"""Contract tests for delegate_features (Task 7) — no live RLM.

We inject fake llm_query / batch_llm_query into the pull_tools module globals
(the same names fast-rlm injects into the REPL at runtime) and drive the async
tool directly, asserting the shared-frame + per-body contract and that the
flattened result coerces to one legal base + unions.
"""

from __future__ import annotations

import asyncio

import rlm.pull_tools as pt
from runtime.schema import Operation, plan_from_dict


def _body_step(name: str) -> dict:
    return {
        "id": name,
        "primitive": "box",
        "operation": "base",
        "parameters": {"length": 10.0, "width": 10.0, "height": 10.0},
    }


def test_delegate_features_does_not_offer_preview_to_children(monkeypatch):
    captured: list[dict] = []

    def fake_llm_query(ctx, schema, tools=None):
        captured.append({"ctx": ctx, "tools": tools})
        return len(captured) - 1  # a handle the fake batch can map back

    async def fake_batch(*queries):
        return [[_body_step(captured[i]["ctx"]["feature"]["name"])] for i in queries]

    monkeypatch.setattr(pt, "llm_query", fake_llm_query, raising=False)
    monkeypatch.setattr(pt, "batch_llm_query", fake_batch, raising=False)

    features = [
        {"name": "leaf_a", "operation": "base"},
        {"name": "leaf_b", "operation": "union"},
        {"name": "pin", "operation": "union"},
    ]
    shared_frame = {"leaf_thickness": 4.0, "pin_radius": 2.5}

    bodies = asyncio.run(pt.delegate_features(features, shared_frame))

    # one child per body, in order
    assert len(bodies) == 3
    assert [c["ctx"]["feature"]["name"] for c in captured] == ["leaf_a", "leaf_b", "pin"]
    # every child sees the SAME shared frame (alignment contract)
    assert all(c["ctx"]["shared_frame"] == shared_frame for c in captured)
    # children get read tools but NOT preview_plan — preview is ROOT-only (giving
    # it to children caused runaway latency: they burned turns previewing dummies)
    assert pt.preview_plan not in captured[0]["tools"]
    assert pt.lookup_primitive in captured[0]["tools"]
    # the child task tells them to build a VALID standalone plan (first step base)
    assert "base" in captured[0]["ctx"]["task"]


def test_flattened_bodies_coerce_to_one_base_plus_unions(monkeypatch):
    def fake_llm_query(ctx, schema, tools=None):
        return ctx["feature"]["name"]

    async def fake_batch(*queries):
        return [[_body_step(name)] for name in queries]

    monkeypatch.setattr(pt, "llm_query", fake_llm_query, raising=False)
    monkeypatch.setattr(pt, "batch_llm_query", fake_batch, raising=False)

    bodies = asyncio.run(
        pt.delegate_features(
            [{"name": "a", "operation": "base"}, {"name": "b", "operation": "union"}],
            {},
        )
    )
    # flatten (each body starts with its own 'base') -> schema folds extra bases to union
    plan = plan_from_dict(
        {"part_name": "asm", "steps": [s for body in bodies for s in body]}
    )
    ops = [s.operation for s in plan.steps]
    assert ops == [Operation.base, Operation.union]
