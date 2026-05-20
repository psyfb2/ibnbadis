"""Page-key conventions: book-key set, helper, regex accept/reject."""

from __future__ import annotations

import pytest

from translation_pipeline.page_keys import (
    BOOK_KEYS,
    assert_valid_page_key,
    book_key,
    compose_page_key,
    is_valid_page_key,
    section_slug,
    slugify,
)


def test_exactly_six_book_keys() -> None:
    assert BOOK_KEYS == {
        "year4-sem1",
        "year4-sem2",
        "year5-sem1",
        "year5-sem2",
        "year6-sem1",
        "year6-sem2",
    }


@pytest.mark.parametrize(
    ("year", "sem", "expected"),
    [
        (4, 1, "year4-sem1"),
        (5, 2, "year5-sem2"),
        (6, 1, "year6-sem1"),
    ],
)
def test_book_key_helper(year: int, sem: int, expected: str) -> None:
    assert book_key(year, sem) == expected
    assert expected in BOOK_KEYS


@pytest.mark.parametrize(("year", "sem"), [(3, 1), (7, 2), (4, 0), (5, 3)])
def test_book_key_rejects_out_of_range(year: int, sem: int) -> None:
    with pytest.raises(ValueError):
        book_key(year, sem)


@pytest.mark.parametrize(
    "key",
    [
        # Real examples from CSTC-3 state/state.json.
        "year4-sem1/section-1-a-new-friend/part-1/page-04",
        "year4-sem1/section-2-our-house/part-2/page-15",
        "year4-sem1/section-4-shopping-list/part-1/page-22",
        # No /part- segment is also valid.
        "year6-sem2/section-3-lost/page-101",
    ],
)
def test_regex_accepts_valid_keys(key: str) -> None:
    assert is_valid_page_key(key)
    assert assert_valid_page_key(key) == key


@pytest.mark.parametrize(
    "key",
    [
        "year4-sem1/section-1-a-new-friend/part-1/page-4",  # unpadded NN
        "year3-sem1/section-1/page-04",  # bad year
        "year4-sem3/section-1/page-04",  # bad semester
        "year4-sem1/Section-1/page-04",  # uppercase slug
        "year4-sem1/section-1/page-04/extra",  # trailing segment after page
        "year4-sem1//page-04",  # empty section slug
        "year4-sem1/section-1/pg-04",  # wrong page token
        "",  # empty
        "year4-sem1/section-1/page-",  # missing number
    ],
)
def test_regex_rejects_malformed_keys(key: str) -> None:
    assert not is_valid_page_key(key)
    with pytest.raises(ValueError):
        assert_valid_page_key(key)


# --- slugify / section_slug / compose_page_key (task 2) --------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("A New Friend!", "a-new-friend"),
        ("It's mine", "it-s-mine"),
        ("  Mixed   CASE  ", "mixed-case"),
        ("Hello---World", "hello-world"),
        ("a/b", "a-b"),
        ("مرحبا world", "world"),  # Arabic run collapses to one '-' then trims
        ("مرحبا", ""),  # purely non-ASCII -> empty
        ("---", ""),  # only separators -> empty
        ("Unit 1: Family & Friends", "unit-1-family-friends"),
    ],
)
def test_slugify(text: str, expected: str) -> None:
    assert slugify(text) == expected


@pytest.mark.parametrize(
    ("index", "title", "part", "expected"),
    [
        (1, "A New Friend", None, "section-1-a-new-friend"),
        (1, "A New Friend", 2, "section-1-a-new-friend/part-2"),
        (3, "مرحبا", None, "section-3"),  # empty slug -> no trailing dash
        (3, "مرحبا", 1, "section-3/part-1"),
    ],
)
def test_section_slug(index: int, title: str, part: int | None, expected: str) -> None:
    assert section_slug(index, title, part) == expected


@pytest.mark.parametrize(
    ("bk", "slug", "page", "expected"),
    [
        (
            "year4-sem1",
            "section-1-a-new-friend/part-1",
            4,
            "year4-sem1/section-1-a-new-friend/part-1/page-04",
        ),
        ("year6-sem2", "section-3-lost", 101, "year6-sem2/section-3-lost/page-101"),
        ("year5-sem1", "section-2", 9, "year5-sem1/section-2/page-09"),
    ],
)
def test_compose_page_key(bk: str, slug: str, page: int, expected: str) -> None:
    key = compose_page_key(bk, slug, page)
    assert key == expected
    assert is_valid_page_key(key)


def test_compose_page_key_is_consistent_with_helpers() -> None:
    key = compose_page_key("year4-sem1", section_slug(1, "A New Friend", 1), 4)
    assert key == "year4-sem1/section-1-a-new-friend/part-1/page-04"


@pytest.mark.parametrize(
    ("bk", "slug", "page"),
    [
        ("year3-sem1", "section-1", 4),  # bad year -> invalid composed key
        ("year4-sem1", "Section-1", 4),  # uppercase slug
        ("year4-sem1", "section-1", -1),  # negative page number
        ("year4-sem1", "section-1", 0),  # 0 would format as page-00
    ],
)
def test_compose_page_key_rejects_invalid(bk: str, slug: str, page: int) -> None:
    with pytest.raises(ValueError):
        compose_page_key(bk, slug, page)
