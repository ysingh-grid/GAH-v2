"""Unit tests for the primitives data-access layer (backend/primitives/store.py)."""

import pytest

from backend.primitives_read import store


def test_load_all_primitives_returns_full_catalog():
    catalog = store.load_all_primitives()
    assert isinstance(catalog, dict)
    assert len(catalog) == 20
    assert "box" in catalog


def test_get_primitive_with_known_key_returns_spec():
    spec = store.get_primitive("box")
    assert spec["name"] == "box"
    assert "template" in spec
    assert "parameters" in spec


def test_get_primitive_with_unknown_key_raises_keyerror():
    with pytest.raises(KeyError):
        store.get_primitive("banana")
