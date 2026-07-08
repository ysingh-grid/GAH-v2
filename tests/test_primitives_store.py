"""Unit tests for the primitives data-access layer (backend/primitives/store.py)."""

import pytest

from backend.primitives_read import store


def test_load_all_primitives_returns_full_catalog():
    catalog = store.load_all_primitives()
    assert isinstance(catalog, dict)
    assert len(catalog) == 22  # 20 base primitives + rect_to_round + rect_to_rect
    assert "box" in catalog
    assert "rect_to_round" in catalog  # loft-transition primitives (duct adapters)
    assert "rect_to_rect" in catalog


def test_get_primitive_with_known_key_returns_spec():
    spec = store.get_primitive("box")
    assert spec["name"] == "box"
    assert "template" in spec
    assert "parameters" in spec


def test_get_primitive_with_unknown_key_raises_keyerror():
    with pytest.raises(KeyError):
        store.get_primitive("banana")
