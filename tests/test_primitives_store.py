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


def test_every_primitive_has_a_nonempty_description():
    """The Rich Menu is built from these descriptions — none may be blank."""
    catalog = store.load_all_primitives()
    for key, spec in catalog.items():
        desc = str(spec.get("description", "")).strip()
        assert desc, f"primitive {key!r} has an empty description"


def test_capability_forward_descriptions_advertise_ideal_use():
    """The unused-but-robust primitives must advertise WHEN to use them so the
    planner reaches for them instead of crude box/cylinder + a fragile finish."""
    catalog = store.load_all_primitives()

    hollow_cyl = catalog["hollow_cylinder"]["description"].lower()
    assert any(w in hollow_cyl for w in ("tube", "cup", "bottle", "hollow"))

    revolve = catalog["revolve"]["description"].lower()
    assert any(w in revolve for w in ("bottle", "revolution", "turned", "vase"))

    # Pre-finished primitives must steer AWAY from a whole-body fillet/shell finish.
    filleted = catalog["filleted_box"]["description"].lower()
    assert "instead of" in filleted or "pre-" in filleted
    hollow_box = catalog["hollow_box"]["description"].lower()
    assert "instead of" in hollow_box or "one step" in hollow_box or "one-step" in hollow_box
