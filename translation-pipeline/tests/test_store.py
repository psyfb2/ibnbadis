"""Store I/O: round-trip, .bak, missing/corrupt fallback, interrupt-safety."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.conftest import ARABIC_Q
from translation_pipeline import store as store_mod
from translation_pipeline.models import Page, Row, TranslationStore
from translation_pipeline.store import (
    StoreCorruptError,
    _bak_path,
    load_store,
    save_store,
)

PAGE_KEY = "year5-sem2/section-2-our-house/part-1/page-11"


def _store(text: str) -> TranslationStore:
    return TranslationStore({PAGE_KEY: Page(rows=[Row(tq="q", uq_translation=text)])})


def test_save_then_load_round_trips(store_path: Path) -> None:
    original = _store(ARABIC_Q)
    save_store(original, store_path)
    assert load_store(store_path) == original


def test_missing_file_returns_empty_store(store_path: Path) -> None:
    assert load_store(store_path) == TranslationStore({})
    assert len(load_store(store_path)) == 0


def test_bak_created_on_overwrite_and_holds_previous_content(store_path: Path) -> None:
    first = _store("first")
    second = _store("second")
    save_store(first, store_path)
    save_store(second, store_path)

    bak = _bak_path(store_path)
    assert bak.exists()
    # .bak holds the PREVIOUS good version; main holds the latest.
    assert load_store(bak) == first
    assert load_store(store_path) == second


def test_corrupt_main_with_valid_bak_falls_back(store_path: Path) -> None:
    save_store(_store("good"), store_path)  # creates main
    save_store(_store("good2"), store_path)  # creates valid .bak (== first)
    store_path.write_text("{ not json", encoding="utf-8")

    loaded = load_store(store_path)
    assert loaded == _store("good")  # the .bak content


def test_corrupt_main_and_no_bak_raises(store_path: Path) -> None:
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text("{ not json", encoding="utf-8")
    with pytest.raises(StoreCorruptError):
        load_store(store_path)


def test_corrupt_main_and_corrupt_bak_raises(store_path: Path) -> None:
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text("{ not json", encoding="utf-8")
    _bak_path(store_path).write_text("also broken", encoding="utf-8")
    with pytest.raises(StoreCorruptError):
        load_store(store_path)


def test_serialized_file_contains_literal_arabic(store_path: Path) -> None:
    save_store(_store(ARABIC_Q), store_path)
    text = store_path.read_text(encoding="utf-8")
    assert ARABIC_Q in text
    assert "\\u0" not in text


def test_interrupt_safety_on_replace_failure(
    store_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed os.replace must leave the original intact and leak no temp file."""
    save_store(_store("original"), store_path)

    real_replace = os.replace

    def boom(src: object, dst: object) -> None:
        # Simulate a kill/failure AFTER the temp file is fully written.
        raise OSError("simulated replace failure")

    monkeypatch.setattr(store_mod.os, "replace", boom)
    with pytest.raises(OSError, match="simulated replace failure"):
        save_store(_store("new-data"), store_path)

    monkeypatch.setattr(store_mod.os, "replace", real_replace)

    # Original file is still intact & valid.
    assert load_store(store_path) == _store("original")
    # No orphaned temp files left in the store directory.
    leftovers = [
        p.name
        for p in store_path.parent.iterdir()
        if p.name.startswith(store_path.name + ".") and p.name.endswith(".tmp")
    ]
    assert leftovers == []


def test_save_creates_parent_directory(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b" / "translations.json"
    save_store(_store("x"), nested)
    assert nested.exists()
