"""Pipeline **pre-write-back validator** (gates step 3).

Run *after* the no-code step-2 translation and *before* step-3 write-back. It is
deterministic, **offline** (no site I/O, no network, no browser) and
**credential-free** (never calls :func:`config.get_settings`), and it is
**read-only on the store** (only :func:`store.load_store`; never
``save_store``). It mirrors the interface-segregation guarantee of
:mod:`translation_pipeline.scrape`: it provably cannot mutate the site or the
store.

It "fails fast" in the **fail-closed** sense — :func:`run` returns a non-zero
exit code on *any* finding so ``make validate`` is a hard gate before
write-back — while still collecting **every** finding in one pass so the
operator can fix all issues in a single step-2 edit.

Failure modes (mapped 1:1 to the PRD task-4 text), checking ``UQ`` and ``UA``
**independently**:

- :attr:`ValidationCode.MISSING_TRANSLATION` — a field flagged
  ``*_needs_translation`` has a blank ``*_translation``.
- :attr:`ValidationCode.INCONSISTENT_TRANSLATION` — the same English source
  string maps to two different non-blank Arabic translations anywhere in the
  store (consistency, PRD req-11).
- :attr:`ValidationCode.ALREADY_TRANSLATED_WRITE` — an ``*_already_translated``
  field carries a non-blank ``*_translation`` (step 2 proposed overwriting a
  pre-existing manual translation — it must be left blank).
- :attr:`ValidationCode.SOURCE_FLAG_MISMATCH` — the four per-field flags
  recomputed from the stored ``tq/ta/uq/ua`` do not equal the stored flags (the
  deterministic, baseline-free proxy for "an English source / already-state was
  modified after scrape"; also catches a corrupt ``already``+``needs``
  both-true row).

The canonical "blank" rule and per-field flag formulas are **reused** from
:mod:`translation_pipeline.scrape` (``_is_blank`` / ``build_row``) — zero
duplication, parity-locked by a unit test.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from translation_pipeline.config import Settings
from translation_pipeline.logging_config import get_logger
from translation_pipeline.models import TranslationStore
from translation_pipeline.scrape import _is_blank, build_row
from translation_pipeline.site import RowFields
from translation_pipeline.store import load_store

_log = get_logger(__name__)


class ValidationCode(StrEnum):
    """The four deterministic pre-write-back failure modes."""

    MISSING_TRANSLATION = "missing_translation"
    INCONSISTENT_TRANSLATION = "inconsistent_translation"
    ALREADY_TRANSLATED_WRITE = "already_translated_write"
    SOURCE_FLAG_MISMATCH = "source_flag_mismatch"


@dataclass(frozen=True)
class Finding:
    """A single validation failure.

    Attributes:
        code: the :class:`ValidationCode` category.
        page_key: the flat store page key the finding belongs to.
        row_index: the 0-based row index, or ``None`` for store-wide findings.
        field: ``"uq"``/``"ua"``/``"tq"``/``"ta"`` or ``None``.
        message: human-readable detail (the store carries no secrets).
    """

    code: ValidationCode
    page_key: str
    row_index: int | None
    field: str | None
    message: str


# --- Pure checks (no I/O — deterministic, trivially unit-testable) ----------


def _check_missing_translations(store: TranslationStore) -> list[Finding]:
    """A ``*_needs_translation`` field whose ``*_translation`` is blank."""
    findings: list[Finding] = []
    for page_key, page in store.items():
        for idx, row in enumerate(page.rows):
            if row.uq_needs_translation and _is_blank(row.uq_translation):
                findings.append(
                    Finding(
                        code=ValidationCode.MISSING_TRANSLATION,
                        page_key=page_key,
                        row_index=idx,
                        field="uq",
                        message="uq flagged needs_translation but uq_translation is blank",
                    )
                )
            if row.ua_needs_translation and _is_blank(row.ua_translation):
                findings.append(
                    Finding(
                        code=ValidationCode.MISSING_TRANSLATION,
                        page_key=page_key,
                        row_index=idx,
                        field="ua",
                        message="ua flagged needs_translation but ua_translation is blank",
                    )
                )
    return findings


def _check_already_translated_not_written(store: TranslationStore) -> list[Finding]:
    """An ``*_already_translated`` field must keep an empty ``*_translation``."""
    findings: list[Finding] = []
    for page_key, page in store.items():
        for idx, row in enumerate(page.rows):
            if row.uq_already_translated and not _is_blank(row.uq_translation):
                findings.append(
                    Finding(
                        code=ValidationCode.ALREADY_TRANSLATED_WRITE,
                        page_key=page_key,
                        row_index=idx,
                        field="uq",
                        message=(
                            "uq_already_translated is set but uq_translation is "
                            "non-blank (would overwrite a pre-existing translation)"
                        ),
                    )
                )
            if row.ua_already_translated and not _is_blank(row.ua_translation):
                findings.append(
                    Finding(
                        code=ValidationCode.ALREADY_TRANSLATED_WRITE,
                        page_key=page_key,
                        row_index=idx,
                        field="ua",
                        message=(
                            "ua_already_translated is set but ua_translation is "
                            "non-blank (would overwrite a pre-existing translation)"
                        ),
                    )
                )
    return findings


def _check_source_flag_integrity(store: TranslationStore) -> list[Finding]:
    """Stored per-field flags must equal flags recomputed from ``tq/ta/uq/ua``.

    Reuses :func:`scrape.build_row` (``prev=None`` — translations are irrelevant
    to flags) so the validator and the scraper share one flag definition. A
    mismatch means an English source / already-translated state was modified
    after scrape, or the flags were hand-corrupted (e.g. ``already``+``needs``
    both true). UQ and UA are checked **independently**: a row with both sides
    corrupted yields one finding per side (mirroring the other per-field
    checks) so neither side is silently folded into the other's message.
    """
    findings: list[Finding] = []
    for page_key, page in store.items():
        for idx, row in enumerate(page.rows):
            expected = build_row(
                RowFields(tq=row.tq, ta=row.ta, uq=row.uq, ua=row.ua),
                prev=None,
            )
            if (
                row.uq_already_translated != expected.uq_already_translated
                or row.uq_needs_translation != expected.uq_needs_translation
            ):
                findings.append(
                    Finding(
                        code=ValidationCode.SOURCE_FLAG_MISMATCH,
                        page_key=page_key,
                        row_index=idx,
                        field="uq",
                        message=(
                            "stored UQ flags do not match flags recomputed "
                            "from tq/uq "
                            f"(stored already={row.uq_already_translated} "
                            f"needs={row.uq_needs_translation}; "
                            f"expected already={expected.uq_already_translated} "
                            f"needs={expected.uq_needs_translation})"
                        ),
                    )
                )
            if (
                row.ua_already_translated != expected.ua_already_translated
                or row.ua_needs_translation != expected.ua_needs_translation
            ):
                findings.append(
                    Finding(
                        code=ValidationCode.SOURCE_FLAG_MISMATCH,
                        page_key=page_key,
                        row_index=idx,
                        field="ua",
                        message=(
                            "stored UA flags do not match flags recomputed "
                            "from ta/ua "
                            f"(stored already={row.ua_already_translated} "
                            f"needs={row.ua_needs_translation}; "
                            f"expected already={expected.ua_already_translated} "
                            f"needs={expected.ua_needs_translation})"
                        ),
                    )
                )
    return findings


def _check_translation_consistency(store: TranslationStore) -> list[Finding]:
    """The same English source string must map to one Arabic string everywhere.

    A single store-wide map spans **both** ``(tq -> uq_translation)`` and
    ``(ta -> ua_translation)`` pairs (a question and an answer that are
    byte-identical English must share one Arabic value — PRD req-11). Only pairs
    whose source **and** translation are non-blank participate; site values
    (``uq``/``ua``) are deliberately excluded (consistency is about the
    Claude-authored translations, not the site's pre-existing conventions). The
    grouping key is the **verbatim** source string — ``tq``/``ta`` are
    read-only verbatim site values so genuine duplicates are byte-identical.
    """
    occurrences: dict[str, list[tuple[str, str, int, str]]] = {}
    for page_key, page in store.items():
        for idx, row in enumerate(page.rows):
            for src, trans, field in (
                (row.tq, row.uq_translation, "uq"),
                (row.ta, row.ua_translation, "ua"),
            ):
                if _is_blank(src) or _is_blank(trans):
                    continue
                occurrences.setdefault(src, []).append((trans, page_key, idx, field))

    findings: list[Finding] = []
    for occ in occurrences.values():
        distinct = sorted({trans for trans, _, _, _ in occ})
        if len(distinct) < 2:
            continue
        for trans, page_key, idx, field in occ:
            findings.append(
                Finding(
                    code=ValidationCode.INCONSISTENT_TRANSLATION,
                    page_key=page_key,
                    row_index=idx,
                    field=field,
                    message=(
                        f"English source maps to {len(distinct)} different "
                        f"Arabic translations {distinct!r}; this occurrence "
                        f"uses {trans!r}"
                    ),
                )
            )
    return findings


def validate_store(store: TranslationStore) -> list[Finding]:
    """Run every check and aggregate **all** findings (not first-only).

    Args:
        store: the loaded translations store.

    Returns:
        Every :class:`Finding` across all four checks; an empty list means the
        store is ready for step-3 write-back.
    """
    findings: list[Finding] = []
    findings += _check_missing_translations(store)
    findings += _check_already_translated_not_written(store)
    findings += _check_source_flag_integrity(store)
    findings += _check_translation_consistency(store)
    return findings


# --- Thin shell (I/O — credential-free, read-only on the store) ------------


def _resolve_store_path(cli_path: str | None) -> Path:
    """Resolve the store path: ``--store`` > ``IBNBADIS_STORE_PATH`` > default.

    The default is read from the :class:`Settings` field metadata, NOT via
    :func:`config.get_settings`, so an offline validation never requires
    credentials.
    """
    if cli_path is not None:
        return Path(cli_path)
    env = os.environ.get("IBNBADIS_STORE_PATH")
    if env:
        return Path(env)
    return Path(Settings.model_fields["store_path"].default)


def run(*, store_path: Path | None = None) -> int:
    """Validate the store; return ``0`` if clean, ``1`` if any finding exists.

    Args:
        store_path: explicit store path; when ``None`` it is resolved from
            ``IBNBADIS_STORE_PATH`` or the configured default. A missing store
            file loads as an empty store (vacuously valid → ``0``).

    Returns:
        ``0`` when there are no findings, ``1`` otherwise (fail-closed gate).
    """
    path = store_path if store_path is not None else _resolve_store_path(None)
    store = load_store(path)
    findings = validate_store(store)

    if not findings:
        _log.info("validate_ok", store_path=str(path), pages=len(store))
        return 0

    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.code.value] = counts.get(finding.code.value, 0) + 1
        _log.warning(
            "validation_finding",
            code=finding.code.value,
            page_key=finding.page_key,
            row_index=finding.row_index,
            field=finding.field,
            message=finding.message,
        )
    _log.error(
        "validation_failed",
        store_path=str(path),
        total=len(findings),
        counts=counts,
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for ``make validate`` / ``python -m ...validate``."""
    parser = argparse.ArgumentParser(
        prog="validate",
        description=(
            "CSTC-4 pipeline pre-write-back validator: fail-closed, offline, "
            "credential-free check that the store is ready for step-3."
        ),
    )
    parser.add_argument(
        "--store",
        default=None,
        help=(
            "path to the translations store "
            "(default: $IBNBADIS_STORE_PATH or store/translations.json)."
        ),
    )
    args = parser.parse_args(argv)
    return run(store_path=_resolve_store_path(args.store))


if __name__ == "__main__":
    raise SystemExit(main())
