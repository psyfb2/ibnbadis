"""scrape (step 1): pure-core merge-refresh logic + orchestration.

The site module is fully mocked (autospec'd ``SiteNavigator``,
``browser_session`` patched) — **no browser, no network**. Pure-core tests run
with zero mocking.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, call, create_autospec

import pytest

from translation_pipeline import scrape
from translation_pipeline.core import build_row
from translation_pipeline.models import Page, Row, RowFields
from translation_pipeline.page_keys import book_key, is_valid_page_key
from translation_pipeline.scrape import (
    SKIP_NO_ENGLISH,
    merge_page,
)
from translation_pipeline.site import (
    NavigationError,
    PageContext,
    PanelError,
    SiteNavigator,
)
from translation_pipeline.store import TranslationStore, load_store, save_store

KEY_04 = "year4-sem1/section-1-a-new-friend/page-04"
KEY_05 = "year4-sem1/section-1-a-new-friend/page-05"


def rf(tq: str = "", ta: str = "", uq: str = "", ua: str = "") -> RowFields:
    """Tiny ``RowFields`` builder for readable test rows."""
    return RowFields(tq=tq, ta=ta, uq=uq, ua=ua)


def pc(
    page_key: str,
    *,
    book: str = "year4-sem1",
    idx: int = 1,
    title: str = "A New Friend",
    part: int | None = None,
    num: int = 4,
) -> PageContext:
    """Build a real ``PageContext`` (key passed verbatim, as the navigator does)."""
    return PageContext(
        book_key=book,
        section_index=idx,
        section_title=title,
        part_number=part,
        page_number=num,
        page_key=page_key,
    )


def make_nav(
    pages: dict[str, list[PageContext]] | list[PageContext],
    reads: list[list[RowFields]],
) -> MagicMock:
    """Autospec'd ``SiteNavigator``: real read-only API, no browser."""
    nav = create_autospec(SiteNavigator, instance=True)
    nav.select_book.side_effect = lambda y, s: book_key(y, s)
    if isinstance(pages, dict):
        nav.iter_book_pages.side_effect = lambda bk: iter(pages.get(bk, []))
    else:
        nav.iter_book_pages.side_effect = lambda bk: iter(pages)
    nav.read_rows.side_effect = list(reads)
    return nav


# --- Pure core: build_row / merge_page (no mocks) --------------------------


def test_merge_page_none_builds_dense_zero_based_rows() -> None:
    page = merge_page(None, [rf("q0", "a0"), rf("q1", "a1")])
    assert len(page.rows) == 2
    assert (page.rows[0].tq, page.rows[0].ta) == ("q0", "a0")
    assert (page.rows[1].tq, page.rows[1].ta) == ("q1", "a1")
    # writeback_status is NEVER set by scrape (task-5 owns terminal status).
    assert page.writeback_status == "pending"
    assert page.writeback_error is None
    assert page.writeback_timestamp is None
    assert page.skip_reason is None


@pytest.mark.parametrize(
    ("tq", "ta", "uq", "ua", "expected"),
    [
        # expected = (uq_already, uq_needs, ua_already, ua_needs)
        ("q", "a", "", "", (False, True, False, True)),
        ("q", "a", "ت", "ت", (True, False, True, False)),
        ("", "", "", "", (False, False, False, False)),
        ("  ", "\t", "  ", "\n", (False, False, False, False)),  # whitespace == blank
        ("q", "a", "ت", "", (True, False, False, True)),  # UQ done, UA needs (independent)
        ("", "a", "", "", (False, False, False, True)),  # only UA side has English
        ("q", "", "", "ت", (False, True, True, False)),  # only UQ side has English
    ],
)
def test_build_row_independent_per_field_flag_matrix(
    tq: str, ta: str, uq: str, ua: str, expected: tuple[bool, bool, bool, bool]
) -> None:
    r = build_row(rf(tq, ta, uq, ua), prev=None)
    assert (
        r.uq_already_translated,
        r.uq_needs_translation,
        r.ua_already_translated,
        r.ua_needs_translation,
    ) == expected
    # already/needs are mutually exclusive per side (never both True).
    assert not (r.uq_already_translated and r.uq_needs_translation)
    assert not (r.ua_already_translated and r.ua_needs_translation)


def test_build_row_carries_prev_translation_and_defaults_empty() -> None:
    prev = Row(uq_translation="سؤال", ua_translation="جواب")
    r = build_row(rf("q", "a"), prev=prev)
    assert r.uq_translation == "سؤال"
    assert r.ua_translation == "جواب"

    r2 = build_row(rf("q", "a"), prev=None)
    assert r2.uq_translation == ""
    assert r2.ua_translation == ""


def test_merge_page_skip_when_no_english_blank_rows_and_empty_grid() -> None:
    page = merge_page(None, [rf("", "", "x", " "), rf("  ", "\t", "", "")])
    assert page.skip_reason == SKIP_NO_ENGLISH
    assert len(page.rows) == 2  # still persisted, just flagged

    empty = merge_page(None, [])
    assert empty.rows == []
    assert empty.skip_reason == SKIP_NO_ENGLISH


def test_merge_refresh_preserves_translations_and_writeback_state() -> None:
    prev = Page(
        rows=[
            Row(
                tq="old",
                ta="old",
                uq="",
                ua="",
                uq_translation="TR_Q",
                ua_translation="TR_A",
                uq_needs_translation=True,
                ua_needs_translation=True,
            )
        ],
        writeback_status="success",
        writeback_error="boom",
        writeback_timestamp="2026-01-01T00:00:00Z",
        skip_reason="stale_value",
    )

    new = merge_page(prev, [rf("newq", "newa", "SITE_UQ", "")])
    row = new.rows[0]

    # source + site state + flags REFRESHED from live.
    assert (row.tq, row.ta, row.uq, row.ua) == ("newq", "newa", "SITE_UQ", "")
    assert row.uq_already_translated is True
    assert row.uq_needs_translation is False
    assert row.ua_needs_translation is True  # ta set, ua blank
    # step-2 translations PRESERVED.
    assert row.uq_translation == "TR_Q"
    assert row.ua_translation == "TR_A"
    # write-back bookkeeping PRESERVED.
    assert new.writeback_status == "success"
    assert new.writeback_error == "boom"
    assert new.writeback_timestamp == "2026-01-01T00:00:00Z"
    # skip_reason RECOMPUTED live (English now present -> cleared).
    assert new.skip_reason is None


def test_merge_refresh_recomputes_skip_when_english_disappears() -> None:
    prev = Page(rows=[Row(tq="had-english", ta="")], skip_reason=None)
    new = merge_page(prev, [rf("", "", "", "")])
    assert new.skip_reason == SKIP_NO_ENGLISH


def test_merge_refresh_row_count_changes_no_dup_no_loss() -> None:
    prev = Page(rows=[Row(uq_translation="t0"), Row(uq_translation="t1")])

    # CSTC-3 added a row: more live rows -> new row has empty translation,
    # prior rows keep theirs BY INDEX, and there are no duplicate rows.
    grown = merge_page(prev, [rf("q", "a"), rf("q", "a"), rf("q", "a")])
    assert len(grown.rows) == 3
    assert grown.rows[0].uq_translation == "t0"
    assert grown.rows[1].uq_translation == "t1"
    assert grown.rows[2].uq_translation == ""

    # Defensive: fewer live rows -> dropped trailing index simply not carried.
    shrunk = merge_page(prev, [rf("q", "a")])
    assert len(shrunk.rows) == 1
    assert shrunk.rows[0].uq_translation == "t0"


# --- Orchestration: scrape_book (autospec'd nav, no browser) ----------------


def test_scrape_book_keys_store_by_page_key_and_saves_per_page(
    monkeypatch: pytest.MonkeyPatch, store_path: Path
) -> None:
    saves = MagicMock()
    monkeypatch.setattr(scrape, "save_store", saves)
    nav = make_nav([pc(KEY_04, num=4), pc(KEY_05, num=5)], [[rf("q", "a")], []])
    store = TranslationStore({})

    scrape.scrape_book(nav, 4, 1, store, store_path)

    # Store is keyed by the verbatim PageContext.page_key (no transform), and
    # every emitted key is format-valid.
    assert set(store.keys()) == {KEY_04, KEY_05}
    assert all(is_valid_page_key(k) for k in store.keys())
    assert saves.call_count == 2  # interrupt-safe: persisted after every page
    # Empty-grid page is still recorded with the no-English skip reason.
    assert store[KEY_05].rows == []
    assert store[KEY_05].skip_reason == SKIP_NO_ENGLISH
    nav.select_book.assert_called_once_with(4, 1)


def test_scrape_book_invokes_only_readonly_nav_api(
    monkeypatch: pytest.MonkeyPatch, store_path: Path
) -> None:
    monkeypatch.setattr(scrape, "save_store", MagicMock())
    nav = make_nav([pc(KEY_04)], [[rf("q", "a")]])

    scrape.scrape_book(nav, 4, 1, TranslationStore({}), store_path)

    # SiteNavigator structurally has NO write surface (autospec proves it).
    for forbidden in ("fill_translation", "save_page", "read_field_value"):
        assert not hasattr(nav, forbidden)
    nav.open_textapps.assert_called()
    nav.read_rows.assert_called()
    nav.close_textapps.assert_called()


def test_scrape_book_panel_error_leaves_page_unrecorded_and_continues(
    monkeypatch: pytest.MonkeyPatch, store_path: Path
) -> None:
    monkeypatch.setattr(scrape, "save_store", MagicMock())
    nav = make_nav([pc(KEY_04, num=4), pc(KEY_05, num=5)], [[rf("q", "a")]])
    # First page: grid never appears. Second page: fine.
    nav.open_textapps.side_effect = [PanelError("no grid"), None]
    # _safe_close must swallow a close failure on the panel-never-opened page.
    nav.close_textapps.side_effect = [NavigationError("no close"), None]
    store = TranslationStore({})

    scrape.scrape_book(nav, 4, 1, store, store_path)

    assert KEY_04 not in store  # error -> NOT recorded (re-run retries it)
    assert KEY_05 in store  # loop continued
    assert nav.close_textapps.call_count == 2  # close attempted on both pages


def test_scrape_book_does_not_prune_unvisited_store_keys(
    monkeypatch: pytest.MonkeyPatch, store_path: Path
) -> None:
    monkeypatch.setattr(scrape, "save_store", MagicMock())
    other = "year6-sem2/section-9-old/page-99"
    store = TranslationStore({other: Page(rows=[Row(uq_translation="X")])})
    nav = make_nav([pc(KEY_04)], [[rf("q", "a")]])

    scrape.scrape_book(nav, 4, 1, store, store_path)

    assert other in store  # refresh/add-only: never prunes
    assert store[other].rows[0].uq_translation == "X"
    assert KEY_04 in store


# --- READ-ONLY guarantee (AST/import test, mirrors test_site.py) -----------


def test_scrape_module_does_not_import_write_helper() -> None:
    assert not hasattr(scrape, "write_helper")

    tree = ast.parse(Path(scrape.__file__).read_text(encoding="utf-8"))
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


# --- Orchestration: run() (browser_session patched) ------------------------


def test_run_walks_six_books_in_order_one_session_each(
    monkeypatch: pytest.MonkeyPatch, creds_env: dict[str, str], store_path: Path
) -> None:
    monkeypatch.setenv("IBNBADIS_STORE_PATH", str(store_path))
    nav = make_nav({}, [])  # every book -> no pages (fast)
    headless_seen: list[bool] = []

    @contextmanager
    def fake_session(*, headless: bool = True, settings: object = None) -> Iterator[MagicMock]:
        headless_seen.append(headless)
        yield nav

    monkeypatch.setattr(scrape, "browser_session", fake_session)

    scrape.run()

    assert nav.select_book.call_args_list == [
        call(4, 1),
        call(4, 2),
        call(5, 1),
        call(5, 2),
        call(6, 1),
        call(6, 2),
    ]
    assert nav.login.call_count == 6  # one session (one login) per book
    assert headless_seen == [True] * 6


def test_run_only_book_filters_to_a_single_book(
    monkeypatch: pytest.MonkeyPatch, creds_env: dict[str, str], store_path: Path
) -> None:
    monkeypatch.setenv("IBNBADIS_STORE_PATH", str(store_path))
    nav = make_nav({}, [])

    @contextmanager
    def fake_session(*, headless: bool = True, settings: object = None) -> Iterator[MagicMock]:
        yield nav

    monkeypatch.setattr(scrape, "browser_session", fake_session)

    scrape.run(only_book="year5-sem1")

    assert nav.select_book.call_args_list == [call(5, 1)]
    assert nav.login.call_count == 1


def test_run_resumes_from_on_disk_store_and_merge_refreshes(
    monkeypatch: pytest.MonkeyPatch, creds_env: dict[str, str], store_path: Path
) -> None:
    monkeypatch.setenv("IBNBADIS_STORE_PATH", str(store_path))
    # Simulate a prior (killed) run: store already on disk with step-2 Arabic
    # and a successful write-back recorded.
    seed = TranslationStore(
        {
            KEY_04: Page(
                rows=[Row(tq="old", ta="old", uq_translation="KEEPQ", ua_translation="KEEPA")],
                writeback_status="success",
                writeback_timestamp="2026-01-01T00:00:00Z",
            )
        }
    )
    save_store(seed, store_path)

    nav = make_nav({"year4-sem1": [pc(KEY_04)]}, [[rf("newq", "newa", "", "")]])

    @contextmanager
    def fake_session(*, headless: bool = True, settings: object = None) -> Iterator[MagicMock]:
        yield nav

    monkeypatch.setattr(scrape, "browser_session", fake_session)

    scrape.run()

    result = load_store(store_path)
    row = result[KEY_04].rows[0]
    assert (row.tq, row.ta) == ("newq", "newa")  # source refreshed from live
    assert row.uq_translation == "KEEPQ"  # step-2 output survived re-scrape
    assert row.ua_translation == "KEEPA"
    assert result[KEY_04].writeback_status == "success"  # step-3 progress survived
    assert result[KEY_04].writeback_timestamp == "2026-01-01T00:00:00Z"
