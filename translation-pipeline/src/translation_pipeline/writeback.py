"""Pipeline **step 3**: deterministic, resumable, idempotent Playwright write-back.

Walks the **validated** store (step 2 has filled the Arabic) and, per page,
fills each pending Arabic translation into the matching ``UQ{N}``/``UA{N}`` site
field **by row index**, Saves once, and records a terminal per-page
``writeback_status`` keyed strictly off the ``userqanssave.php`` response body
(never the fleeting green Save flash — delegated to
:func:`translation_pipeline.write_helper.save_page`).

Behavioural contract (PRD task 5 / requirements 3,4,5,6,7,10):

- **Resume-skip**: a page whose ``writeback_status == "success"`` is skipped
  without re-reading the site (no panel open, no read, no write, no Save).
- **Per-field independent selection**: a ``UQ`` (resp. ``UA``) is written iff
  ``uq_needs_translation`` (resp. ``ua_needs_translation``) is true *and*
  ``uq_translation`` (resp. ``ua_translation``) is non-blank.
- **Defensive no-overwrite guard**: immediately before filling a candidate
  field, its live ``.value`` is read; if non-blank it is *never* overwritten —
  the field is skipped, a warning logged, and the store row reconciled in place.
- **Write surface**: ``UQ{N}``/``UA{N}`` filled strictly by row index via
  :mod:`translation_pipeline.write_helper` — never ``+``, never ``TQ``/``TA``,
  never add/remove rows. Navigation goes through the READ-ONLY ``site`` module.
- **Save contract**: ``["", true]`` -> ``success``; ``["", false]`` -> failed
  (not retried); ``5xx``/timeout/unparseable -> server error, the filled form
  retried **exactly once**. An empty form is **never** submitted.
- **Resumable & idempotent**: the store is loaded once, persisted (atomically)
  after every page; only ``pending``/``failed`` pages are touched on a re-run.

This module is **explicitly allowed** to import both the READ-ONLY ``site``
module (navigation) and ``write_helper`` (side effects) — the interface
segregation guarantee only constrains the *scrape* path.
"""

from __future__ import annotations

import argparse
import datetime as _dt
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from playwright.sync_api import Page as PwPage

from translation_pipeline.config import get_settings
from translation_pipeline.logging_config import get_logger
from translation_pipeline.models import Page, Row
from translation_pipeline.page_keys import BOOK_KEYS, book_key
from translation_pipeline.scrape import BOOKS, _is_blank, build_row
from translation_pipeline.selectors import Field, TargetField
from translation_pipeline.site import (
    PanelError,
    RowFields,
    SiteNavigator,
    browser_session,
)
from translation_pipeline.store import TranslationStore, load_store, save_store
from translation_pipeline.write_helper import (
    SaveOutcome,
    SaveResult,
    fill_translation,
    read_field_value,
    save_page,
)

_log = get_logger(__name__)


# --- Pure core (no Playwright / store I/O — trivially unit-testable) --------


@dataclass(frozen=True)
class WriteItem:
    """One field to fill: ``UQ``/``UA`` at a 0-based row index plus its value."""

    row_index: int
    field: TargetField  # UQ or UA only
    value: str  # the step-2 Arabic to write


def plan_page_writes(page: Page) -> list[WriteItem]:
    """Per-field, per-row write plan derived purely from the store.

    A field is included iff its ``*_needs_translation`` flag is true **and**
    its ``*_translation`` is non-blank (whitespace-aware, via the canonical
    :func:`translation_pipeline.scrape._is_blank`). A blank ``*_translation``
    is excluded even when the needs flag is set — defensive: the validator
    should have caught it, and write-back must never fill a blank value nor
    submit an empty form. The order is deterministic: rows ascending, ``UQ``
    before ``UA``.
    """
    items: list[WriteItem] = []
    for idx, row in enumerate(page.rows):
        if row.uq_needs_translation and not _is_blank(row.uq_translation):
            items.append(WriteItem(idx, TargetField.UQ, row.uq_translation))
        if row.ua_needs_translation and not _is_blank(row.ua_translation):
            items.append(WriteItem(idx, TargetField.UA, row.ua_translation))
    return items


def _as_field(tf: TargetField) -> Field:
    """``TargetField`` -> ``Field`` for the read-only live guard (same value)."""
    return Field(tf.value)


def reconcile_guarded_row(row: Row, field: TargetField, live_value: str) -> Row:
    """Reconcile a defensively-skipped row in place (pure).

    The *guarded* side's site value (``uq``/``ua``) is set to the live value,
    then **all four** per-field flags are recomputed via the canonical
    :func:`translation_pipeline.scrape.build_row` with ``prev=row`` so the
    step-2 ``uq_translation``/``ua_translation`` are carried forward and never
    destroyed. Reusing ``build_row`` keeps zero flag-formula duplication and
    keeps the validator's source-flag-integrity invariant satisfied. The
    unguarded side's ``tq``/``ta``/``uq``/``ua`` are unchanged, so its
    recomputed flags are identical to what scrape stored (a no-op in effect).
    """
    new_uq = live_value if field is TargetField.UQ else row.uq
    new_ua = live_value if field is TargetField.UA else row.ua
    return build_row(RowFields(tq=row.tq, ta=row.ta, uq=new_uq, ua=new_ua), prev=row)


# --- Orchestration shell (side effects: browser + store I/O) ---------------


def _utc_now_iso() -> str:
    """ISO-8601 UTC, ``Z``-suffixed (matches the schema/test convention)."""
    return _dt.datetime.now(tz=_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_close(nav: SiteNavigator) -> None:
    """Close the TextApps panel, swallowing+logging any failure.

    Reached from the per-page ``finally`` only after we attempted to open the
    panel, so it must tolerate the panel being in any partial state — a
    transient close failure must never abort the book walk.
    """
    try:
        nav.close_textapps()
    except Exception as exc:  # broad on purpose: close must never abort a book
        _log.warning("textapps_close_failed", error=str(exc))


def _mark(page: Page, status: Literal["success", "failed"], *, error: str | None) -> None:
    """Set the page's terminal write-back bookkeeping atomically.

    ``success`` clears any prior error; ``failed`` records ``error``. Both
    stamp ``writeback_timestamp`` with the attempt time.
    """
    page.writeback_status = status
    page.writeback_error = error
    page.writeback_timestamp = _utc_now_iso()


def _save_with_single_retry(pg: PwPage) -> SaveResult:
    """Save once; retry **exactly once** only on a server error.

    The caller only invokes this when ≥1 field was filled, so a retried Save is
    always a *filled* form (PRD: filled-form 5xx is retried exactly once).
    ``REJECTED`` (``["", false]``) is a definitive rejection and is **not**
    retried (re-runnable via a later full ``make writeback``).
    """
    result = save_page(pg)
    if result.outcome is SaveOutcome.SERVER_ERROR:
        _log.warning("save_server_error_retrying", http_status=result.http_status)
        result = save_page(pg)
    return result


def writeback_page(nav: SiteNavigator, page_model: Page, page_key: str) -> None:
    """Apply step 3 to ONE in-store page (mutates ``page_model`` in place).

    A page with nothing to fill (empty plan, or every planned field
    defensively skipped) is **not** Saved but is assigned the terminal
    ``writeback_status="success"`` so re-runs never re-open it.
    """
    plan = plan_page_writes(page_model)
    if not plan:  # nothing in the store to do — terminal, no site interaction
        _mark(page_model, "success", error=None)
        return
    try:
        nav.open_textapps()
        filled_any = False
        for item in plan:
            live = read_field_value(nav.page, item.row_index, _as_field(item.field))
            if not _is_blank(live):  # DEFENSIVE: never overwrite a non-blank target
                _log.warning(
                    "defensive_skip_nonblank_target",
                    page_key=page_key,
                    row=item.row_index,
                    field=item.field.value,
                )
                page_model.rows[item.row_index] = reconcile_guarded_row(
                    page_model.rows[item.row_index], item.field, live
                )
                continue
            fill_translation(nav.page, item.row_index, item.field, item.value)
            filled_any = True
        if not filled_any:  # all defensively skipped — terminal success, NO Save
            _mark(page_model, "success", error=None)
            return
        result = _save_with_single_retry(nav.page)
        if result.outcome is SaveOutcome.PERSISTED:
            _mark(page_model, "success", error=None)
        elif result.outcome is SaveOutcome.REJECTED:
            _mark(page_model, "failed", error='save rejected (["", false])')
        else:  # SERVER_ERROR after the single retry
            _mark(page_model, "failed", error=f"server error (http={result.http_status})")
    except PanelError:
        _log.warning("page_panel_error", page_key=page_key)
        _mark(page_model, "failed", error="panel did not open")
    finally:
        _safe_close(nav)


def writeback_book(
    nav: SiteNavigator,
    year: int,
    sem: int,
    store: TranslationStore,
    store_path: Path,
) -> None:
    """Write back every page of one book, persisting after each page.

    Pages absent from the store (not scraped / no entry) and pages already at
    ``writeback_status == "success"`` are skipped without touching the site.
    """
    bk = nav.select_book(year, sem)
    _log.info("book_start", book_key=bk)
    for ctx in nav.iter_book_pages(bk):
        page_model = store.get(ctx.page_key)
        if page_model is None:  # not scraped / no entry — never created here
            _log.debug("page_absent_from_store", page_key=ctx.page_key)
            continue
        if page_model.writeback_status == "success":  # RESUME-SKIP (no site read)
            _log.info("page_skip_already_success", page_key=ctx.page_key)
            continue
        writeback_page(nav, page_model, ctx.page_key)
        store[ctx.page_key] = page_model  # explicit (already the same object)
        save_store(store, store_path)  # interrupt-safe: persist after every page
        _log.info(
            "page_writeback_done",
            page_key=ctx.page_key,
            status=page_model.writeback_status,
        )


def run(*, headless: bool = True, only_book: str | None = None) -> None:
    """Write back all 6 books (or just ``only_book``) from the configured store.

    One ``browser_session`` per book (``select_book`` needs the books-listing
    semester dropdown that does not exist inside the viewer, and the READ-ONLY
    site module exposes no return-to-listing primitive — same constraint as
    scrape). The store is loaded once and mutated in place; the on-disk file
    (saved after every page) is the resume source after a kill. Write-back is
    act-only — store keys are never added or pruned here.
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
            writeback_book(nav, year, sem, store, settings.store_path)
        _log.info("book_session_done", book_key=bk)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for ``make writeback`` / ``python -m ...writeback``."""
    parser = argparse.ArgumentParser(
        prog="writeback",
        description="CSTC-4 pipeline step 3: deterministic resumable write-back.",
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
        help="write back only this single book key (default: all 6, in order).",
    )
    args = parser.parse_args(argv)
    run(headless=not args.headed, only_book=args.book)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
