"""selectors: field-name helpers, parsing, CSS builders, enum membership."""

from __future__ import annotations

import pytest

from translation_pipeline.selectors import (
    Field,
    TargetField,
    field_input_css,
    field_name,
    parse_field_name,
)


@pytest.mark.parametrize(
    ("field", "index", "expected"),
    [
        (Field.UQ, 0, "UQ0"),
        (Field.UA, 1, "UA1"),
        (Field.TQ, 12, "TQ12"),
        (Field.TA, 7, "TA7"),
        (TargetField.UQ, 0, "UQ0"),
        (TargetField.UA, 3, "UA3"),
    ],
)
def test_field_name(field: Field | TargetField, index: int, expected: str) -> None:
    assert field_name(field, index) == expected


@pytest.mark.parametrize("index", [-1, -10])
def test_field_name_rejects_negative_index(index: int) -> None:
    with pytest.raises(ValueError):
        field_name(Field.UQ, index)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("UQ0", (Field.UQ, 0)),
        ("UA1", (Field.UA, 1)),
        ("TQ12", (Field.TQ, 12)),
        ("TA7", (Field.TA, 7)),
    ],
)
def test_parse_field_name_roundtrip(name: str, expected: tuple[Field, int]) -> None:
    assert parse_field_name(name) == expected
    field, index = expected
    assert field_name(field, index) == name


@pytest.mark.parametrize(
    "name",
    ["Level", "Subject", "UQ", "", "uq0", "UQ-1", "UQ 0", "XQ0", "0UQ"],
)
def test_parse_field_name_rejects_non_grid_inputs(name: str) -> None:
    assert parse_field_name(name) is None


def test_target_field_excludes_english_source() -> None:
    values = {m.value for m in TargetField}
    assert values == {"UQ", "UA"}
    assert "TQ" not in values
    assert "TA" not in values
    # Independent enums: a TargetField is not a Field instance (mypy + runtime).
    assert not isinstance(TargetField.UQ, Field)


@pytest.mark.parametrize(
    ("field", "index", "expected"),
    [
        (Field.TQ, 3, 'input[name="TQ3"]'),
        (TargetField.UQ, 0, 'input[name="UQ0"]'),
        (TargetField.UA, 11, 'input[name="UA11"]'),
    ],
)
def test_field_input_css(field: Field | TargetField, index: int, expected: str) -> None:
    assert field_input_css(field, index) == expected


def test_field_input_css_rejects_negative_index() -> None:
    with pytest.raises(ValueError):
        field_input_css(TargetField.UQ, -1)
