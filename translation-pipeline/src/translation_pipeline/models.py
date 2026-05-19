"""Typed schema for the standalone data store ``store/translations.json``.

The store is a single JSON object whose top-level keys are flat CSTC-3-style page
strings (see :mod:`translation_pipeline.page_keys`). Each value is a :class:`Page`
holding an ordered list of :class:`Row` objects (list index == 0-based row index)
plus page-level write-back bookkeeping.

This schema is the contract for tasks 3 (merge-refresh) and 5 (per-field
write-back / idempotency); its defaults are deliberately shaped so those tasks
need no schema change.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Literal

from pydantic import BaseModel, ConfigDict, RootModel


class Row(BaseModel):
    """A single TextApps row (0-based; its index is its position in ``Page.rows``).

    UQ and UA are independent write targets: a row may have one side already
    translated on the site and the other side blank, hence the per-field flags.
    """

    model_config = ConfigDict(extra="forbid")

    # English source — read-only by convention (never modified by this pipeline).
    tq: str = ""
    ta: str = ""

    # Site UQ/UA values AS CAPTURED AT SCRAPE TIME (step 1).
    uq: str = ""
    ua: str = ""

    # Arabic to write — filled by the no-code translation step (step 2).
    uq_translation: str = ""
    ua_translation: str = ""

    # Independent per-field flags.
    uq_already_translated: bool = False
    uq_needs_translation: bool = False
    ua_already_translated: bool = False
    ua_needs_translation: bool = False


class Page(BaseModel):
    """All rows for one page plus its write-back bookkeeping."""

    model_config = ConfigDict(extra="forbid")

    #: Ordered rows; the list index *is* the 0-based row index (no explicit
    #: index field — position is the single source of truth).
    rows: list[Row] = []

    writeback_status: Literal["pending", "success", "failed"] = "pending"
    writeback_error: str | None = None
    #: ISO-8601 UTC timestamp string of the last write-back attempt.
    writeback_timestamp: str | None = None
    #: Reason a page was skipped (e.g. no English Q&A at scrape time).
    skip_reason: str | None = None


class TranslationStore(RootModel[dict[str, Page]]):
    """The whole store: ``{page_key: Page}``.

    The page key lives only as the dict key (never duplicated inside ``Page``)
    so there is a single source of truth and no drift.
    """

    root: dict[str, Page] = {}

    # Minimal mapping-style passthroughs (KISS) used by store I/O and later tasks.
    def __getitem__(self, key: str) -> Page:
        return self.root[key]

    def __setitem__(self, key: str, value: Page) -> None:
        self.root[key] = value

    def __contains__(self, key: str) -> bool:
        return key in self.root

    def get(self, key: str, default: Page | None = None) -> Page | None:
        return self.root.get(key, default)

    # Intentionally diverges from BaseModel.__iter__ (which yields field
    # tuples): a RootModel-as-mapping iterates its keys, like a dict.
    def __iter__(self) -> Iterator[str]:  # type: ignore[override]
        return iter(self.root)

    def __len__(self) -> int:
        return len(self.root)

    def items(self):
        return self.root.items()

    def keys(self):
        return self.root.keys()

    def values(self):
        return self.root.values()
