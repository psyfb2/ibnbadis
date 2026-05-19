"""Page-key conventions: book-key set, helper, regex accept/reject."""

from __future__ import annotations

import pytest

from translation_pipeline.page_keys import (
    BOOK_KEYS,
    assert_valid_page_key,
    book_key,
    is_valid_page_key,
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
