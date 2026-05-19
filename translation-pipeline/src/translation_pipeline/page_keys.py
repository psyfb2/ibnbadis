"""Page-key conventions shared (as a STRING FORMAT only) with CSTC-3.

CSTC-4 reuses CSTC-3's flat page-key string so the two data sets cross-reference.
It does NOT reuse CSTC-3's files or directory structure.

Format::

    <book-key>/<section-slug>/page-<NN>

e.g. ``year4-sem1/section-1-a-new-friend/part-1/page-04``

- ``<book-key>`` = ``year{N}-sem{S}`` for ``N in {4,5,6}``, ``S in {1,2}`` -> 6 keys.
- ``<section-slug>`` = kebab-case sidebar slug, optionally with one or more extra
  path segments (e.g. a ``part-{n}`` segment).
- ``<NN>`` = zero-padded (>=2 digit) page number.

Pure functions only — no I/O. Foundational; reused by tasks 2/3/5.
"""

from __future__ import annotations

import re

#: The exactly-six book keys assigned to user ``fadi``.
BOOK_KEYS: frozenset[str] = frozenset(
    f"year{year}-sem{sem}" for year in (4, 5, 6) for sem in (1, 2)
)

#: Anchored regex for a full page key.
PAGE_KEY_RE: re.Pattern[str] = re.compile(
    r"^year[456]-sem[12]/[a-z0-9-]+(?:/[a-z0-9-]+)*/page-\d{2,}$"
)


def book_key(year: int, semester: int) -> str:
    """Return the canonical book key for ``year`` (4/5/6) and ``semester`` (1/2).

    Raises:
        ValueError: if ``year`` or ``semester`` is out of range.
    """
    if year not in (4, 5, 6):
        raise ValueError(f"year must be one of 4, 5, 6 (got {year!r})")
    if semester not in (1, 2):
        raise ValueError(f"semester must be one of 1, 2 (got {semester!r})")
    return f"year{year}-sem{semester}"


def is_valid_page_key(value: str) -> bool:
    """Return ``True`` iff ``value`` matches the canonical page-key format."""
    return PAGE_KEY_RE.match(value) is not None


def assert_valid_page_key(value: str) -> str:
    """Return ``value`` unchanged if valid; otherwise raise ``ValueError``."""
    if not is_valid_page_key(value):
        raise ValueError(
            f"invalid page key {value!r}; expected "
            r"'<book-key>/<section-slug>/page-<NN>' "
            f"matching {PAGE_KEY_RE.pattern}"
        )
    return value
