"""site: READ-ONLY navigation logic, RTL-safe reads, interface segregation.

Playwright is fully mocked (autospec'd ``Page``) — no browser, no network.
Unit tests validate *flow/logic*; the unverified real selectors are tuned
during the task 3/5 integration runs.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from tests.conftest import fake_input, fake_section, fake_text_el
from translation_pipeline import site as site_mod
from translation_pipeline.page_keys import is_valid_page_key
from translation_pipeline.site import (
    LoginError,
    NavigationError,
    PanelError,
    SiteNavigator,
    browser_session,
)


class RecordingLogger:
    """Captures every log call so a test can prove the password never leaks."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def _rec(self, level: str, event: str, **kw: Any) -> None:
        self.calls.append((level, event, kw))

    def info(self, event: str, **kw: Any) -> None:
        self._rec("info", event, **kw)

    def warning(self, event: str, **kw: Any) -> None:
        self._rec("warning", event, **kw)

    def error(self, event: str, **kw: Any) -> None:
        self._rec("error", event, **kw)

    def debug(self, event: str, **kw: Any) -> None:
        self._rec("debug", event, **kw)


@pytest.fixture
def nav(mock_page: MagicMock, creds_env: dict[str, str]) -> SiteNavigator:
    """A navigator over the mocked page (settings resolved from creds_env)."""
    return SiteNavigator(mock_page)


# --- login -----------------------------------------------------------------


def test_login_fills_creds_and_never_logs_password(
    nav: SiteNavigator,
    mock_page: MagicMock,
    creds_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rec = RecordingLogger()
    monkeypatch.setattr(site_mod, "_log", rec)
    mock_page.get_by_text.return_value.count.return_value = 1

    nav.login()

    mock_page.goto.assert_called_once_with("https://myquds.ibnbadis.org/")
    mock_page.fill.assert_any_call('input[name="username"]', creds_env["username"])
    # The secret reaches page.fill (the only place it is allowed to flow).
    mock_page.fill.assert_any_call('input[name="password"]', creds_env["password"])

    flat = repr(rec.calls)
    assert creds_env["password"] not in flat
    assert any(e == "login_ok" for _, e, _ in rec.calls)
    assert any(kw.get("username") == creds_env["username"] for _, _, kw in rec.calls)
    # Password is never passed as a logging kwarg anywhere.
    assert all(creds_env["password"] not in repr(kw) for _, _, kw in rec.calls)


def test_login_raises_on_listing_timeout(nav: SiteNavigator, mock_page: MagicMock) -> None:
    mock_page.get_by_text.return_value.count.return_value = 1
    mock_page.wait_for_selector.side_effect = PlaywrightTimeoutError("nope")
    with pytest.raises(LoginError):
        nav.login()


# --- semester / book -------------------------------------------------------


@pytest.mark.parametrize(("semester", "label"), [(1, "الفصل 1"), (2, "الفصل 2")])
def test_select_semester(
    nav: SiteNavigator, mock_page: MagicMock, semester: int, label: str
) -> None:
    nav.select_semester(semester)
    mock_page.select_option.assert_called_once_with("select", label=label)


@pytest.mark.parametrize("semester", [0, 3, -1])
def test_select_semester_rejects_out_of_range(nav: SiteNavigator, semester: int) -> None:
    with pytest.raises(NavigationError):
        nav.select_semester(semester)


def test_select_book_returns_book_key_and_navigates(
    nav: SiteNavigator, mock_page: MagicMock
) -> None:
    assert nav.select_book(4, 1) == "year4-sem1"
    mock_page.select_option.assert_called_once_with("select", label="الفصل 1")
    mock_page.get_by_text.assert_any_call("Year 4 English")


def test_select_book_rejects_out_of_range(nav: SiteNavigator) -> None:
    with pytest.raises(ValueError):
        nav.select_book(3, 1)


# --- sidebar / sections ----------------------------------------------------


def test_sections_returns_one_based_index_and_title(
    nav: SiteNavigator, mock_page: MagicMock
) -> None:
    mock_page.query_selector_all.return_value = [
        fake_text_el(" Unit One "),
        fake_text_el("Unit Two"),
    ]
    assert nav.sections() == [(1, "Unit One"), (2, "Unit Two")]


def test_current_section_identified_by_position_and_active_class(
    nav: SiteNavigator, mock_page: MagicMock
) -> None:
    mock_page.query_selector_all.return_value = [
        fake_section("Unit One"),
        fake_section("Unit Two", active=True),
    ]
    assert nav._current_section() == (2, "Unit Two")


def test_current_section_disambiguates_duplicate_titles(
    nav: SiteNavigator, mock_page: MagicMock
) -> None:
    # Two sections share the title "Part 1"; the SECOND is active. Resolving by
    # title text would wrongly return index 1 — index must come from position.
    mock_page.query_selector_all.return_value = [
        fake_section("Part 1"),
        fake_section("Part 1", active=True),
        fake_section("Part 2"),
    ]
    assert nav._current_section() == (2, "Part 1")


def test_current_section_raises_without_active(nav: SiteNavigator, mock_page: MagicMock) -> None:
    mock_page.query_selector_all.return_value = [
        fake_section("Unit One"),
        fake_section("Unit Two"),
    ]
    with pytest.raises(NavigationError):
        nav._current_section()


def test_current_page_number_parses_int(nav: SiteNavigator, mock_page: MagicMock) -> None:
    mock_page.query_selector.return_value = fake_text_el(" 7 ")
    assert nav._current_page_number() == 7


def test_current_page_number_raises_on_non_int(nav: SiteNavigator, mock_page: MagicMock) -> None:
    mock_page.query_selector.return_value = fake_text_el("abc")
    with pytest.raises(NavigationError):
        nav._current_page_number()


@pytest.mark.parametrize(
    ("arrow", "expected", "clicked"),
    [
        (None, False, False),
        ("disabled", False, False),
        ("enabled", True, True),
    ],
)
def test_advance_to_next_page(
    nav: SiteNavigator,
    mock_page: MagicMock,
    arrow: str | None,
    expected: bool,
    clicked: bool,
) -> None:
    settled = MagicMock()
    nav._wait_for_page_settled = settled  # type: ignore[method-assign]
    if arrow is None:
        mock_page.query_selector.return_value = None
        el = None
    else:
        el = MagicMock()
        el.is_disabled.return_value = arrow == "disabled"
        mock_page.query_selector.return_value = el
    assert nav._advance_to_next_page() is expected
    if el is not None:
        assert el.click.called is clicked
    # The settle seam is invoked exactly when (and only when) we advanced, so
    # the next read does not race the SPA page swap.
    assert settled.called is clicked


# --- read_rows (RTL: by name, never by position) ---------------------------


def test_read_rows_groups_by_name_not_dom_order(nav: SiteNavigator, mock_page: MagicMock) -> None:
    none_named = MagicMock()
    none_named.get_attribute.return_value = None  # exercises the None guard
    # Deliberately shuffled DOM order; UQ1 omitted -> must default to "".
    mock_page.query_selector_all.return_value = [
        fake_input("TA1", "a1"),
        fake_input("UQ0", ""),
        fake_input("Level", "3"),  # non-grid -> ignored
        fake_input("TQ0", "q0"),
        fake_input("UA1", "ترجمة"),
        none_named,
        fake_input("TA0", "a0"),
        fake_input("Subject", "English"),  # non-grid -> ignored
        fake_input("TQ1", "q1"),
        fake_input("UA0", ""),
    ]
    rows = nav.read_rows()
    assert len(rows) == 2
    assert rows[0].tq == "q0" and rows[0].ta == "a0"
    assert rows[0].uq == "" and rows[0].ua == ""
    assert rows[1].tq == "q1" and rows[1].ta == "a1"
    assert rows[1].uq == ""  # UQ1 absent -> default ""
    assert rows[1].ua == "ترجمة"


def test_read_rows_empty_grid_returns_empty_list(nav: SiteNavigator, mock_page: MagicMock) -> None:
    mock_page.query_selector_all.return_value = []
    assert nav.read_rows() == []


# --- iter_book_pages (single forward walk) ---------------------------------


def test_iter_book_pages_composes_keys_and_stops(
    nav: SiteNavigator, monkeypatch: pytest.MonkeyPatch
) -> None:
    secs = iter([(1, "Unit One"), (1, "Unit One"), (2, "Unit Two")])
    nums = iter([3, 4, 3])  # page number 3 repeats across sections
    adv = iter([True, True, False])
    monkeypatch.setattr(nav, "_current_section", lambda: next(secs))
    monkeypatch.setattr(nav, "_current_page_number", lambda: next(nums))
    monkeypatch.setattr(nav, "_current_part_number", lambda: None)
    monkeypatch.setattr(nav, "_advance_to_next_page", lambda: next(adv))

    pages = list(nav.iter_book_pages("year4-sem1"))

    assert [p.page_key for p in pages] == [
        "year4-sem1/section-1-unit-one/page-03",
        "year4-sem1/section-1-unit-one/page-04",
        "year4-sem1/section-2-unit-two/page-03",
    ]
    assert [p.section_index for p in pages] == [1, 1, 2]
    assert [p.page_number for p in pages] == [3, 4, 3]
    assert all(is_valid_page_key(p.page_key) for p in pages)
    # Repeated page number 3 yields distinct keys (section slug differentiates).
    assert pages[0].page_key != pages[2].page_key


def test_current_page_key(nav: SiteNavigator, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(nav, "_current_section", lambda: (2, "Our House"))
    monkeypatch.setattr(nav, "_current_page_number", lambda: 15)
    monkeypatch.setattr(nav, "_current_part_number", lambda: 2)
    assert nav.current_page_key("year4-sem1") == "year4-sem1/section-2-our-house/part-2/page-15"


# --- TextApps panel --------------------------------------------------------


def test_open_textapps_sequence(nav: SiteNavigator, mock_page: MagicMock) -> None:
    nav.open_textapps()
    mock_page.hover.assert_called_once_with(".spanner")
    mock_page.get_by_text.assert_any_call("Data iBook (Text Entry)")
    mock_page.get_by_text.assert_any_call("TextApps")
    mock_page.wait_for_selector.assert_called_once_with("input.expinputq", timeout=30_000)


def test_open_textapps_raises_panel_error(nav: SiteNavigator, mock_page: MagicMock) -> None:
    mock_page.wait_for_selector.side_effect = PlaywrightTimeoutError("no grid")
    with pytest.raises(PanelError):
        nav.open_textapps()


def test_close_textapps_sequence(nav: SiteNavigator, mock_page: MagicMock) -> None:
    nav.close_textapps()
    mock_page.get_by_text.assert_any_call("إغلاق")
    mock_page.get_by_text.assert_any_call("Close")


# --- Interface segregation (scrape provably cannot mutate the site) --------


def test_sitenavigator_exposes_no_write_surface() -> None:
    for forbidden in ("fill_translation", "save_page", "read_field_value"):
        assert not hasattr(SiteNavigator, forbidden)


def test_site_module_does_not_import_write_helper() -> None:
    # Structural: importing write_helper would expose it as a module attribute.
    assert not hasattr(site_mod, "write_helper")

    # Rigorous (AST, not raw text — docstrings legitimately *describe* the
    # segregation): no import resolves to the write surface, and no
    # identifier/attribute in the code references a write primitive.
    tree = ast.parse(Path(site_mod.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    identifiers: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            imported.add(base)
            imported.update(f"{base}.{a.name}" for a in node.names)
        elif isinstance(node, ast.Name):
            identifiers.add(node.id)
        elif isinstance(node, ast.Attribute):
            identifiers.add(node.attr)

    assert not any("write_helper" in m for m in imported)
    forbidden = {
        "write_helper",
        "fill_translation",
        "save_page",
        "read_field_value",
        "SAVE_BUTTON_SELECTOR",
        "SAVE_ENDPOINT_SUBSTR",
    }
    assert forbidden.isdisjoint(imported)
    assert forbidden.isdisjoint(identifiers)


# --- browser_session lifecycle (sync_playwright patched) -------------------


def test_browser_session_launches_and_tears_down(
    monkeypatch: pytest.MonkeyPatch, creds_env: dict[str, str]
) -> None:
    pw = MagicMock()
    browser = MagicMock()
    context = MagicMock()
    sp = MagicMock()
    sp.start.return_value = pw
    pw.chromium.launch.return_value = browser
    browser.new_context.return_value = context
    context.new_page.return_value = MagicMock()
    monkeypatch.setattr(site_mod, "sync_playwright", lambda: sp)

    with browser_session() as session_nav:
        assert isinstance(session_nav, SiteNavigator)

    pw.chromium.launch.assert_called_once_with(headless=True)
    browser.new_context.assert_called_once_with(locale="ar")
    browser.close.assert_called_once()
    pw.stop.assert_called_once()
