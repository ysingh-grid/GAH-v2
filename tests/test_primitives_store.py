"""Unit tests for the primitives data-access layer (backend/primitives/store.py)."""

import pytest

from backend.primitives_read import store


def test_load_all_primitives_returns_full_catalog():
    catalog = store.load_all_primitives()
    assert isinstance(catalog, dict)
    assert len(catalog) == 36
    assert "box" in catalog


def test_get_primitive_with_known_key_returns_spec():
    spec = store.get_primitive("box")
    assert spec["name"] == "box"
    assert "template" in spec
    assert "parameters" in spec


def test_get_primitive_with_unknown_key_raises_keyerror():
    with pytest.raises(KeyError):
        store.get_primitive("banana")


def test_all_templates_compile_and_execute_in_cadquery():
    import shutil
    import uuid
    from tools.execute_cadquery import execute_cadquery
    from tools.artifacts import run_dir

    catalog = store.load_all_primitives()
    run_id = f"test_run_{uuid.uuid4().hex[:8]}"

    try:
        for key, spec in catalog.items():
            template = spec["template"]
            params = {k: v["default"] for k, v in spec["parameters"].items()}
            formatted_code = template.format(**params)
            code = f"import cadquery as cq\nresult = {formatted_code}"
            
            res = execute_cadquery(code, run_id)
            assert res.get("success") is True, f"Failed to execute primitive '{key}': {res.get('error')}"
            assert res.get("volume") is not None and res.get("volume") > 0.0, f"Primitive '{key}' has invalid volume: {res.get('volume')}"
    finally:
        d = run_dir(run_id)
        if d.exists():
            shutil.rmtree(d)
