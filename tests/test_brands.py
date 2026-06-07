"""Tests for deterministic brand extraction from product titles."""

from __future__ import annotations

import pytest

from app.brands import extract_brand, extract_model


@pytest.mark.parametrize(("title", "expected"), [
    ("Ninja Foodi 6-in-1 Indoor Grill and Air Fryer EG201", "EG201"),
    ('Samsung 65" Class QN65Q80D QLED 4K TV', "QN65Q80D"),
    ("Ninja DoubleStack XL 2 Basket Air Fryer", ""),     # no real model code
    ("Apple MacBook Pro 14", ""),                         # '14' alone isn't a model
    ("VIZIO D Series 4K HDR Smart TV", ""),               # HDR/4K excluded
])
def test_extract_model(title, expected):
    assert extract_model(title) == expected


@pytest.mark.parametrize(("title", "expected"), [
    ("Dell 15 Laptop - w/ Windows 11 OS", "Dell"),
    ("Lenovo IdeaPad Slim 3 Laptop", "Lenovo"),
    ("ASUS ROG Zephyrus G16 Laptop", "ASUS"),            # ALLCAPS preserved
    ('HP 14" HD Windows Laptop', "HP"),
    ("65 inch Insignia Class F50 4K TV", "Insignia"),    # skips "65"/"inch"
    ("Ninja 4-in-1 Air Fryer Pro", "Ninja"),
    ("Instant Pot Duo 7-in-1", "Instant Pot"),           # multi-word known brand
    ("VIZIO D Series Smart TV", "VIZIO"),
    ("Apple MacBook Pro 14", "Apple"),
])
def test_extract_brand_known_and_fallback(title, expected):
    assert extract_brand(title) == expected


def test_extract_brand_empty_uses_fallback():
    assert extract_brand("") == "Unknown"
    assert extract_brand("", fallback="—") == "—"


def test_extract_brand_capitalizes_unknown_first_token():
    # Not a known brand -> first meaningful token, title-cased.
    assert extract_brand("zorblax mega blender") == "Zorblax"
