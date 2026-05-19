"""Schema round-trip + invariants."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from tests.conftest import ARABIC_A, ARABIC_Q
from translation_pipeline.models import Page, Row, TranslationStore

PAGE_KEY = "year4-sem1/section-1-a-new-friend/part-1/page-04"


def _sample_store() -> TranslationStore:
    row_translated_q_blank_a = Row(
        tq="What is your name?",
        ta="My name is Ali.",
        uq=ARABIC_Q,  # already translated on the site
        ua="",
        uq_translation="",
        ua_translation=ARABIC_A,  # step-2 fills the blank side only
        uq_already_translated=True,
        uq_needs_translation=False,
        ua_already_translated=False,
        ua_needs_translation=True,
    )
    page = Page(rows=[row_translated_q_blank_a], writeback_status="pending")
    return TranslationStore({PAGE_KEY: page})


def test_round_trip_preserves_arabic_and_structure() -> None:
    store = _sample_store()
    dumped = json.dumps(store.model_dump(mode="json"), ensure_ascii=False, indent=2)
    reloaded = TranslationStore.model_validate_json(dumped)
    assert reloaded == store
    assert reloaded[PAGE_KEY].rows[0].ua_translation == ARABIC_A


def test_serialized_arabic_is_literal_not_escaped() -> None:
    store = _sample_store()
    text = json.dumps(store.model_dump(mode="json"), ensure_ascii=False)
    assert ARABIC_A in text
    assert "\\u0" not in text  # no \uXXXX escaping of Arabic


def test_independent_per_field_flags_representable() -> None:
    row = _sample_store()[PAGE_KEY].rows[0]
    # One side already translated, the other still needs translation.
    assert row.uq_already_translated is True
    assert row.uq_needs_translation is False
    assert row.ua_already_translated is False
    assert row.ua_needs_translation is True


def test_row_rejects_unknown_keys() -> None:
    with pytest.raises(ValidationError):
        Row(tq="x", bogus_field="nope")  # type: ignore[call-arg]


def test_page_rejects_unknown_keys() -> None:
    with pytest.raises(ValidationError):
        Page(rows=[], not_a_field=1)  # type: ignore[call-arg]


def test_defaults_are_blank_and_pending() -> None:
    row = Row()
    assert (row.tq, row.ta, row.uq, row.ua) == ("", "", "", "")
    assert row.uq_translation == "" and row.ua_translation == ""
    assert not any(
        (
            row.uq_already_translated,
            row.uq_needs_translation,
            row.ua_already_translated,
            row.ua_needs_translation,
        )
    )
    page = Page()
    assert page.rows == []
    assert page.writeback_status == "pending"
    assert page.writeback_error is None
    assert page.writeback_timestamp is None
    assert page.skip_reason is None


def test_writeback_status_enum_enforced() -> None:
    with pytest.raises(ValidationError):
        Page(writeback_status="bogus")  # type: ignore[arg-type]


def test_row_index_is_list_position() -> None:
    rows = [Row(tq=f"q{i}") for i in range(3)]
    page = Page(rows=rows)
    store = TranslationStore({PAGE_KEY: page})
    reloaded = TranslationStore.model_validate_json(json.dumps(store.model_dump(mode="json")))
    assert [r.tq for r in reloaded[PAGE_KEY].rows] == ["q0", "q1", "q2"]
