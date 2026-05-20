"""write_helper: fill-by-index guard, live read, Save classification.

Playwright is fully mocked — no browser, no network. The empty-form-skip /
filled-form single-retry POLICY is task 5; here ``save_page`` is just a
click + classify primitive.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

import pytest

from tests.conftest import ARABIC_Q
from translation_pipeline import write_helper
from translation_pipeline.selectors import SAVE_BUTTON_SELECTOR, Field, TargetField
from translation_pipeline.write_helper import (
    SaveOutcome,
    fill_translation,
    read_field_value,
    save_page,
)

# --- fill_translation ------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "index", "css"),
    [
        (TargetField.UQ, 0, 'input[name="UQ0"]'),
        (TargetField.UA, 5, 'input[name="UA5"]'),
    ],
)
def test_fill_translation_sets_value_in_frame_by_index(
    mock_page: MagicMock, field: TargetField, index: int, css: str
) -> None:
    frame = MagicMock()
    mock_page.frame_locator.return_value = frame

    fill_translation(mock_page, index, field, ARABIC_Q)

    # Frame-scoped (the grid is in #LFrm), addressed by name, never page.fill
    # (the cells are hidden) — set .value + fire input/change via evaluate.
    mock_page.frame_locator.assert_called_once_with("#LFrm")
    frame.locator.assert_called_once_with(css)
    frame.locator.return_value.evaluate.assert_called_once_with(
        write_helper._SET_VALUE_JS, ARABIC_Q
    )
    mock_page.fill.assert_not_called()


@pytest.mark.parametrize("field", [Field.TQ, Field.TA, Field.UQ, Field.UA])
def test_fill_translation_rejects_non_targetfield(mock_page: MagicMock, field: Field) -> None:
    # English source (TQ/TA) AND even Field.UQ/UA (independent enum, not a
    # TargetField) are rejected: callers MUST pass a TargetField.
    with pytest.raises(ValueError):
        fill_translation(mock_page, 0, field, "x")  # type: ignore[arg-type]
    mock_page.frame_locator.assert_not_called()


def test_fill_translation_rejects_negative_index(mock_page: MagicMock) -> None:
    with pytest.raises(ValueError):
        fill_translation(mock_page, -1, TargetField.UQ, "x")
    mock_page.frame_locator.assert_not_called()


# --- read_field_value ------------------------------------------------------


def test_read_field_value_returns_live_value(mock_page: MagicMock) -> None:
    frame = MagicMock()
    mock_page.frame_locator.return_value = frame
    frame.locator.return_value.input_value.return_value = "موجود"

    assert read_field_value(mock_page, 2, Field.UA) == "موجود"

    mock_page.frame_locator.assert_called_once_with("#LFrm")
    frame.locator.assert_called_once_with('input[name="UA2"]')


# --- save_page classification matrix ---------------------------------------


def test_save_page_persisted(
    mock_page: MagicMock,
    wire_save_response: Callable[..., Any],
    make_save_response: Callable[..., Any],
) -> None:
    frame = MagicMock()
    mock_page.frame_locator.return_value = frame
    wire_save_response(make_save_response(body=["", True]))

    result = save_page(mock_page)

    assert result.outcome is SaveOutcome.PERSISTED
    assert result.http_status == 200
    # Save is clicked in-frame (#saveAll lives in #LFrm), never on the page.
    mock_page.frame_locator.assert_called_once_with("#LFrm")
    frame.locator.assert_called_once_with(SAVE_BUTTON_SELECTOR)
    frame.locator.return_value.click.assert_called_once()
    mock_page.click.assert_not_called()


def test_save_page_rejected(
    mock_page: MagicMock,
    wire_save_response: Callable[..., Any],
    make_save_response: Callable[..., Any],
) -> None:
    wire_save_response(make_save_response(body=["", False]))
    result = save_page(mock_page)
    assert result.outcome is SaveOutcome.REJECTED


@pytest.mark.parametrize("status", [500, 502, 503])
def test_save_page_server_error_on_5xx(
    mock_page: MagicMock,
    wire_save_response: Callable[..., Any],
    make_save_response: Callable[..., Any],
    status: int,
) -> None:
    wire_save_response(make_save_response(status=status, body=["", True]))
    result = save_page(mock_page)
    assert result.outcome is SaveOutcome.SERVER_ERROR
    assert result.http_status == status


def test_save_page_server_error_on_timeout(
    mock_page: MagicMock, wire_save_response: Callable[..., Any]
) -> None:
    wire_save_response(raise_timeout=True)
    result = save_page(mock_page)
    assert result.outcome is SaveOutcome.SERVER_ERROR
    assert result.http_status is None


def test_save_page_server_error_on_unparseable_body(
    mock_page: MagicMock,
    wire_save_response: Callable[..., Any],
    make_save_response: Callable[..., Any],
) -> None:
    wire_save_response(make_save_response(raw="<html>not json</html>"))
    result = save_page(mock_page)
    assert result.outcome is SaveOutcome.SERVER_ERROR
    assert result.raw_body == "<html>not json</html>"


def test_save_page_server_error_on_unexpected_body(
    mock_page: MagicMock,
    wire_save_response: Callable[..., Any],
    make_save_response: Callable[..., Any],
) -> None:
    wire_save_response(make_save_response(body=["unexpected", True]))
    result = save_page(mock_page)
    assert result.outcome is SaveOutcome.SERVER_ERROR
    assert result.raw_body == '["unexpected", true]'


def test_is_save_response_matches_cross_origin_post(
    make_save_response: Callable[..., Any],
) -> None:
    save_resp = make_save_response(body=["", True])
    other = make_save_response(body=["", True], url="https://myquds.ibnbadis.org/x.php")
    assert write_helper._is_save_response(save_resp) is True
    assert write_helper._is_save_response(other) is False


def test_save_page_never_inspects_button_colour(
    mock_page: MagicMock,
    wire_save_response: Callable[..., Any],
    make_save_response: Callable[..., Any],
) -> None:
    """Codifies the CSTC-4 divergence: success is keyed off the response body,
    never the fleeting green Save-button flash.

    Behavioural (not a brittle source scan — the docstring legitimately
    documents the divergence): save_page must not read any element
    style/colour/DOM state; it only clicks Save and reads the intercepted
    response body.
    """
    wire_save_response(make_save_response(body=["", True]))
    save_page(mock_page)
    mock_page.get_attribute.assert_not_called()
    mock_page.evaluate.assert_not_called()
    mock_page.eval_on_selector.assert_not_called()
    mock_page.query_selector.assert_not_called()
    mock_page.wait_for_selector.assert_not_called()
