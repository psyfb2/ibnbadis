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


#: Any run of characters that are NOT lowercase ASCII alphanumerics.
_NON_SLUG_RE: re.Pattern[str] = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    """Deterministically kebab-case ``text`` for use in a section slug.

    Lowercases, then collapses every run of non ``[a-z0-9]`` characters
    (whitespace, punctuation, apostrophes, and any non-ASCII text such as
    Arabic) into a single ``-`` and trims leading/trailing ``-``. A title that
    contains no ASCII alphanumerics (e.g. a purely Arabic title) yields ``""``;
    :func:`section_slug` handles that case so the composed key stays valid.
    """
    return _NON_SLUG_RE.sub("-", text.strip().lower()).strip("-")


def section_slug(index: int, title: str, part: int | None = None) -> str:
    """Build the ``<section-slug>`` path segment(s) for a page key.

    Always starts ``section-{index}`` so the slug is non-empty and key-valid
    even when ``title`` slugifies to ``""``. An optional ``part`` appends a
    ``/part-{part}`` segment (mirrors CSTC-3's ``.../part-{n}/...`` keys).

    Note: CSTC-3's hand-made special slugs (``dictionary``, ``ending``,
    ``pictionary-and-alphabet``) are NOT algorithmically reproducible; CSTC-4
    uses this deterministic ``section-{index}-{slug}`` rule consistently, which
    is format-compliant and internally consistent (scrape and write-back key by
    the same rule). Cross-reference with CSTC-3 is therefore best-effort by key.
    """
    slug = slugify(title)
    base = f"section-{index}-{slug}" if slug else f"section-{index}"
    if part is not None:
        base += f"/part-{part}"
    return base


def compose_page_key(book_key: str, section_slug: str, page_number: int) -> str:
    """Compose and validate a full flat page key.

    Args:
        book_key: e.g. ``year4-sem1`` (see :func:`book_key`).
        section_slug: a slug as produced by :func:`section_slug` (may itself
            contain a ``/part-{n}`` segment).
        page_number: 1-based page number; zero-padded to >=2 digits.

    Raises:
        ValueError: if the composed key is not a valid page key.
    """
    return assert_valid_page_key(f"{book_key}/{section_slug}/page-{page_number:02d}")
