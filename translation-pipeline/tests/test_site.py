"""site: READ-ONLY navigation logic, RTL-safe reads, interface segregation.

Playwright is fully mocked (autospec'd ``Page``) — no browser, no network.
Unit tests validate *flow/logic*; the live-verified selectors themselves are
exercised by the integration scrape (see ``docs/live-selectors-tuning.md``).
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from tests.conftest import fake_input
from translation_pipeline import site as site_mod
from translation_pipeline.page_keys import is_valid_page_key
from translation_pipeline.site import (
    LoginError,
    NavigationError,
    PanelError,
    SiteNavigator,
    _SidebarUnit,
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


def fake_tree_el(
    tag: str,
    *,
    title: str | None = None,
    href: str | None = None,
    text: str | None = None,
) -> MagicMock:
    """A fake sidebar element (SECTION span or Part anchor) for tree parsing.

    The live sidebar carries NO page range (every Part's ``data-name`` is the
    literal ``"X"``), so this helper deliberately models only ``tagName``,
    ``title``, ``href`` and text content.
    """
    el = MagicMock()
    el.evaluate.return_value = tag  # responds to "e => e.tagName"
    el.get_attribute.side_effect = lambda name: {"title": title, "href": href}.get(name)
    el.text_content.return_value = text
    return el


# --- login -----------------------------------------------------------------


def test_login_fills_creds_and_never_logs_password(
    nav: SiteNavigator,
    mock_page: MagicMock,
    creds_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rec = RecordingLogger()
    monkeypatch.setattr(site_mod, "_log", rec)

    nav.login()

    mock_page.goto.assert_called_once_with("https://myquds.ibnbadis.org/")
    mock_page.fill.assert_any_call('input[type="text"][name="form_login"]', creds_env["username"])
    # The secret reaches page.fill (the only place it is allowed to flow).
    mock_page.fill.assert_any_call(
        'input[type="password"][name="form_password"]', creds_env["password"]
    )
    # Submit is an <input type=submit>: clicked by selector, never by text.
    mock_page.click.assert_called_once_with("#logbutt")

    flat = repr(rec.calls)
    assert creds_env["password"] not in flat
    assert any(e == "login_ok" for _, e, _ in rec.calls)
    assert any(kw.get("username") == creds_env["username"] for _, _, kw in rec.calls)
    assert all(creds_env["password"] not in repr(kw) for _, _, kw in rec.calls)


def test_login_raises_on_listing_timeout(nav: SiteNavigator, mock_page: MagicMock) -> None:
    mock_page.wait_for_selector.side_effect = PlaywrightTimeoutError("nope")
    with pytest.raises(LoginError):
        nav.login()


# --- book selection --------------------------------------------------------


@pytest.mark.parametrize(
    ("year", "sem", "bk", "name", "sel_value"),
    [
        (4, 1, "year4-sem1", "Year 4 English A", "1"),
        (4, 2, "year4-sem2", "Year 4 English B", "2"),
        (6, 2, "year6-sem2", "Year 6 English B", "2"),
    ],
)
def test_select_book_selects_semester_then_clicks_exact_link(
    nav: SiteNavigator,
    mock_page: MagicMock,
    year: int,
    sem: int,
    bk: str,
    name: str,
    sel_value: str,
) -> None:
    assert nav.select_book(year, sem) == bk
    # Semester select FIRST (sem-2 rows are display:none until then), then the
    # now-visible exact-name book link.
    mock_page.select_option.assert_called_once_with("#changeYear", sel_value)
    mock_page.get_by_role.assert_called_once_with("link", name=name, exact=True)
    mock_page.get_by_role.return_value.first.click.assert_called_once()


def test_select_book_rejects_out_of_range(nav: SiteNavigator) -> None:
    with pytest.raises(ValueError):
        nav.select_book(3, 1)


def test_select_book_raises_when_viewer_does_not_load(
    nav: SiteNavigator, mock_page: MagicMock
) -> None:
    mock_page.wait_for_selector.side_effect = PlaywrightTimeoutError("no sidebar")
    with pytest.raises(NavigationError):
        nav.select_book(4, 1)


# --- sidebar Section -> Part tree parsing ----------------------------------


def test_parse_sidebar_units_orders_and_attributes_sections(
    nav: SiteNavigator, mock_page: MagicMock
) -> None:
    mock_page.query_selector_all.return_value = [
        # Orphan Part before any Section header -> becomes its own Section
        # (its own ``title`` is the section title).
        fake_tree_el("A", href="/content.php?gid=1069_0_0", title="xxxxx"),
        # A skip-nav link sharing the path but with a #fragment -> ignored.
        fake_tree_el("A", href="/content.php?gid=1070_0_1#content", title="Go to content"),
        fake_tree_el("SPAN", title="Section 1: A new friend"),
        fake_tree_el("A", href="/content.php?gid=1072_0_2", title="Part 1"),
        fake_tree_el("A", href="/content.php?gid=1073_0_3", title="Part 2"),
        fake_tree_el("SPAN", title="Section 2: Our house"),
        fake_tree_el("A", href="/content.php?gid=1075_0_4", title="Part 1"),
    ]
    units = nav._parse_sidebar_units()
    # No page range is parsed from the sidebar (it carries none); each unit is
    # just identity + Section grouping. Ranges are discovered live per Part.
    assert units == [
        _SidebarUnit(1, "xxxxx", "/content.php?gid=1069_0_0"),
        _SidebarUnit(2, "Section 1: A new friend", "/content.php?gid=1072_0_2"),
        _SidebarUnit(2, "Section 1: A new friend", "/content.php?gid=1073_0_3"),
        _SidebarUnit(3, "Section 2: Our house", "/content.php?gid=1075_0_4"),
    ]


def test_parse_sidebar_units_raises_when_empty(nav: SiteNavigator, mock_page: MagicMock) -> None:
    mock_page.query_selector_all.return_value = []
    with pytest.raises(NavigationError):
        nav._parse_sidebar_units()


# --- page number / part ----------------------------------------------------


def test_current_page_number_parses_int(nav: SiteNavigator, mock_page: MagicMock) -> None:
    el = MagicMock()
    el.text_content.return_value = " 7 "
    mock_page.query_selector.return_value = el
    assert nav._current_page_number() == 7


def test_current_page_number_raises_on_non_int(nav: SiteNavigator, mock_page: MagicMock) -> None:
    el = MagicMock()
    el.text_content.return_value = "abc"
    mock_page.query_selector.return_value = el
    with pytest.raises(NavigationError):
        nav._current_page_number()


def test_current_page_number_raises_when_absent(nav: SiteNavigator, mock_page: MagicMock) -> None:
    # No .currentpage AND not a lone single-page link -> unreadable.
    mock_page.query_selector.return_value = None
    mock_page.query_selector_all.return_value = []
    with pytest.raises(NavigationError):
        nav._current_page_number()


def test_current_page_number_single_page_part_uses_sole_link(
    nav: SiteNavigator, mock_page: MagicMock
) -> None:
    # A single-page Part ("Ending") has one #page link with NO currentpage
    # class; that lone link IS the current page.
    sole = MagicMock()
    sole.text_content.return_value = "64"
    mock_page.query_selector.return_value = None  # no .currentpage marker
    mock_page.query_selector_all.return_value = [sole]
    assert nav._current_page_number() == 64


def test_current_part_number_is_always_none(nav: SiteNavigator) -> None:
    # Divergence C: no /part- segment is ever emitted.
    assert nav._current_part_number() is None


def test_at_last_page_true_when_next_disabled(
    nav: SiteNavigator, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Multi-page Part on its last page: #next carries class "disabled".
    monkeypatch.setattr(nav, "_next_disabled", lambda: True)
    assert nav._at_last_page() is True


def test_at_last_page_true_for_single_page_part(
    nav: SiteNavigator, mock_page: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Single-page Part: #next not disabled, no .currentpage, exactly 1 link.
    monkeypatch.setattr(nav, "_next_disabled", lambda: False)
    mock_page.query_selector.return_value = None  # no .currentpage
    mock_page.query_selector_all.return_value = [MagicMock()]  # one #page link
    assert nav._at_last_page() is True


def test_at_last_page_false_mid_multi_page_part(
    nav: SiteNavigator, mock_page: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Mid multi-page Part: #next enabled and a .currentpage marker present.
    monkeypatch.setattr(nav, "_next_disabled", lambda: False)
    mock_page.query_selector.return_value = MagicMock()  # .currentpage present
    assert nav._at_last_page() is False


# --- iter_book_pages (Part-by-Part forward walk) ---------------------------


def test_iter_book_pages_steps_within_parts_and_composes_keys(
    nav: SiteNavigator, mock_page: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    units = [
        _SidebarUnit(1, "Section 1: A new friend", "/content.php?gid=1072_0_2"),
        _SidebarUnit(2, "Section 2: Our house", "/content.php?gid=1075_0_4"),
    ]
    monkeypatch.setattr(nav, "_parse_sidebar_units", lambda: units)
    # Part 1 walks 4 -> 5 -> 6 (bounded by #next becoming disabled on page 6);
    # Part 2 is a single page (#next disabled immediately).
    nums = iter([4, 5, 6, 10])
    monkeypatch.setattr(nav, "_current_page_number", lambda: next(nums))
    # Part 1 ends when page 6 is the last page; Part 2 is single-page.
    at_last = iter([False, False, True, True])
    monkeypatch.setattr(nav, "_at_last_page", lambda: next(at_last))
    monkeypatch.setattr(nav, "_wait_for_page_settled", lambda prev: None)

    pages = list(nav.iter_book_pages("year4-sem1"))

    assert [p.page_key for p in pages] == [
        "year4-sem1/section-1-section-1-a-new-friend/page-04",
        "year4-sem1/section-1-section-1-a-new-friend/page-05",
        "year4-sem1/section-1-section-1-a-new-friend/page-06",
        "year4-sem1/section-2-section-2-our-house/page-10",
    ]
    assert [p.section_index for p in pages] == [1, 1, 1, 2]
    assert [p.page_number for p in pages] == [4, 5, 6, 10]
    assert all(p.part_number is None for p in pages)
    assert all(is_valid_page_key(p.page_key) for p in pages)
    # Navigated to each Part's gid URL (absolute, joined to base_url).
    assert mock_page.goto.call_args_list == [
        call("https://myquds.ibnbadis.org/content.php?gid=1072_0_2"),
        call("https://myquds.ibnbadis.org/content.php?gid=1075_0_4"),
    ]
    # Two next-clicks inside Part 1 (4->5, 5->6); none in the single-page Part.
    assert mock_page.click.call_count == 2


def test_iter_book_pages_breaks_a_stuck_part(
    nav: SiteNavigator, mock_page: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    units = [_SidebarUnit(1, "Sec", "/content.php?gid=1_0_0")]
    monkeypatch.setattr(nav, "_parse_sidebar_units", lambda: units)
    # Never at the last page AND the page number never advances past 4
    # -> the stuck-nav guard must still break (no infinite loop).
    monkeypatch.setattr(nav, "_current_page_number", lambda: 4)
    monkeypatch.setattr(nav, "_at_last_page", lambda: False)
    monkeypatch.setattr(nav, "_wait_for_page_settled", lambda prev: None)

    pages = list(nav.iter_book_pages("year4-sem1"))

    assert [p.page_number for p in pages] == [4]  # yielded once, then bailed


def test_iter_book_pages_skips_placeholder_part_without_pager(
    nav: SiteNavigator, mock_page: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A placeholder Part (e.g. the dashed "xxxxx" intro) never loads a pager:
    # it must be skipped (non-fatal, resumable), not raise.
    units = [_SidebarUnit(1, "xxxxx", "/content.php?gid=1069_0_0")]
    monkeypatch.setattr(nav, "_parse_sidebar_units", lambda: units)
    mock_page.wait_for_selector.side_effect = PlaywrightTimeoutError("no pager")

    def _fail() -> int:  # must never be reached for a skipped Part
        raise AssertionError("_current_page_number called on a placeholder Part")

    monkeypatch.setattr(nav, "_current_page_number", _fail)
    rec = RecordingLogger()
    monkeypatch.setattr(site_mod, "_log", rec)

    pages = list(nav.iter_book_pages("year4-sem1"))

    assert pages == []
    assert any(e == "part_has_no_pages" for _, e, _ in rec.calls)
    mock_page.click.assert_not_called()


# --- page settle -----------------------------------------------------------


def test_wait_for_page_settled_waits_on_page_number_then_load_state(
    nav: SiteNavigator, mock_page: MagicMock
) -> None:
    nav._wait_for_page_settled("3")

    mock_page.wait_for_function.assert_called_once()
    _, kwargs = mock_page.wait_for_function.call_args
    assert kwargs["arg"] == [site_mod.PAGE_CURRENT_SELECTOR, "3"]
    assert kwargs["timeout"] == 30_000
    mock_page.wait_for_load_state.assert_called_once_with("networkidle", timeout=30_000)


def test_wait_for_page_settled_never_raises_when_all_signals_time_out(
    nav: SiteNavigator, mock_page: MagicMock
) -> None:
    mock_page.wait_for_function.side_effect = PlaywrightTimeoutError("no change")
    mock_page.wait_for_load_state.side_effect = PlaywrightTimeoutError("never settles")

    nav._wait_for_page_settled("3")  # must not raise

    assert mock_page.wait_for_load_state.call_args_list == [
        call("networkidle", timeout=30_000),
        call("domcontentloaded", timeout=30_000),
    ]


# --- read_rows (RTL: by name, never by position; inside the iframe) --------


def _wire_frame_rows(mock_page: MagicMock, els: list[MagicMock]) -> MagicMock:
    """Wire ``page.frame_locator(...).locator(ROW_INPUT_CSS).all()`` -> els."""
    frame = MagicMock()
    inputs = MagicMock()
    inputs.all.return_value = els
    frame.locator.return_value = inputs
    mock_page.frame_locator.return_value = frame
    return frame


def test_read_rows_groups_by_name_not_dom_order(nav: SiteNavigator, mock_page: MagicMock) -> None:
    none_named = MagicMock()
    none_named.get_attribute.return_value = None  # exercises the None guard
    frame = _wire_frame_rows(
        mock_page,
        [
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
        ],
    )
    rows = nav.read_rows()
    assert len(rows) == 2
    assert rows[0].tq == "q0" and rows[0].ta == "a0"
    assert rows[0].uq == "" and rows[0].ua == ""
    assert rows[1].tq == "q1" and rows[1].ta == "a1"
    assert rows[1].uq == ""  # UQ1 absent -> default ""
    assert rows[1].ua == "ترجمة"
    # Reads went through the cross-origin TextApps iframe.
    mock_page.frame_locator.assert_called_once_with(site_mod.TEXTAPPS_IFRAME_SELECTOR)
    frame.locator.assert_called_once_with(site_mod.ROW_INPUT_CSS)


def test_read_rows_empty_grid_returns_empty_list(nav: SiteNavigator, mock_page: MagicMock) -> None:
    _wire_frame_rows(mock_page, [])
    assert nav.read_rows() == []


# --- TextApps panel (iframe) ----------------------------------------------


def test_open_textapps_sequence(nav: SiteNavigator, mock_page: MagicMock) -> None:
    frame = MagicMock()
    mock_page.frame_locator.return_value = frame

    nav.open_textapps()

    assert mock_page.click.call_args_list == [
        call("#adminTab_"),
        call("#xwcode"),
    ]
    mock_page.frame_locator.assert_called_once_with("#LFrm")
    frame.get_by_text.assert_called_once_with("TextApps", exact=True)
    frame.get_by_text.return_value.first.click.assert_called_once()
    frame.locator.assert_called_once_with("input.expinputq")
    # ATTACHED, not visible: the live form's first input (Arabic UQ0) is
    # hidden by the RTL layout but fully readable by read_rows().
    frame.locator.return_value.first.wait_for.assert_called_once_with(
        state="attached", timeout=30_000
    )


def test_open_textapps_raises_panel_error_when_grid_absent(
    nav: SiteNavigator, mock_page: MagicMock
) -> None:
    frame = MagicMock()
    frame.locator.return_value.first.wait_for.side_effect = PlaywrightTimeoutError("no grid")
    mock_page.frame_locator.return_value = frame
    with pytest.raises(PanelError):
        nav.open_textapps()


def test_close_textapps_clicks_modal_then_panel(nav: SiteNavigator, mock_page: MagicMock) -> None:
    nav.close_textapps()
    assert mock_page.locator.call_args_list == [
        call("#secondClose"),
        call('a[href*="closeAdminMenu"]'),
    ]


def test_close_textapps_tolerates_absent_control(
    nav: SiteNavigator, mock_page: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = RecordingLogger()
    monkeypatch.setattr(site_mod, "_log", rec)
    mock_page.locator.return_value.first.click.side_effect = PlaywrightTimeoutError("gone")

    nav.close_textapps()  # must not raise

    assert sum(e == "textapps_close_control_absent" for _, e, _ in rec.calls) == 2


# --- Interface segregation (scrape provably cannot mutate the site) --------


def test_page_property_returns_injected_page_read_only(
    nav: SiteNavigator, mock_page: MagicMock
) -> None:
    assert nav.page is mock_page
    with pytest.raises(AttributeError):
        nav.page = MagicMock()  # type: ignore[misc]


def test_sitenavigator_exposes_no_write_surface() -> None:
    for forbidden in ("fill_translation", "save_page", "read_field_value"):
        assert not hasattr(SiteNavigator, forbidden)


def test_site_module_does_not_import_write_helper() -> None:
    assert not hasattr(site_mod, "write_helper")

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
