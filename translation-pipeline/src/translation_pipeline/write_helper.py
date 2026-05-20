"""Side-effecting Playwright primitives — imported ONLY by write-back (task 5).

Keeping these out of :mod:`translation_pipeline.site` is a structural interface
segregation guarantee: the scrape path cannot import a write surface, so it
provably cannot mutate the site.

This module provides only *primitives*. The empty-form-skip and the
filled-form single-retry POLICY is task 5's responsibility; :func:`save_page`
just performs one Save click and classifies the response.

Save-success contract (authoritative — memory ``ibnbadis-save-behavior``):

- POST to ``…/userqanssave.php`` body ``["", true]``  -> persisted
- body ``["", false]``                                -> rejected
- HTTP 5xx / timeout / unparseable body               -> server error

The fleeting green Save-button flash is **never** inspected (the deliberate
CSTC-4 divergence from CSTC-3's agentic green-flash heuristic).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum, auto

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import FrameLocator, Page, Response
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from translation_pipeline.logging_config import get_logger
from translation_pipeline.selectors import (
    SAVE_BUTTON_SELECTOR,
    SAVE_ENDPOINT_SUBSTR,
    SAVE_RESPONSE_TIMEOUT_MS,
    TEXTAPPS_IFRAME_SELECTOR,
    Field,
    TargetField,
    field_input_css,
)

_log = get_logger(__name__)

#: The TextApps grid + Save button live inside the cross-origin ``#LFrm``
#: iframe (same frame the READ-ONLY ``site.read_rows`` uses) — every
#: fill/read/Save here is frame-scoped, never on the top-level page.
#:
#: Set-value JS for a (possibly **hidden**) Arabic ``UQ``/``UA`` input: the
#: RTL layout renders these cells ``hidden``, so ``Locator.fill`` (which
#: requires visibility) cannot be used. ``Locator.evaluate`` only needs the
#: element ATTACHED, so we set ``.value`` directly and dispatch the
#: ``input``/``change`` events the site's ``submitForms`` serialisation
#: relies on. (Mirrors the read path's "address hidden inputs by name"
#: rationale. Live Save-flow confirmation is the writeback canary's job —
#: ``# VERIFY-ON-LIVE-WRITEBACK``.)
_SET_VALUE_JS = (
    "(el, v) => { el.value = v;"
    " el.dispatchEvent(new Event('input', { bubbles: true }));"
    " el.dispatchEvent(new Event('change', { bubbles: true })); }"
)


def _textapps_frame(page: Page) -> FrameLocator:
    """The cross-origin TextApps iframe (same ``#LFrm`` the read path uses)."""
    return page.frame_locator(TEXTAPPS_IFRAME_SELECTOR)


class SaveOutcome(Enum):
    """Classification of a ``userqanssave.php`` response."""

    PERSISTED = auto()  # body == ["", true]
    REJECTED = auto()  # body == ["", false]
    SERVER_ERROR = auto()  # 5xx / timeout / unparseable / unexpected body


@dataclass(frozen=True)
class SaveResult:
    """Outcome of one Save click plus raw diagnostics."""

    outcome: SaveOutcome
    http_status: int | None
    raw_body: str | None


def fill_translation(page: Page, row_index: int, field: TargetField, value: str) -> None:
    """Fill a single Arabic translation cell (``UQ{N}``/``UA{N}``) by index.

    Args:
        page: the Playwright page.
        row_index: 0-based row index.
        field: a :class:`TargetField` (UQ/UA only). ``TQ``/``TA`` or any
            non-:class:`TargetField` is rejected — the English source is never
            edited, ``+`` is never used and rows are never added/removed.
        value: the Arabic string to write.

    Raises:
        ValueError: if ``field`` is not a :class:`TargetField`, or
            ``row_index`` is negative (via :func:`field_input_css`).
    """
    if not isinstance(field, TargetField):
        raise ValueError(f"fill_translation only writes UQ/UA TargetField (got {field!r})")
    css = field_input_css(field, row_index)  # raises on a negative index
    # Frame-scoped, hidden-input safe (see _SET_VALUE_JS): never the top page,
    # never a visibility-gated fill, never TQ/TA, never the ``+`` button.
    _textapps_frame(page).locator(css).evaluate(_SET_VALUE_JS, value)


def read_field_value(page: Page, row_index: int, field: Field) -> str:
    """Return the live ``.value`` of one field (task 5 no-overwrite guard).

    Frame-scoped; ``input_value`` reads a hidden input fine (same as the
    READ-ONLY ``site.read_rows`` path).
    """
    return _textapps_frame(page).locator(field_input_css(field, row_index)).input_value()


def _is_save_response(response: Response) -> bool:
    """Match the cross-origin ``userqanssave.php`` POST by URL substring."""
    return SAVE_ENDPOINT_SUBSTR in response.url


def save_page(page: Page, *, timeout_ms: int = SAVE_RESPONSE_TIMEOUT_MS) -> SaveResult:
    """Click Save once and classify the ``userqanssave.php`` response.

    Success is keyed strictly off the response body — the Save button's colour
    or style is never read.
    """
    try:
        # ``expect_response`` stays page-level (it captures sub-frame requests
        # too); only the Save click is frame-scoped (the button is in #LFrm).
        with page.expect_response(_is_save_response, timeout=timeout_ms) as info:
            _textapps_frame(page).locator(SAVE_BUTTON_SELECTOR).click()
        response = info.value
    except PlaywrightTimeoutError:
        _log.warning("save_no_response", reason="timeout")
        return SaveResult(SaveOutcome.SERVER_ERROR, None, None)

    status = response.status
    raw_body: str | None
    try:
        raw_body = response.text()
    except PlaywrightError:  # includes PlaywrightTimeoutError
        raw_body = None

    if status >= 500:
        _log.warning("save_server_error", http_status=status)
        return SaveResult(SaveOutcome.SERVER_ERROR, status, raw_body)

    try:
        parsed = json.loads(raw_body) if raw_body is not None else None
    except json.JSONDecodeError:
        _log.warning("save_unparseable_body", http_status=status)
        return SaveResult(SaveOutcome.SERVER_ERROR, status, raw_body)

    if parsed == ["", True]:
        return SaveResult(SaveOutcome.PERSISTED, status, raw_body)
    if parsed == ["", False]:
        return SaveResult(SaveOutcome.REJECTED, status, raw_body)

    _log.warning("save_unexpected_body", http_status=status)
    return SaveResult(SaveOutcome.SERVER_ERROR, status, raw_body)
