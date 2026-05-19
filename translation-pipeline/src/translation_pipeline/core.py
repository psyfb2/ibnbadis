"""Canonical, side-effect-free pipeline rules shared by every step.

This module is the **single source of truth** for the two cross-cutting rules
that scrape (step 1), the validator and write-back (step 3) must all agree on:

- :func:`is_blank` — the whitespace-aware "this field is empty" definition
  (RUNBOOK §6: empty rows count as not-present).
- :func:`build_row` — the per-field flag formulas turning a freshly-read row
  into a :class:`~translation_pipeline.models.Row`.

Keeping these here (rather than anchoring them in ``scrape`` and importing the
private ``scrape._is_blank`` across modules) makes the shared contract explicit
and stops the validator/write-back depending on a module-private implementation
detail of the scrape step. The module is pure (no Playwright, no store I/O), so
it is trivially unit-testable and safe for any step to import.
"""

from __future__ import annotations

from translation_pipeline.models import Row
from translation_pipeline.site import RowFields


def is_blank(value: str) -> bool:
    """Whitespace-aware "blank" test (RUNBOOK §6: empty rows are not-present).

    The single definition of "blank" reused by every per-field flag, the
    no-English skip rule, the validator and the write-back no-overwrite guard,
    so all of them stay consistent.

    Args:
        value: the raw field value.

    Returns:
        ``True`` when ``value`` is empty or whitespace-only.
    """
    return value.strip() == ""


def build_row(src: RowFields, *, prev: Row | None) -> Row:
    """Build a :class:`~translation_pipeline.models.Row` from live fields.

    Source (``tq``/``ta``) and site-state (``uq``/``ua``) and the four
    independent per-field flags are refreshed from ``src`` every scrape. The
    step-2 Arabic (``uq_translation``/``ua_translation``) is carried forward
    from ``prev`` (the row previously at this index) and is never derived from
    the site nor cleared by a re-scrape.

    Per-field flags are independent: ``UQ`` keys off ``tq``, ``UA`` off ``ta``.
    ``*_already_translated`` and ``*_needs_translation`` are mutually exclusive
    for one side but **both are ``False``** when that side has no English
    source (valid, not an error).

    Args:
        src: the row as read from the site at scrape time.
        prev: the row previously stored at this 0-based index, or ``None``.
    """
    uq_blank = is_blank(src.uq)
    ua_blank = is_blank(src.ua)
    tq_blank = is_blank(src.tq)
    ta_blank = is_blank(src.ta)
    return Row(
        tq=src.tq,
        ta=src.ta,
        uq=src.uq,
        ua=src.ua,
        uq_translation=prev.uq_translation if prev is not None else "",
        ua_translation=prev.ua_translation if prev is not None else "",
        uq_already_translated=not uq_blank,
        uq_needs_translation=(not tq_blank) and uq_blank,
        ua_already_translated=not ua_blank,
        ua_needs_translation=(not ta_blank) and ua_blank,
    )
