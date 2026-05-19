"""Shared fixtures.

Task-1 tests are pure-Python (no Playwright import, no network). Task-2 tests
add Playwright-MOCK fixtures: importing ``playwright.sync_api`` and
``create_autospec(Page)`` needs **no browser binary** and makes **no network
calls** — the real Chromium is only ever launched by ``site.browser_session``,
which is itself unit-tested with ``sync_playwright`` patched.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, create_autospec

import pytest
from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

# A representative Arabic string used to assert UTF-8 round-tripping.
ARABIC_Q = "ما اسمك؟"
ARABIC_A = "اسمي علي."

#: The default cross-origin Save endpoint URL (see memory ibnbadis-save-behavior).
SAVE_URL = "https://dev.ibnbadis.org/TextEntry/userqanssave.php"


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    """A throwaway store path inside a tmp dir (parent exists)."""
    return tmp_path / "store" / "translations.json"


@pytest.fixture
def clean_ibnbadis_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Hermetic config env: drop ambient IBNBADIS_*/LOG_LEVEL AND chdir into an
    empty tmp dir so a developer's gitignored ``.env`` cannot leak in and give a
    false green (pydantic-settings reads ``.env`` relative to CWD)."""
    for var in (
        "IBNBADIS_USERNAME",
        "IBNBADIS_PASSWORD",
        "IBNBADIS_BASE_URL",
        "IBNBADIS_STORE_PATH",
        "LOG_LEVEL",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def creds_env(monkeypatch: pytest.MonkeyPatch, clean_ibnbadis_env: None) -> dict[str, str]:
    """Set valid credential env vars; return the values for assertions."""
    values = {"username": "fadi", "password": "s3cr3t-do-not-log"}
    monkeypatch.setenv("IBNBADIS_USERNAME", values["username"])
    monkeypatch.setenv("IBNBADIS_PASSWORD", values["password"])
    return values


# --- Playwright mock helpers (task 2) --------------------------------------


class FakeResponse:
    """Minimal stand-in for ``playwright.sync_api.Response``.

    ``save_page`` only touches ``.status``, ``.url`` and ``.text()``.
    """

    def __init__(self, status: int, url: str, text: str) -> None:
        self.status = status
        self.url = url
        self._text = text

    def text(self) -> str:
        return self._text


@pytest.fixture
def mock_page() -> MagicMock:
    """An autospec'd Playwright ``Page`` (real signatures enforced, no browser).

    Method return values are plain mocks by default; tests configure the few
    they exercise (``query_selector_all``, ``query_selector``, ``input_value``,
    ``expect_response`` …).
    """
    return create_autospec(Page, instance=True)


@pytest.fixture
def make_save_response() -> Callable[..., FakeResponse]:
    """Factory for a fake ``userqanssave.php`` response.

    Pass ``body`` (JSON-serialised) for the normal cases, or ``raw`` for a
    deliberately malformed body.
    """

    def _make(
        *,
        status: int = 200,
        body: Any = None,
        raw: str | None = None,
        url: str = SAVE_URL,
    ) -> FakeResponse:
        text = raw if raw is not None else json.dumps(body)
        return FakeResponse(status=status, url=url, text=text)

    return _make


@pytest.fixture
def wire_save_response(mock_page: MagicMock) -> Callable[..., MagicMock | None]:
    """Wire ``mock_page.expect_response`` as a context manager.

    With ``raise_timeout=True`` the call raises ``PlaywrightTimeoutError`` (no
    matching response). Otherwise the context manager yields an ``info`` whose
    ``.value`` is ``response``.
    """

    def _wire(
        response: FakeResponse | None = None, *, raise_timeout: bool = False
    ) -> MagicMock | None:
        if raise_timeout:
            mock_page.expect_response.side_effect = PlaywrightTimeoutError("no response")
            return None
        info = MagicMock()
        info.value = response
        cm = MagicMock()
        cm.__enter__.return_value = info
        cm.__exit__.return_value = False
        mock_page.expect_response.return_value = cm
        return info

    return _wire


def fake_input(name: str, value: str) -> MagicMock:
    """A fake grid ``<input>`` element handle (``get_attribute``/``input_value``)."""
    el = MagicMock()
    el.get_attribute.return_value = name
    el.input_value.return_value = value
    return el


def fake_text_el(text: str) -> MagicMock:
    """A fake element exposing ``text_content()``."""
    el = MagicMock()
    el.text_content.return_value = text
    return el
