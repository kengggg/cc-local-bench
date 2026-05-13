"""Tests for format_phone_number. All six must pass — no edits to this file."""
import pytest

from phone_utils import format_phone_number

CANONICAL = "+66-812-345-678"


def test_national_format_with_leading_zero():
    """Standard Thai national format: 10 digits starting with 0."""
    assert format_phone_number("0812345678") == CANONICAL


def test_international_with_plus():
    """Already-international format with leading '+'."""
    assert format_phone_number("+66812345678") == CANONICAL


def test_international_without_plus():
    """Bare digits, country code present."""
    assert format_phone_number("66812345678") == CANONICAL


def test_with_dashes():
    """Common written form with dashes between groups."""
    assert format_phone_number("081-234-5678") == CANONICAL


def test_with_mixed_separators():
    """Robust to parens, dots, and spaces mixed together."""
    assert format_phone_number("(081) 234.5678") == CANONICAL


def test_invalid_input_raises():
    """Letters or wrong digit-count must raise ValueError, not return junk."""
    with pytest.raises(ValueError):
        format_phone_number("not-a-phone-number")
    with pytest.raises(ValueError):
        format_phone_number("12345")  # too short
