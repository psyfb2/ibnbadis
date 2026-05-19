"""Centralized selectors, labels, timeouts and TextApps field helpers.

This module is **pure**: it imports no Playwright and performs no I/O. It is the
single place where every CSS/text selector lives so that, when the unverified
selectors are tuned against the live site during tasks 3/5 integration runs,
only this file changes.

Selector reality check
----------------------
The CSTC-3 RUNBOOK and the Jira UI screenshots give *labels/text and DOM facts*
(``input.expinputq``; the ``UQ/UA/TQ/TA{N}`` ``name`` scheme) but **no exact CSS
selectors** for login, the semester dropdown, the sidebar, the page arrows, the
spanner, the modal tabs or the Save button. Every such constant below is a
best-effort guess marked ``# VERIFY-ON-LIVE``. Unit tests validate logic/flow
against a mocked Playwright ``Page`` — they cannot validate real selectors; that
is integration work in tasks 3/5 (which require ``make install-browsers``).

Confirmed field mapping (authoritative — screenshot ``textapps-translated-
fields.png`` + ``progress.txt``):

===========  ================================  ========  ====================
``name``     Column                            Language  Role for CSTC-4
===========  ================================  ========  ====================
``UQ{N}``    Translated Questions              Arabic    WRITE target
``UA{N}``    Translated Answers                Arabic    WRITE target
``TQ{N}``    Page Questions                    English   READ-ONLY source
``TA{N}``    Page Answers                      English   READ-ONLY source
===========  ================================  ========  ====================

All four are ``<input class="expinputq">`` addressed strictly by ``name``,
**0-based**, never by visual position (the UI is right-to-left).
"""

from __future__ import annotations

import re
from enum import StrEnum


class Field(StrEnum):
    """Every addressable TextApps grid field by its ``name`` prefix."""

    UQ = "UQ"  # Translated Questions  (Arabic, write target)
    UA = "UA"  # Translated Answers    (Arabic, write target)
    TQ = "TQ"  # Page Questions        (English, read-only source)
    TA = "TA"  # Page Answers          (English, read-only source)


class TargetField(StrEnum):
    """The write targets only (Arabic translation columns).

    Deliberately an *independent* ``StrEnum`` (no inheritance from
    :class:`Field`) so passing a :class:`TargetField` where a :class:`Field` is
    expected (or vice-versa) is a static type error — the write-helper guard is
    therefore enforced by ``mypy`` as well as at runtime.
    """

    UQ = "UQ"
    UA = "UA"


#: Matches a TextApps input ``name`` like ``UQ0`` / ``TA12`` (0-based index).
FIELD_NAME_RE: re.Pattern[str] = re.compile(r"^(UQ|UA|TQ|TA)(\d+)$")

#: Enumeration selector for every grid input on a page.
ROW_INPUT_CSS = "input.expinputq"


def field_name(field: Field | TargetField, index: int) -> str:
    """Return the ``name`` attribute for ``field`` at 0-based ``index``.

    Args:
        field: a :class:`Field` or :class:`TargetField` (only ``.value`` used,
            so the union is accepted without a ``# type: ignore``).
        index: 0-based row index.

    Raises:
        ValueError: if ``index`` is negative.
    """
    if index < 0:
        raise ValueError(f"row index must be >= 0 (got {index!r})")
    return f"{field.value}{index}"


def parse_field_name(name: str) -> tuple[Field, int] | None:
    """Parse a grid input ``name`` into ``(Field, 0-based index)``.

    Returns ``None`` for anything that is not a ``UQ/UA/TQ/TA{N}`` name (e.g.
    the ``Level``/``Subject`` inputs or the ``+`` button), so callers can simply
    skip non-matching inputs.
    """
    match = FIELD_NAME_RE.match(name)
    if match is None:
        return None
    return Field(match.group(1)), int(match.group(2))


def field_input_css(field: Field | TargetField, index: int) -> str:
    """Return an ``input[name="..."]`` CSS selector for one grid field."""
    return f'input[name="{field_name(field, index)}"]'


# --- Login -----------------------------------------------------------------
LOGIN_USERNAME_SELECTOR = 'input[name="username"]'  # VERIFY-ON-LIVE
LOGIN_PASSWORD_SELECTOR = 'input[name="password"]'  # VERIFY-ON-LIVE
#: The submit button text varies in the RUNBOOK ("دخول") vs a note ("شغول").
LOGIN_SUBMIT_TEXTS: tuple[str, ...] = ("دخول", "شغول")  # VERIFY-ON-LIVE
#: An element that only exists once the books listing has loaded (login OK).
LISTING_READY_SELECTOR = "table"  # VERIFY-ON-LIVE

# --- Semester / book selection --------------------------------------------
SEMESTER_DROPDOWN_SELECTOR = "select"  # VERIFY-ON-LIVE
#: Semester -> visible option label in the dropdown.
SEMESTER_OPTION: dict[int, str] = {1: "الفصل 1", 2: "الفصل 2"}  # VERIFY-ON-LIVE
#: Book row is matched by this text prefix, e.g. "Year 4 English".
BOOK_ROW_TEXT_TMPL = "Year {year} English"  # VERIFY-ON-LIVE

# --- Ebook viewer / navigation --------------------------------------------
SIDEBAR_SECTION_SELECTOR = ".sidebar .section"  # VERIFY-ON-LIVE
SIDEBAR_SECTION_ACTIVE_SELECTOR = ".sidebar .section.active"  # VERIFY-ON-LIVE
#: Token expected in the active sidebar section element's class list. The
#: active section is identified by DOM POSITION + this class (never by title
#: text, which can collide across sections, e.g. a repeated "Part 1").
SIDEBAR_ACTIVE_CLASS = "active"  # VERIFY-ON-LIVE
PAGE_NEXT_ARROW_SELECTOR = ".page-nav .next"  # VERIFY-ON-LIVE
PAGE_PREV_ARROW_SELECTOR = ".page-nav .prev"  # VERIFY-ON-LIVE
PAGE_NUMBER_ACTIVE_SELECTOR = ".page-nav .current"  # VERIFY-ON-LIVE

# --- Admin & Dev -> Data iBook (Text Entry) -> TextApps -------------------
SPANNER_TRIGGER_SELECTOR = ".spanner"  # VERIFY-ON-LIVE
DATA_IBOOK_TEXT = "Data iBook (Text Entry)"  # VERIFY-ON-LIVE
TEXTAPPS_TAB_TEXT = "TextApps"  # VERIFY-ON-LIVE
MODAL_CLOSE_TEXT = "إغلاق"  # VERIFY-ON-LIVE
ADMIN_PANEL_CLOSE_TEXT = "Close"  # VERIFY-ON-LIVE

# --- Save ------------------------------------------------------------------
SAVE_BUTTON_SELECTOR = "button.save"  # VERIFY-ON-LIVE
#: Substring of the cross-origin POST that confirms a save (host-agnostic: the
#: app is myquds.ibnbadis.org but the POST goes to dev.ibnbadis.org).
SAVE_ENDPOINT_SUBSTR = "userqanssave.php"

# --- Timeouts (module constants; the task-1 Settings contract is fixed) -----
DEFAULT_TIMEOUT_MS = 30_000
SAVE_RESPONSE_TIMEOUT_MS = 15_000
