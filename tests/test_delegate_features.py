"""Minimal guard for the ISOLATED delegate_features def.

delegate_features is NOT in any toolset — the platform is single-object and
multi-body assembly is out of scope (that absence is asserted by
tests/test_planner.py::test_planner_toolset_is_single_object). The def is kept
in rlm/pull_tools.py for reference only; this test just pins its mechanics so a
future reader knows what it did, and confirms children never get preview_plan.
"""

from __future__ import annotations

import asyncio

import rlm.pull_tools as pt


def _body_step(name: str) -> dict:
    return {
        "id": name,
        "primitive": "box",
        "operation": "base",
        "parameters": {"length": 10.0, "width": 10.0, "height": 10.0},
    }


def test_isolated_delegate_features_children_never_get_preview(monkeypatch):
    captured: list[dict] = []

    def fake_llm_query(ctx, schema, tools=None):
        captured.append({"ctx": ctx, "tools": tools})
        return len(captured) - 1

    async def fake_batch(*queries):
        return [[_body_step(captured[i]["ctx"]["feature"]["name"])] for i in queries]

    monkeypatch.setattr(pt, "llm_query", fake_llm_query, raising=False)
    monkeypatch.setattr(pt, "batch_llm_query", fake_batch, raising=False)

    bodies = asyncio.run(
        pt.delegate_features([{"name": "leaf_a", "operation": "base"}], {"t": 4.0})
    )

    assert len(bodies) == 1
    # children get read tools but NEVER preview_plan (host-geometry runaway guard)
    assert pt.preview_plan not in captured[0]["tools"]
    assert pt.lookup_primitive in captured[0]["tools"]
