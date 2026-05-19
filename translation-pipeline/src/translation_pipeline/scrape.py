"""Pipeline **step 1**: deterministic, READ-ONLY, resumable Playwright scrape.

Walks all 6 books (Year 4/5/6 English x semester 1/2), every section and page,
opens the TextApps panel and reads each existing row's English source
(``TQ``/``TA``) and current site translation state (``UQ``/``UA``), then
persists it to ``store/translations.json`` under the flat CSTC-3-style page key.
It computes the independent per-field flags, records a ``skip_reason`` for pages
with no English Q&A, and **never writes to the site**.

Interface segregation (hard requirement): this module imports **only**
:mod:`translation_pipeline.site` (READ-ONLY) and never
:mod:`translation_pipeline.write_helper`, so the scrape path provably cannot
mutate the site.

Re-runs perform a **merge-refresh**: live source/site state and the per-field
flags are refreshed, while ``uq_translation``/``ua_translation`` (step 2 output)
and the page-level write-back bookkeeping (step 3 progress) are preserved — so
re-running step 1 after step 2/3 never destroys translations or write-back
progress. ``store.save_store`` runs after every page (atomic), making the scrape
killable and restartable.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from translation_pipeline.config import get_settings
from translation_pipeline.core import build_row, is_blank
from translation_pipeline.logging_config import get_logger
from translation_pipeline.models import Page, Row
from translation_pipeline.page_keys import BOOK_KEYS, book_key
from translation_pipeline.site import (
    PanelError,
    RowFields,
    SiteNavigator,
    browser_session,
)
from translation_pipeline.store import TranslationStore, load_store, save_store

_log = get_logger(__name__)

#: ``skip_reason`` recorded for a page with no English Q&A at scrape time.
SKIP_NO_ENGLISH = "no_english_qa"

#: Fixed deterministic walk order (``BOOK_KEYS`` is an unordered frozenset).
BOOKS: list[tuple[int, int]] = [(4, 1), (4, 2), (5, 1), (5, 2), (6, 1), (6, 2)]


# --- Pure core (no Playwright / store I/O — trivially unit-testable) --------
#
# The canonical "blank" rule and per-field flag formulas live in
# :mod:`translation_pipeline.core` (imported above and re-exported here for
# backward compatibility) so the validator and write-back can depend on an
# explicit shared contract rather than a private detail of this step.


def _page_has_english(rows: list[Row]) -> bool:
    """``True`` if any row has a non-blank English source (``tq`` or ``ta``)."""
    return any(not is_blank(r.tq) or not is_blank(r.ta) for r in rows)


def merge_page(prev: Page | None, sources: list[RowFields]) -> Page:
    """Merge-refresh: rebuild rows from live, preserve step-2/step-3 state.

    Rows are rebuilt fresh from ``sources`` every run (never appended → no
    duplicate rows); step-2 translations are carried forward **by row index**
    only where a live row still exists at that index (handles CSTC-3 having
    added rows since the last scrape, and the defensive fewer-rows case).

    Page-level write-back bookkeeping (``writeback_status``/``writeback_error``/
    ``writeback_timestamp``) is preserved from ``prev`` so re-running step 1
    after step 2/3 never destroys write-back progress. ``skip_reason`` is
    site-state-derived and therefore **recomputed live** each run.
    ``writeback_status`` is **never set by scrape** (stays ``pending`` for new
    pages; assigning a terminal status is task 5's job).

    Args:
        prev: the previously stored page, or ``None`` for a first scrape.
        sources: live rows in 0-based order (empty grid → empty list).
    """
    rows = [
        build_row(
            s,
            prev=(prev.rows[i] if prev is not None and i < len(prev.rows) else None),
        )
        for i, s in enumerate(sources)
    ]
    skip_reason = None if _page_has_english(rows) else SKIP_NO_ENGLISH
    if prev is not None:
        return Page(
            rows=rows,
            writeback_status=prev.writeback_status,
            writeback_error=prev.writeback_error,
            writeback_timestamp=prev.writeback_timestamp,
            skip_reason=skip_reason,
        )
    return Page(rows=rows, skip_reason=skip_reason)


# --- Orchestration shell (side effects: browser + store I/O) ---------------


def _safe_close(nav: SiteNavigator) -> None:
    """Close the TextApps panel, swallowing+logging any failure.

    Reached from the per-page ``finally`` even when ``open_textapps`` failed,
    so it must tolerate the panel never having opened or being in any partial
    state — a transient close failure must never abort the book.
    """
    try:
        nav.close_textapps()
    except Exception as exc:  # broad on purpose: close must never abort a book
        _log.warning("textapps_close_failed", error=str(exc))


def scrape_book(
    nav: SiteNavigator,
    year: int,
    sem: int,
    store: TranslationStore,
    store_path: Path,
) -> None:
    """Scrape every page of one book into ``store`` (persist after each page).

    A ``PanelError`` (grid never appeared) leaves the page **unrecorded** so a
    re-run retries it — distinct from a recorded no-English skip.
    """
    bk = nav.select_book(year, sem)
    _log.info("book_start", book_key=bk)
    for ctx in nav.iter_book_pages(bk):
        try:
            nav.open_textapps()
            rows_src = nav.read_rows()
        except PanelError:
            _log.warning("page_panel_error", page_key=ctx.page_key)
            continue
        finally:
            _safe_close(nav)

        page = merge_page(store.get(ctx.page_key), rows_src)
        store[ctx.page_key] = page
        save_store(store, store_path)
        _log.info(
            "page_scraped",
            page_key=ctx.page_key,
            rows=len(page.rows),
            uq_needs=sum(r.uq_needs_translation for r in page.rows),
            ua_needs=sum(r.ua_needs_translation for r in page.rows),
            uq_already=sum(r.uq_already_translated for r in page.rows),
            ua_already=sum(r.ua_already_translated for r in page.rows),
            skipped=bool(page.skip_reason),
        )


def run(*, headless: bool = True, only_book: str | None = None) -> None:
    """Scrape all 6 books (or just ``only_book``) into the configured store.

    One ``browser_session`` per book (``select_book`` needs the books-listing
    semester dropdown that does not exist inside the viewer, and the READ-ONLY
    site module exposes no return-to-listing primitive). The store is loaded
    once and mutated in place; the on-disk file (saved after every page) is the
    resume source after a kill. Scrape is refresh/add-only — store keys not
    revisited are never pruned.
    """
    settings = get_settings()
    store = load_store(settings.store_path)
    for year, sem in BOOKS:
        bk = book_key(year, sem)
        if only_book is not None and bk != only_book:
            continue
        _log.info("book_session_start", book_key=bk, headless=headless)
        with browser_session(headless=headless) as nav:
            nav.login()
            scrape_book(nav, year, sem, store, settings.store_path)
        _log.info("book_session_done", book_key=bk)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for ``make scrape`` / ``python -m ...scrape``."""
    parser = argparse.ArgumentParser(
        prog="scrape",
        description="CSTC-4 pipeline step 1: deterministic READ-ONLY scrape.",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="run with a visible browser (helps the live selector-tuning run).",
    )
    parser.add_argument(
        "--book",
        choices=sorted(BOOK_KEYS),
        default=None,
        help="scrape only this single book key (default: all 6, in order).",
    )
    args = parser.parse_args(argv)
    run(headless=not args.headed, only_book=args.book)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
