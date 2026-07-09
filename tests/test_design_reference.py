"""Design-reference index/fetch, including the merged approved-designs store."""

from __future__ import annotations

import pytest

from backend.approved_store import store as astore
from backend.design_reference import store as dref


@pytest.fixture(autouse=True)
def _tmp_approved(tmp_path, monkeypatch):
    monkeypatch.setattr(astore, "_APPROVED_PATH", tmp_path / "approved_designs.json")


def test_index_merges_recipes_fastener_and_approved():
    astore.append_approved(
        run_id="run_1", original_prompt="a hollow vase", plan={"part_name": "vase", "steps": [{"id": "b"}]}
    )
    idx = dref.index_reference()
    assert "bolt_circle" in idx           # a curated recipe key
    assert "fastener_dims" in idx         # the dimension tables key
    assert "approved__run_1" in idx       # the merged approved design
    assert idx["approved__run_1"] == "a hollow vase"


def test_fetch_returns_only_requested_across_sources():
    astore.append_approved(
        run_id="run_1", original_prompt="a hollow vase",
        plan={"part_name": "vase", "steps": [{"id": "b", "primitive": "revolve"}]},
    )
    out = dref.fetch_reference(["bolt_circle", "fastener_dims", "approved__run_1", "nope"])
    assert set(out) == {"bolt_circle", "fastener_dims", "approved__run_1"}
    assert "steps" in out["bolt_circle"]                       # curated recipe
    assert out["approved__run_1"]["steps"][0]["primitive"] == "revolve"  # approved design


def test_index_survives_missing_approved_store():
    # No approvals written → index is just recipes + fastener_dims, never raises.
    idx = dref.index_reference()
    assert "fastener_dims" in idx
    assert not any(k.startswith("approved__") for k in idx)
