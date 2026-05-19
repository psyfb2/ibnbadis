"""validate (pre-write-back gate): pure checks + credential-free shell.

All tests are pure-Python with inline ``TranslationStore`` fixtures — no
browser, no network, no credentials. Mirrors ``test_scrape.py`` conventions.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.conftest import ARABIC_A, ARABIC_Q
from translation_pipeline import validate
from translation_pipeline.core import build_row
from translation_pipeline.models import Page, Row, TranslationStore
from translation_pipeline.site import RowFields
from translation_pipeline.store import save_store
from translation_pipeline.validate import (
    Finding,
    ValidationCode,
    validate_store,
)

DOC_PATH = Path(__file__).resolve().parents[1] / "docs" / "step-2-translation-procedure.md"


def needs_row(
    *,
    tq: str = "q",
    ta: str = "a",
    uq_translation: str = ARABIC_Q,
    ua_translation: str = ARABIC_A,
) -> Row:
    """A row needing both sides, flags consistent with ``build_row``."""
    return Row(
        tq=tq,
        ta=ta,
        uq="",
        ua="",
        uq_translation=uq_translation,
        ua_translation=ua_translation,
        uq_needs_translation=True,
        ua_needs_translation=True,
    )


def already_row(*, uq_translation: str = "", ua_translation: str = "") -> Row:
    """A row already translated on the site (no step-2 output expected)."""
    return Row(
        tq="q",
        ta="a",
        uq="موجود",
        ua="موجود",
        uq_translation=uq_translation,
        ua_translation=ua_translation,
        uq_already_translated=True,
        ua_already_translated=True,
    )


def store(**pages: Page) -> TranslationStore:
    return TranslationStore(dict(pages))


# --- PASS / vacuous --------------------------------------------------------


def test_clean_store_has_no_findings() -> None:
    s = store(
        p1=Page(rows=[needs_row(), already_row()]),
        p2=Page(rows=[needs_row(tq="q", uq_translation=ARABIC_Q)]),  # consistent
    )
    assert validate_store(s) == []


def test_empty_store_is_vacuously_valid() -> None:
    assert validate_store(TranslationStore({})) == []


def test_skip_and_no_english_rows_yield_no_findings() -> None:
    s = store(
        skipped=Page(rows=[], skip_reason="no_english_qa"),
        blank=Page(rows=[Row()]),  # all-blank row: no flags, nothing to do
    )
    assert validate_store(s) == []


# --- MISSING_TRANSLATION ---------------------------------------------------


def test_missing_translation_empty_and_whitespace_only() -> None:
    s = store(
        empty=Page(rows=[needs_row(uq_translation="", ua_translation="")]),
        ws=Page(rows=[needs_row(uq_translation="   ", ua_translation="\t\n")]),
    )
    findings = validate_store(s)
    missing = [f for f in findings if f.code is ValidationCode.MISSING_TRANSLATION]
    assert len(missing) == 4
    assert {f.field for f in missing} == {"uq", "ua"}


def test_missing_translation_independent_ua_only() -> None:
    s = store(p=Page(rows=[needs_row(uq_translation=ARABIC_Q, ua_translation="")]))
    findings = validate_store(s)
    assert findings == [
        Finding(
            code=ValidationCode.MISSING_TRANSLATION,
            page_key="p",
            row_index=0,
            field="ua",
            message="ua flagged needs_translation but ua_translation is blank",
        )
    ]


# --- INCONSISTENT_TRANSLATION ---------------------------------------------


def test_inconsistent_same_tq_different_arabic_across_pages() -> None:
    s = store(
        p1=Page(rows=[needs_row(tq="hello", uq_translation="مرحبا")]),
        p2=Page(rows=[needs_row(tq="hello", uq_translation="أهلا")]),
    )
    inconsistent = [
        f for f in validate_store(s) if f.code is ValidationCode.INCONSISTENT_TRANSLATION
    ]
    # one finding per occurrence of the conflicting source.
    assert len(inconsistent) == 2
    assert {f.page_key for f in inconsistent} == {"p1", "p2"}


def test_inconsistent_tq_and_ta_byte_identical_global_map() -> None:
    # "cat" appears once as a tq and once as a ta with different Arabic.
    row_q = Row(tq="cat", ta="", uq="", ua="", uq_translation="قطة", uq_needs_translation=True)
    row_a = Row(tq="", ta="cat", uq="", ua="", ua_translation="هر", ua_needs_translation=True)
    s = store(p=Page(rows=[row_q, row_a]))
    inconsistent = [
        f for f in validate_store(s) if f.code is ValidationCode.INCONSISTENT_TRANSLATION
    ]
    assert len(inconsistent) == 2
    assert {f.field for f in inconsistent} == {"uq", "ua"}


def test_consistent_same_source_same_arabic_across_pages_is_ok() -> None:
    s = store(
        p1=Page(rows=[needs_row(tq="x", uq_translation="ص")]),
        p2=Page(rows=[needs_row(tq="x", uq_translation="ص")]),
    )
    assert [f for f in validate_store(s) if f.code is ValidationCode.INCONSISTENT_TRANSLATION] == []


# --- ALREADY_TRANSLATED_WRITE ---------------------------------------------


def test_already_translated_write_uq_and_independent_ua() -> None:
    s = store(
        both=Page(rows=[already_row(uq_translation="x", ua_translation="y")]),
        ua_only=Page(rows=[already_row(uq_translation="", ua_translation="z")]),
    )
    findings = [f for f in validate_store(s) if f.code is ValidationCode.ALREADY_TRANSLATED_WRITE]
    assert len(findings) == 3
    assert sorted(f.field or "" for f in findings) == ["ua", "ua", "uq"]


# --- SOURCE_FLAG_MISMATCH --------------------------------------------------


def test_source_flag_mismatch_when_flags_tampered() -> None:
    # tq set + uq blank -> build_row expects uq_needs=True; stored says False.
    tampered = Row(tq="q", ta="", uq="", ua="", uq_needs_translation=False)
    s = store(p=Page(rows=[tampered]))
    findings = [f for f in validate_store(s) if f.code is ValidationCode.SOURCE_FLAG_MISMATCH]
    assert len(findings) == 1
    assert findings[0].field == "uq"


def test_source_flag_mismatch_already_and_needs_both_true() -> None:
    corrupt = Row(
        tq="q",
        ta="",
        uq="",
        ua="",
        uq_translation=ARABIC_Q,
        uq_already_translated=True,
        uq_needs_translation=True,
    )
    s = store(p=Page(rows=[corrupt]))
    codes = {f.code for f in validate_store(s)}
    assert ValidationCode.SOURCE_FLAG_MISMATCH in codes


def test_source_flag_mismatch_both_sides_independent_findings() -> None:
    # tq+ta set, uq+ua blank -> build_row expects BOTH needs=True; stored
    # says both False -> one independent finding per side (not folded).
    both = Row(
        tq="q",
        ta="a",
        uq="",
        ua="",
        uq_needs_translation=False,
        ua_needs_translation=False,
    )
    s = store(p=Page(rows=[both]))
    findings = [f for f in validate_store(s) if f.code is ValidationCode.SOURCE_FLAG_MISMATCH]
    assert len(findings) == 2
    assert {f.field for f in findings} == {"uq", "ua"}


# --- Independent UQ/UA -----------------------------------------------------


def test_independent_uq_ok_ua_missing_reports_only_ua() -> None:
    s = store(p=Page(rows=[needs_row(uq_translation=ARABIC_Q, ua_translation="")]))
    findings = validate_store(s)
    assert len(findings) == 1
    assert findings[0].field == "ua"


def test_independent_ua_ok_uq_missing_reports_only_uq() -> None:
    s = store(p=Page(rows=[needs_row(uq_translation="", ua_translation=ARABIC_A)]))
    findings = validate_store(s)
    assert len(findings) == 1
    assert findings[0].field == "uq"


# --- Aggregation (collect all, not first-only) -----------------------------


def test_aggregates_all_distinct_violations() -> None:
    s = store(
        miss=Page(rows=[needs_row(uq_translation="", ua_translation=ARABIC_A)]),
        already=Page(rows=[already_row(uq_translation="x")]),
        flag=Page(rows=[Row(tq="q", uq_needs_translation=False)]),
        incon1=Page(rows=[needs_row(tq="dup", uq_translation="A")]),
        incon2=Page(rows=[needs_row(tq="dup", uq_translation="B")]),
    )
    codes = {f.code for f in validate_store(s)}
    assert codes == {
        ValidationCode.MISSING_TRANSLATION,
        ValidationCode.ALREADY_TRANSLATED_WRITE,
        ValidationCode.SOURCE_FLAG_MISMATCH,
        ValidationCode.INCONSISTENT_TRANSLATION,
    }


# --- Flag-reuse parity (locks exact reuse of core.build_row) -------------


@pytest.mark.parametrize(
    ("tq", "ta", "uq", "ua"),
    [
        ("q", "a", "", ""),
        ("q", "a", "ت", "ت"),
        ("", "", "", ""),
        ("  ", "\t", "  ", "\n"),
        ("q", "a", "ت", ""),
        ("", "a", "", ""),
    ],
)
def test_source_flag_check_uses_build_row_logic(tq: str, ta: str, uq: str, ua: str) -> None:
    expected = build_row(RowFields(tq=tq, ta=ta, uq=uq, ua=ua), prev=None)
    consistent = Row(
        tq=tq,
        ta=ta,
        uq=uq,
        ua=ua,
        uq_already_translated=expected.uq_already_translated,
        uq_needs_translation=expected.uq_needs_translation,
        ua_already_translated=expected.ua_already_translated,
        ua_needs_translation=expected.ua_needs_translation,
    )
    s = store(p=Page(rows=[consistent]))
    assert [f for f in validate_store(s) if f.code is ValidationCode.SOURCE_FLAG_MISMATCH] == []


# --- Shell: run() / main() / store-path resolution -------------------------


def test_run_returns_zero_on_clean_store(store_path: Path) -> None:
    save_store(store(p=Page(rows=[needs_row()])), store_path)
    assert validate.run(store_path=store_path) == 0


def test_run_returns_one_on_findings(store_path: Path) -> None:
    save_store(store(p=Page(rows=[needs_row(uq_translation="")])), store_path)
    assert validate.run(store_path=store_path) == 1


def test_run_is_credential_free(clean_ibnbadis_env: None) -> None:
    # No IBNBADIS_* env at all; missing default store -> empty -> exit 0.
    assert validate.run() == 0
    assert validate.main([]) == 0


def test_missing_store_file_is_exit_zero(tmp_path: Path) -> None:
    assert validate.run(store_path=tmp_path / "absent.json") == 0


def test_store_path_precedence_cli_over_env(
    clean_ibnbadis_env: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bad = tmp_path / "bad.json"
    good = tmp_path / "good.json"
    save_store(store(p=Page(rows=[needs_row(uq_translation="")])), bad)  # findings
    save_store(store(p=Page(rows=[needs_row()])), good)  # clean
    monkeypatch.setenv("IBNBADIS_STORE_PATH", str(bad))
    # --store wins over the env var.
    assert validate.main(["--store", str(good)]) == 0


def test_store_path_precedence_env_over_default(
    clean_ibnbadis_env: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bad = tmp_path / "bad.json"
    save_store(store(p=Page(rows=[needs_row(uq_translation="")])), bad)
    monkeypatch.setenv("IBNBADIS_STORE_PATH", str(bad))
    assert validate.main([]) == 1


def test_main_returns_run_exit_code(store_path: Path) -> None:
    save_store(store(p=Page(rows=[needs_row(uq_translation="")])), store_path)
    assert validate.main(["--store", str(store_path)]) == 1


# --- Read-only AST/import guarantee (mirrors test_scrape.py) ---------------


def test_validate_module_is_read_only_offline() -> None:
    assert not hasattr(validate, "write_helper")
    assert not hasattr(validate, "save_store")

    tree = ast.parse(Path(validate.__file__).read_text(encoding="utf-8"))
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
        "save_store",
        "get_settings",
        "SAVE_BUTTON_SELECTOR",
        "SAVE_ENDPOINT_SUBSTR",
    }
    assert forbidden.isdisjoint(imported)
    assert forbidden.isdisjoint(identifiers)


# --- Step-2 doc contract ---------------------------------------------------


def test_step2_doc_exists_and_specifies_the_contract() -> None:
    assert DOC_PATH.is_file()
    text = DOC_PATH.read_text(encoding="utf-8").lower()
    for anchor in (
        "uq_translation",
        "ua_translation",
        "tq",
        "ta",
        "already_translated",
        "needs_translation",
        "make validate",
        "consistent",
        "primary",
        "never",
    ):
        assert anchor in text, f"step-2 doc missing contract anchor: {anchor!r}"
