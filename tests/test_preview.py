"""Tests for the preview service (Task 5): script builder, evidence, endpoint, tool."""

from __future__ import annotations

from runtime.preview import _perstep_specs, build_preview_script
from runtime.schema import load_library, plan_from_dict

_CUBE = {
    "part_name": "cube",
    "steps": [
        {"id": "body", "primitive": "box", "operation": "base",
         "parameters": {"length": 40.0, "width": 40.0, "height": 40.0}}
    ],
}

# base box + a second box placed far away → two disconnected components
_DISJOINT = {
    "part_name": "two_boxes",
    "steps": [
        {"id": "a", "primitive": "box", "operation": "base",
         "parameters": {"length": 10.0, "width": 10.0, "height": 10.0},
         "position": [0.0, 0.0, 0.0]},
        {"id": "b", "primitive": "box", "operation": "union",
         "parameters": {"length": 10.0, "width": 10.0, "height": 10.0},
         "position": [100.0, 0.0, 0.0]},
    ],
}


# ── pure: script builder ─────────────────────────────────────────────────────


def test_perstep_specs_maps_only_primitive_steps():
    plan = plan_from_dict(
        {
            "part_name": "p",
            "steps": [
                {"id": "body", "primitive": "box", "operation": "base"},
                {"id": "hole", "primitive": "cylinder", "operation": "cut"},
                {"id": "f1", "op": "fillet", "selector": "|Z", "value": 1.0},
            ],
        }
    )
    specs = _perstep_specs(plan)
    assert specs == [("s0", "body", "base", "box"), ("s1", "hole", "cut", "cylinder")]


def test_build_preview_script_wraps_body_and_lists_steps():
    plan = plan_from_dict(_CUBE)
    script = build_preview_script(plan, load_library(), "out.stl", "out.step")
    assert "_out = {'success': True}" in script
    assert "per_feature" in script
    assert '("body", "base", "box"' in script  # the step tuple is embedded
    assert "print(_json.dumps(_out))" in script


# ── integration: real geometry (cadquery installed in this venv) ─────────────


def test_preview_plan_on_cube_is_watertight_single_component(tmp_path):
    from backend.preview.store import preview_plan

    ev = preview_plan(_CUBE, run_id="test_preview_cube")
    assert ev["compiles"] is True
    assert ev["executes"] is True
    assert ev["watertight"] is True
    assert ev["num_components"] == 1
    assert ev["disconnected"] is False
    # the base feature's real size is ~40mm on each axis
    body = next(f for f in ev["per_feature"] if f["id"] == "body")
    assert all(abs(d - 40.0) < 1.0 for d in body["size_mm"])
    assert body["pct_of_overall_bbox"] == 100.0  # single feature fills the bbox


def test_preview_plan_flags_disconnected_components():
    from backend.preview.store import preview_plan

    ev = preview_plan(_DISJOINT, run_id="test_preview_disjoint")
    assert ev["executes"] is True
    assert ev["num_components"] == 2
    assert ev["disconnected"] is True
    assert "disconnected_hint" in ev
    assert "overlap" in ev["disconnected_hint"].lower()


def test_preview_plan_rejects_invalid_plan():
    from backend.preview.store import preview_plan

    ev = preview_plan({"part_name": "x", "steps": [
        {"id": "a", "primitive": "box", "operation": "union"}  # no base → invalid
    ]})
    assert ev["compiles"] is False
    assert "did not validate" in ev["error"]


_L_BRACKET = {
    "part_name": "l_bracket",
    "steps": [
        {
            "id": "body",
            "primitive": "profile_extrude",
            "operation": "base",
            "parameters": {
                "profile": [[0, 0], [80, 0], [80, 10], [10, 10], [10, 60], [0, 60]],
                "height": 5.0,
            },
        }
    ],
}


def test_preview_plan_on_profile_extrude_l_bracket_is_valid():
    """Representation (Task 8): a non-boxy L silhouette via profile_extrude builds
    ONE watertight solid — no need to fake it by stacking boxes."""
    from backend.preview.store import preview_plan

    ev = preview_plan(_L_BRACKET, run_id="test_preview_lbracket")
    assert ev["compiles"] is True
    assert ev["executes"] is True
    assert ev["watertight"] is True
    assert ev["num_components"] == 1


def test_preview_plan_on_rect_to_round_is_valid():
    """Representation (loft primitive): a rectangle->round duct adapter builds ONE
    watertight solid — previously impossible (pyramid collapsed it to a spike)."""
    from backend.preview.store import preview_plan

    plan = {
        "part_name": "duct_adapter",
        "steps": [
            {
                "id": "body",
                "primitive": "rect_to_round",
                "operation": "base",
                "parameters": {
                    "base_length": 70.0, "base_width": 50.0,
                    "top_diameter": 30.0, "height": 50.0,
                },
            }
        ],
    }
    ev = preview_plan(plan, run_id="test_preview_rect_to_round")
    assert ev["compiles"] is True
    assert ev["executes"] is True
    assert ev["watertight"] is True
    assert ev["num_components"] == 1


# ── endpoint wiring ──────────────────────────────────────────────────────────


def test_preview_endpoint_returns_evidence():
    from starlette.testclient import TestClient

    from backend.app import create_app

    client = TestClient(create_app())
    resp = client.post(
        "/internal/preview-plan", json={"plan": _CUBE, "critique": False}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["compiles"] is True
    assert body["num_components"] == 1


# ── pull tool round-trip (stubbed backend) ───────────────────────────────────


def test_preview_plan_tool_posts_plan_to_backend(monkeypatch):
    import rlm.pull_tools as pt

    # The tool keeps a per-run counter in module globals — reset it per test.
    monkeypatch.setattr(pt, "_PREVIEW_CALLS", 0, raising=False)

    captured: dict = {}

    class _FakeResp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"compiles": True, "num_components": 1}

    def _fake_post(url, json, timeout):  # noqa: ANN001, A002
        captured["url"] = url
        captured["json"] = json
        return _FakeResp()

    monkeypatch.setenv("DTCM_BACKEND_URL", "http://backend:8001")
    monkeypatch.setattr("requests.post", _fake_post)

    out = pt.preview_plan(_CUBE, critique=False)
    assert out["compiles"] is True
    assert captured["url"].endswith("/internal/preview-plan")
    assert captured["json"]["plan"]["part_name"] == "cube"
    assert captured["json"]["critique"] is False


def test_preview_plan_tool_hard_caps_after_budget(monkeypatch):
    """The 3rd preview (budget=2) is refused in code — no HTTP call — so the model
    can never run preview away regardless of what its prompt does."""
    import rlm.pull_tools as pt

    monkeypatch.setattr(pt, "_PREVIEW_CALLS", 0, raising=False)
    monkeypatch.setenv("DTCM_BACKEND_URL", "http://backend:8001")
    monkeypatch.setenv("DTCM_PREVIEW_BUDGET", "2")

    calls = {"n": 0}

    class _FakeResp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"compiles": True}

    def _fake_post(url, json, timeout):  # noqa: ANN001, A002
        calls["n"] += 1
        return _FakeResp()

    monkeypatch.setattr("requests.post", _fake_post)

    assert pt.preview_plan(_CUBE).get("compiles") is True          # 1
    assert pt.preview_plan(_CUBE).get("compiles") is True          # 2
    refused = pt.preview_plan(_CUBE)                                 # 3 -> refused
    assert refused.get("budget_exhausted") is True
    assert "FINAL" in refused.get("message", "")
    assert calls["n"] == 2  # the 3rd never reached the backend
