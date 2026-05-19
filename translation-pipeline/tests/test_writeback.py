"""writeback (step 3): pure-core write planning + orchestration.

The site/write-helper modules are fully mocked (autospec'd ``SiteNavigator``,
monkeypatched ``fill_translation``/``read_field_value``/``save_page``/
``save_store``/``browser_session``) — **no browser, no network, no creds**.
Pure-core tests run with zero mocking.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call, create_autospec

import pytest

from tests.conftest import ARABIC_A, ARABIC_Q
from translation_pipeline import writeback
from translation_pipeline.core import build_row
from translation_pipeline.models import Page, Row
from translation_pipeline.page_keys import book_key, is_valid_page_key
from translation_pipeline.selectors import Field, TargetField
from translation_pipeline.site import (
    NavigationError,
    PageContext,
    PanelError,
    RowFields,
    SiteNavigator,
)
from translation_pipeline.store import TranslationStore, load_store, save_store
from translation_pipeline.write_helper import SaveOutcome, SaveResult
from translation_pipeline.writeback import (
    WriteItem,
    _as_field,
    plan_page_writes,
    reconcile_guarded_row,
)

KEY_04 = "year4-sem1/section-1-a-new-friend/page-04"
KEY_05 = "year4-sem1/section-1-a-new-friend/page-05"
FIXED_TS = "2026-01-01T00:00:00Z"


# --- builders --------------------------------------------------------------


def row(
    *,
    tq: str = "",
    ta: str = "",
    uq: str = "",
    ua: str = "",
    uq_tr: str = "",
    ua_tr: str = "",
    uq_already: bool = False,
    uq_needs: bool = False,
    ua_already: bool = False,
    ua_needs: bool = False,
) -> Row:
    return Row(
        tq=tq,
        ta=ta,
        uq=uq,
        ua=ua,
        uq_translation=uq_tr,
        ua_translation=ua_tr,
        uq_already_translated=uq_already,
        uq_needs_translation=uq_needs,
        ua_already_translated=ua_already,
        ua_needs_translation=ua_needs,
    )


def page(*rows: Row, status: str = "pending") -> Page:
    return Page(rows=list(rows), writeback_status=status)  # type: ignore[arg-type]


def pc(page_key: str, *, num: int = 4) -> PageContext:
    """Build a real ``PageContext`` (key passed verbatim, as the navigator does)."""
    return PageContext(
        book_key="year4-sem1",
        section_index=1,
        section_title="A New Friend",
        part_number=None,
        page_number=num,
        page_key=page_key,
    )


def make_page_nav() -> MagicMock:
    """Autospec'd ``SiteNavigator`` for a single ``writeback_page`` call."""
    return create_autospec(SiteNavigator, instance=True)


def make_book_nav(
    pages: dict[str, list[PageContext]] | list[PageContext],
) -> MagicMock:
    nav = create_autospec(SiteNavigator, instance=True)
    nav.select_book.side_effect = lambda y, s: book_key(y, s)
    if isinstance(pages, dict):
        nav.iter_book_pages.side_effect = lambda bk: iter(pages.get(bk, []))
    else:
        nav.iter_book_pages.side_effect = lambda bk: iter(pages)
    return nav


def sr(outcome: SaveOutcome, *, status: int | None = 200) -> SaveResult:
    return SaveResult(outcome, status, None)


@pytest.fixture
def patched_io(monkeypatch: pytest.MonkeyPatch) -> dict[str, MagicMock]:
    """Monkeypatch all side-effecting write-back collaborators."""
    fill = MagicMock(name="fill_translation")
    read = MagicMock(name="read_field_value", return_value="")  # blank => fill
    save = MagicMock(name="save_page", return_value=sr(SaveOutcome.PERSISTED))
    store_save = MagicMock(name="save_store")
    monkeypatch.setattr(writeback, "fill_translation", fill)
    monkeypatch.setattr(writeback, "read_field_value", read)
    monkeypatch.setattr(writeback, "save_page", save)
    monkeypatch.setattr(writeback, "save_store", store_save)
    monkeypatch.setattr(writeback, "_utc_now_iso", lambda: FIXED_TS)
    return {"fill": fill, "read": read, "save": save, "save_store": store_save}


class RecordingLogger:
    """Captures structured log calls for credential/secret leak assertions."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def _rec(self, lvl: str, event: str, **kw: Any) -> None:
        self.calls.append((lvl, event, kw))

    def info(self, event: str, **kw: Any) -> None:
        self._rec("info", event, **kw)

    def warning(self, event: str, **kw: Any) -> None:
        self._rec("warning", event, **kw)

    def error(self, event: str, **kw: Any) -> None:
        self._rec("error", event, **kw)

    def debug(self, event: str, **kw: Any) -> None:
        self._rec("debug", event, **kw)


# --- Pure core: plan_page_writes -------------------------------------------


def test_plan_page_writes_uq_only() -> None:
    p = page(row(tq="q", uq_needs=True, uq_tr="AR_Q"))
    assert plan_page_writes(p) == [WriteItem(0, TargetField.UQ, "AR_Q")]


def test_plan_page_writes_ua_only() -> None:
    p = page(row(ta="a", ua_needs=True, ua_tr="AR_A"))
    assert plan_page_writes(p) == [WriteItem(0, TargetField.UA, "AR_A")]


def test_plan_page_writes_both_deterministic_order_uq_before_ua() -> None:
    p = page(
        row(tq="q1", ta="a1", uq_needs=True, ua_needs=True, uq_tr="Q1", ua_tr="A1"),
        row(tq="q2", uq_needs=True, uq_tr="Q2"),
    )
    assert plan_page_writes(p) == [
        WriteItem(0, TargetField.UQ, "Q1"),
        WriteItem(0, TargetField.UA, "A1"),
        WriteItem(1, TargetField.UQ, "Q2"),
    ]


def test_plan_page_writes_neither_when_no_needs_flag() -> None:
    assert plan_page_writes(page(row(tq="q", uq_already=True, uq="x"))) == []


def test_plan_page_writes_excludes_needs_but_blank_translation() -> None:
    # Defensive: needs flag true but the (whitespace-only / empty) translation
    # is excluded — write-back must never fill blank nor submit an empty form.
    p = page(
        row(tq="q", uq_needs=True, uq_tr=""),
        row(ta="a", ua_needs=True, ua_tr="   \t"),
    )
    assert plan_page_writes(p) == []


def test_plan_page_writes_already_translated_row_not_planned() -> None:
    p = page(row(tq="q", uq="ت", uq_already=True, uq_tr="SHOULD_NOT_WRITE"))
    assert plan_page_writes(p) == []


# --- Pure core: _as_field / reconcile_guarded_row --------------------------


def test_as_field_maps_targetfield_to_field() -> None:
    assert _as_field(TargetField.UQ) is Field.UQ
    assert _as_field(TargetField.UA) is Field.UA


def test_reconcile_guarded_row_uq_sets_live_flips_flags_preserves_rest() -> None:
    r = row(
        tq="q",
        ta="a",
        uq="",
        ua="",
        uq_tr="KEEP_Q",
        ua_tr="KEEP_A",
        uq_needs=True,
        ua_needs=True,
    )
    out = reconcile_guarded_row(r, TargetField.UQ, "LIVE_Q")

    assert out.uq == "LIVE_Q"
    assert out.uq_already_translated is True
    assert out.uq_needs_translation is False
    # step-2 work preserved on BOTH sides; UA side untouched.
    assert out.uq_translation == "KEEP_Q"
    assert out.ua_translation == "KEEP_A"
    assert out.ua == ""
    assert out.ua_needs_translation is True
    # parity: identical to the canonical core.build_row.
    assert out == build_row(RowFields(tq="q", ta="a", uq="LIVE_Q", ua=""), prev=r)


def test_reconcile_guarded_row_ua_symmetric() -> None:
    r = row(tq="q", ta="a", uq_tr="KQ", ua_tr="KA", uq_needs=True, ua_needs=True)
    out = reconcile_guarded_row(r, TargetField.UA, "LIVE_A")
    assert out.ua == "LIVE_A"
    assert out.ua_already_translated is True
    assert out.ua_needs_translation is False
    assert out.ua_translation == "KA"
    assert out.uq == "" and out.uq_needs_translation is True


# --- writeback_page: per-field fill + status transitions -------------------


def test_writeback_page_per_field_independent_fill_uq_only(
    patched_io: dict[str, MagicMock],
) -> None:
    nav = make_page_nav()
    pm = page(row(tq="q", ta="a", ua="ت", ua_already=True, uq_needs=True, uq_tr=ARABIC_Q))

    writeback.writeback_page(nav, pm, KEY_04)

    patched_io["fill"].assert_called_once_with(nav.page, 0, TargetField.UQ, ARABIC_Q)
    patched_io["save"].assert_called_once()
    assert pm.writeback_status == "success"
    assert pm.writeback_error is None
    assert pm.writeback_timestamp == FIXED_TS


def test_writeback_page_fill_by_index_and_only_targetfields(
    patched_io: dict[str, MagicMock],
) -> None:
    nav = make_page_nav()
    pm = page(
        row(tq="q0", ta="a0", uq_needs=True, ua_needs=True, uq_tr="Q0", ua_tr="A0"),
        row(tq="q1", uq_needs=True, uq_tr="Q1"),
    )

    writeback.writeback_page(nav, pm, KEY_04)

    assert patched_io["fill"].call_args_list == [
        call(nav.page, 0, TargetField.UQ, "Q0"),
        call(nav.page, 0, TargetField.UA, "A0"),
        call(nav.page, 1, TargetField.UQ, "Q1"),
    ]
    # never `+`, never TQ/TA: every fill targets a TargetField (UQ/UA only).
    for c in patched_io["fill"].call_args_list:
        assert isinstance(c.args[2], TargetField)


def test_writeback_page_successful_write_does_not_mutate_store_row(
    patched_io: dict[str, MagicMock],
) -> None:
    nav = make_page_nav()
    pm = page(row(tq="q", uq_needs=True, uq_tr="AR"))

    writeback.writeback_page(nav, pm, KEY_04)

    r = pm.rows[0]
    # only writeback_status flips; the scrape-time snapshot is untouched so the
    # validator's source-flag-integrity invariant stays satisfied.
    assert (r.uq, r.uq_needs_translation, r.uq_translation) == ("", True, "AR")
    assert pm.writeback_status == "success"


def test_writeback_page_defensive_guard_skips_nonblank_and_reconciles(
    patched_io: dict[str, MagicMock], monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = RecordingLogger()
    monkeypatch.setattr(writeback, "_log", rec)
    nav = make_page_nav()
    # plan order: row0 UQ, then row0 UA. UQ live is non-blank => skip+reconcile;
    # UA live is blank => filled normally; page then Saved.
    patched_io["read"].side_effect = ["PRE_EXISTING", ""]
    pm = page(
        row(
            tq="q",
            ta="a",
            uq="",
            ua="",
            uq_tr="AR_Q",
            ua_tr="AR_A",
            uq_needs=True,
            ua_needs=True,
        )
    )

    writeback.writeback_page(nav, pm, KEY_04)

    # UQ never overwritten; only UA filled.
    patched_io["fill"].assert_called_once_with(nav.page, 0, TargetField.UA, "AR_A")
    r = pm.rows[0]
    assert r.uq == "PRE_EXISTING"
    assert r.uq_already_translated is True
    assert r.uq_needs_translation is False
    assert r.uq_translation == "AR_Q"  # step-2 work preserved
    assert r.ua_translation == "AR_A"
    assert pm.writeback_status == "success"
    assert any(e == "defensive_skip_nonblank_target" for _, e, _ in rec.calls)


def test_writeback_page_all_defensively_skipped_terminal_success_no_save(
    patched_io: dict[str, MagicMock],
) -> None:
    nav = make_page_nav()
    patched_io["read"].return_value = "ALREADY_THERE"  # every target non-blank
    pm = page(row(tq="q", ta="a", uq_needs=True, ua_needs=True, uq_tr="Q", ua_tr="A"))

    writeback.writeback_page(nav, pm, KEY_04)

    nav.open_textapps.assert_called_once()
    patched_io["fill"].assert_not_called()
    patched_io["save"].assert_not_called()  # empty form NEVER submitted
    assert pm.writeback_status == "success"  # terminal nothing-to-do
    assert pm.rows[0].uq == "ALREADY_THERE" and pm.rows[0].ua == "ALREADY_THERE"


def test_writeback_page_empty_plan_terminal_success_without_opening_panel(
    patched_io: dict[str, MagicMock],
) -> None:
    nav = make_page_nav()
    pm = page(row(tq="q"))  # nothing needs translation

    writeback.writeback_page(nav, pm, KEY_04)

    nav.open_textapps.assert_not_called()
    patched_io["save"].assert_not_called()
    assert pm.writeback_status == "success"
    assert pm.writeback_timestamp == FIXED_TS


def test_writeback_page_persisted_sets_success(patched_io: dict[str, MagicMock]) -> None:
    nav = make_page_nav()
    patched_io["save"].return_value = sr(SaveOutcome.PERSISTED)
    pm = page(row(tq="q", uq_needs=True, uq_tr="AR"))
    writeback.writeback_page(nav, pm, KEY_04)
    assert (pm.writeback_status, pm.writeback_error) == ("success", None)


def test_writeback_page_rejected_fails_and_is_not_retried(
    patched_io: dict[str, MagicMock],
) -> None:
    nav = make_page_nav()
    patched_io["save"].return_value = sr(SaveOutcome.REJECTED)
    pm = page(row(tq="q", uq_needs=True, uq_tr="AR"))

    writeback.writeback_page(nav, pm, KEY_04)

    patched_io["save"].assert_called_once()  # definitive — NOT retried
    assert pm.writeback_status == "failed"
    assert "false" in (pm.writeback_error or "")
    assert pm.writeback_timestamp == FIXED_TS


def test_writeback_page_server_error_retried_exactly_once_then_failed(
    patched_io: dict[str, MagicMock],
) -> None:
    nav = make_page_nav()
    patched_io["save"].side_effect = [
        sr(SaveOutcome.SERVER_ERROR, status=502),
        sr(SaveOutcome.SERVER_ERROR, status=502),
    ]
    pm = page(row(tq="q", uq_needs=True, uq_tr="AR"))

    writeback.writeback_page(nav, pm, KEY_04)

    assert patched_io["save"].call_count == 2  # filled-form 5xx => exactly one retry
    assert pm.writeback_status == "failed"
    assert "server error" in (pm.writeback_error or "")


def test_writeback_page_server_error_then_persisted_succeeds(
    patched_io: dict[str, MagicMock],
) -> None:
    nav = make_page_nav()
    patched_io["save"].side_effect = [
        sr(SaveOutcome.SERVER_ERROR, status=503),
        sr(SaveOutcome.PERSISTED),
    ]
    pm = page(row(tq="q", uq_needs=True, uq_tr="AR"))

    writeback.writeback_page(nav, pm, KEY_04)

    assert patched_io["save"].call_count == 2
    assert pm.writeback_status == "success"


def test_writeback_page_server_error_then_rejected_fails(
    patched_io: dict[str, MagicMock],
) -> None:
    nav = make_page_nav()
    patched_io["save"].side_effect = [
        sr(SaveOutcome.SERVER_ERROR, status=500),
        sr(SaveOutcome.REJECTED),
    ]
    pm = page(row(tq="q", uq_needs=True, uq_tr="AR"))

    writeback.writeback_page(nav, pm, KEY_04)

    assert patched_io["save"].call_count == 2
    assert pm.writeback_status == "failed"
    assert "false" in (pm.writeback_error or "")


def test_writeback_page_panel_error_records_failed_and_closes(
    patched_io: dict[str, MagicMock],
) -> None:
    nav = make_page_nav()
    nav.open_textapps.side_effect = PanelError("no grid")
    pm = page(row(tq="q", uq_needs=True, uq_tr="AR"))

    writeback.writeback_page(nav, pm, KEY_04)

    assert pm.writeback_status == "failed"
    assert pm.writeback_error == "panel did not open"
    patched_io["save"].assert_not_called()
    nav.close_textapps.assert_called_once()  # _safe_close still runs


def test_writeback_page_safe_close_tolerates_close_failure(
    patched_io: dict[str, MagicMock],
) -> None:
    nav = make_page_nav()
    nav.close_textapps.side_effect = NavigationError("cannot close")
    pm = page(row(tq="q", uq_needs=True, uq_tr="AR"))

    writeback.writeback_page(nav, pm, KEY_04)  # must not raise

    assert pm.writeback_status == "success"  # close failure does not flip status


# --- writeback_book / run --------------------------------------------------


def test_writeback_book_resume_skips_success_pages(
    patched_io: dict[str, MagicMock], store_path: Path
) -> None:
    nav = make_book_nav([pc(KEY_04)])
    store = TranslationStore(
        {KEY_04: page(row(tq="q", uq_needs=True, uq_tr="AR"), status="success")}
    )

    writeback.writeback_book(nav, 4, 1, store, store_path)

    nav.open_textapps.assert_not_called()
    patched_io["save"].assert_not_called()
    patched_io["save_store"].assert_not_called()  # nothing acted => no persist
    assert store[KEY_04].writeback_status == "success"


def test_writeback_book_retries_failed_page_on_rerun(
    patched_io: dict[str, MagicMock], store_path: Path
) -> None:
    # Resumability/idempotency: only "success" is terminal — a "failed" page is
    # NOT skipped; it is re-acted on the next run and can recover to "success".
    nav = make_book_nav([pc(KEY_04)])
    store = TranslationStore(
        {
            KEY_04: page(
                row(tq="q", uq_needs=True, uq_tr="AR"),
                status="failed",
            )
        }
    )
    store[KEY_04].writeback_error = "server error (http=502)"

    writeback.writeback_book(nav, 4, 1, store, store_path)

    nav.open_textapps.assert_called_once()  # re-acted, not resume-skipped
    patched_io["save"].assert_called_once()
    assert store[KEY_04].writeback_status == "success"
    assert store[KEY_04].writeback_error is None  # cleared on recovery
    patched_io["save_store"].assert_called_once()  # persisted after acting


def test_writeback_book_skips_pages_absent_from_store(
    patched_io: dict[str, MagicMock], store_path: Path
) -> None:
    nav = make_book_nav([pc(KEY_04)])
    store = TranslationStore({})

    writeback.writeback_book(nav, 4, 1, store, store_path)

    nav.open_textapps.assert_not_called()
    assert KEY_04 not in store  # never created here (act-only)
    patched_io["save_store"].assert_not_called()


def test_writeback_book_acts_and_persists_per_page(
    patched_io: dict[str, MagicMock], store_path: Path
) -> None:
    nav = make_book_nav([pc(KEY_04, num=4), pc(KEY_05, num=5)])
    store = TranslationStore(
        {
            KEY_04: page(row(tq="q", uq_needs=True, uq_tr="AR")),
            KEY_05: page(row(tq="q", uq_needs=True, uq_tr="AR")),
        }
    )

    writeback.writeback_book(nav, 4, 1, store, store_path)

    assert store[KEY_04].writeback_status == "success"
    assert store[KEY_05].writeback_status == "success"
    assert patched_io["save_store"].call_count == 2  # persisted after every acted page
    nav.select_book.assert_called_once_with(4, 1)
    assert all(is_valid_page_key(k) for k in store.keys())


def test_writeback_book_double_run_terminal_success_not_renavigated(
    patched_io: dict[str, MagicMock], store_path: Path
) -> None:
    store = TranslationStore({KEY_04: page(row(tq="q"))})  # nothing-to-fill

    nav1 = make_book_nav([pc(KEY_04)])
    writeback.writeback_book(nav1, 4, 1, store, store_path)
    assert store[KEY_04].writeback_status == "success"

    nav2 = make_book_nav([pc(KEY_04)])
    writeback.writeback_book(nav2, 4, 1, store, store_path)
    nav2.open_textapps.assert_not_called()  # resume-skip on re-run


def test_run_walks_six_books_in_order_one_session_each(
    monkeypatch: pytest.MonkeyPatch, creds_env: dict[str, str], store_path: Path
) -> None:
    monkeypatch.setenv("IBNBADIS_STORE_PATH", str(store_path))
    nav = make_book_nav({})  # every book -> no pages
    headless_seen: list[bool] = []

    @contextmanager
    def fake_session(*, headless: bool = True, settings: object = None) -> Iterator[MagicMock]:
        headless_seen.append(headless)
        yield nav

    monkeypatch.setattr(writeback, "browser_session", fake_session)

    writeback.run()

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
    nav = make_book_nav({})

    @contextmanager
    def fake_session(*, headless: bool = True, settings: object = None) -> Iterator[MagicMock]:
        yield nav

    monkeypatch.setattr(writeback, "browser_session", fake_session)

    writeback.run(only_book="year5-sem1")

    assert nav.select_book.call_args_list == [call(5, 1)]
    assert nav.login.call_count == 1


def test_run_resumes_from_on_disk_store(
    monkeypatch: pytest.MonkeyPatch, creds_env: dict[str, str], store_path: Path
) -> None:
    monkeypatch.setenv("IBNBADIS_STORE_PATH", str(store_path))
    # Seed: one already-successful page (must be resume-skipped) + one pending.
    seed = TranslationStore(
        {
            KEY_04: page(row(tq="q", uq_needs=True, uq_tr="DONE"), status="success"),
            KEY_05: page(row(tq="q", uq_needs=True, uq_tr="AR")),
        }
    )
    save_store(seed, store_path)

    nav = make_book_nav({"year4-sem1": [pc(KEY_04, num=4), pc(KEY_05, num=5)]})
    monkeypatch.setattr(writeback, "fill_translation", MagicMock())
    monkeypatch.setattr(writeback, "read_field_value", MagicMock(return_value=""))
    monkeypatch.setattr(writeback, "save_page", MagicMock(return_value=sr(SaveOutcome.PERSISTED)))
    monkeypatch.setattr(writeback, "_utc_now_iso", lambda: FIXED_TS)

    @contextmanager
    def fake_session(*, headless: bool = True, settings: object = None) -> Iterator[MagicMock]:
        yield nav

    monkeypatch.setattr(writeback, "browser_session", fake_session)

    writeback.run()

    result = load_store(store_path)
    assert result[KEY_04].writeback_status == "success"  # untouched (resume-skip)
    assert result[KEY_05].writeback_status == "success"  # acted this run
    assert result[KEY_05].writeback_timestamp == FIXED_TS


def test_writeback_does_not_log_translation_values(
    patched_io: dict[str, MagicMock], monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = RecordingLogger()
    monkeypatch.setattr(writeback, "_log", rec)
    nav = make_page_nav()
    pm = page(row(tq="q", ta="a", uq_needs=True, ua_needs=True, uq_tr=ARABIC_Q, ua_tr=ARABIC_A))

    writeback.writeback_page(nav, pm, KEY_04)

    flat = repr(rec.calls)
    assert ARABIC_Q not in flat  # values are never logged (keys/counts/status only)
    assert ARABIC_A not in flat
