"""Tests for runtime/planner.py — typed output contract + pure helpers.

The live RLM turn is gated behind RUN_RLM_LIVE (needs deno + network + spend).
"""

import os

import pytest
from pydantic import ValidationError

from runtime.planner import (
    build_planner_query,
    parse_planner_result,
    run_planner_turn,
)
from runtime.schema import PrimitivePlan

_CUBE_PLAN = {
    "part_name": "cube",
    "steps": [
        {
            "id": "body",
            "primitive": "box",
            "operation": "base",
            "parameters": {"length": 60.0, "width": 60.0, "height": 60.0},
        }
    ],
}


# ── output contract ──────────────────────────────────────────────────────────


def test_plan_result_carries_validated_plan():
    out = parse_planner_result(_CUBE_PLAN)
    assert out.part_name == "cube"
    assert out.steps[0].primitive == "box"


def test_parse_planner_result_accepts_already_validated_model():
    expected = PrimitivePlan.model_validate(_CUBE_PLAN)
    out = parse_planner_result(expected)
    assert out.part_name == expected.part_name
    assert len(out.steps) == len(expected.steps)


def test_plan_with_no_steps_raises():
    with pytest.raises(ValidationError):
        parse_planner_result({"part_name": "x", "steps": []})


def test_plan_with_two_base_steps_coerced():
    bad = {
        "part_name": "x",
        "steps": [
            {"id": "a", "primitive": "box", "operation": "base"},
            {"id": "b", "primitive": "box", "operation": "base"},
        ],
    }
    res = parse_planner_result(bad)
    assert res.steps[0].operation == "base"
    assert res.steps[1].operation == "union"


def test_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        parse_planner_result({**_CUBE_PLAN, "bogus": 1})


# ── query assembly ───────────────────────────────────────────────────────────


def test_build_planner_query_shape():
    from runtime.planner import PLANNER_TASK

    q = build_planner_query("make a 60mm cube", [{"role": "user", "content": "hi"}])
    assert q["original_prompt"] == "make a 60mm cube"
    assert q["chat_history"][0]["content"] == "hi"
    # task is the planner's standing instruction — NOT a duplicate of the user
    # prompt (the old byte-for-byte duplication was wasted context every REPL step).
    assert q["task"] == PLANNER_TASK
    assert q["task"] != q["original_prompt"]


def test_build_planner_query_forwards_both_menus():
    """Regression guard: pre-injected rich primitive schemas land in the query dict."""
    q = build_planner_query(
        "make a cube", [],
        available_primitives={"box": "A 3D box"},
    )
    assert q["available_primitives"] == {"box": "A 3D box"}


def test_run_planner_turn_uses_typed_output_schema(monkeypatch):
    import fast_rlm

    captured = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return {"results": _CUBE_PLAN}

    monkeypatch.setattr(fast_rlm, "run", fake_run)
    monkeypatch.setattr(
        "runtime.planner._load_available_primitives", lambda: {"box": "A 3D box"}
    )

    out = run_planner_turn(
        "make a 60mm cube",
        [{"role": "user", "content": "make a 60mm cube"}],
        backend_url="http://backend.test",
        config={},
    )

    from runtime.schema import LibraryBoundPrimitivePlan

    assert out.part_name == "cube"
    assert captured["output_schema"] is LibraryBoundPrimitivePlan
    assert captured["env_variables"]["DTCM_BACKEND_URL"] == "http://backend.test"


def test_run_replanner_turn_preinjects_primitive_menu(monkeypatch):
    """The replanner gets the same measured pre-inject win as the planner, but
    MINIMAL: only available_primitives (needed to swap/fix a primitive) — no
    kb_index (a replan edits an existing plan; the KB menu stays pull-only)."""
    import fast_rlm

    from runtime.planner import run_replanner_turn

    captured = {}

    def fake_run(query, **kwargs):
        captured["query"] = query
        captured.update(kwargs)
        return {"results": _CUBE_PLAN}

    monkeypatch.setattr(fast_rlm, "run", fake_run)
    monkeypatch.setattr(
        "runtime.planner._load_available_primitives",
        lambda: {"box": "A box", "cylinder": "A cylinder"},
    )

    out = run_replanner_turn(
        "make a 60mm cube",
        [{"role": "system", "content": "fix it"}],
        backend_url="http://backend.test",
        config={},
    )

    assert out.part_name == "cube"
    assert captured["query"]["available_primitives"] == {"box": "A box", "cylinder": "A cylinder"}
    assert "kb_index" not in captured["query"]
    from runtime.schema import LibraryBoundPrimitivePlan

    assert captured["output_schema"] is LibraryBoundPrimitivePlan


def test_run_replanner_turn_injects_current_plan_into_query(monkeypatch):
    """The current plan is handed to the replanner as context['current_plan'] (a dict),
    so it never re-parses the plan from chat text."""
    import fast_rlm

    from runtime.planner import run_replanner_turn

    captured = {}

    def fake_run(query, **kwargs):
        captured["query"] = query
        return {"results": _CUBE_PLAN}

    monkeypatch.setattr(fast_rlm, "run", fake_run)
    monkeypatch.setattr(
        "runtime.planner._load_available_primitives", lambda: {"box": "A box"}
    )

    run_replanner_turn(
        "make a 60mm cube",
        [{"role": "system", "content": "fix it"}],
        backend_url="http://backend.test",
        config={},
        current_plan=_CUBE_PLAN,
    )
    assert captured["query"]["current_plan"] == _CUBE_PLAN

    # omitted when not provided
    captured.clear()
    run_replanner_turn(
        "make a 60mm cube",
        [{"role": "system", "content": "fix it"}],
        backend_url="http://backend.test",
        config={},
    )
    assert "current_plan" not in captured["query"]


def test_all_skills_fit_in_one_repl_output():
    """Every skill must fit under truncate_len or the engine truncates it on
    delivery and the model burns extra REPL steps paginating (the exact problem
    truncate_len was raised to eliminate — playbook.md regressed past the old
    8000 cap silently)."""
    from pathlib import Path

    from rlm.rlm_config import config

    skills_dir = Path(__file__).resolve().parent.parent / "skills"
    for md in sorted(skills_dir.glob("*.md")):
        size = len(md.read_text(encoding="utf-8"))
        assert size < config.truncate_len, (
            f"{md.name} is {size} chars >= truncate_len={config.truncate_len}; "
            "raise truncate_len in rlm/rlm_config.py or trim the skill"
        )


def test_replanner_task_teaches_cause_classes_not_product_recipes():
    """Topology fails must use geometric CAUSE classes, not vessel folklore."""
    from runtime.planner import REPLANNER_TASK

    low = REPLANNER_TASK.lower()
    assert "cut_sever" in low
    assert "union_gap" in low
    assert "shell_fail" in low
    assert "final" in low


def test_run_replanner_turn_escalates_reasoning_vs_first_pass(monkeypatch):
    """First-pass planning stays cheap ('low'); the rare failure/edit replan
    escalates reasoning so the model can reason about a construction change."""
    import fast_rlm

    from rlm.rlm_config import LLM_KWARGS
    from runtime.planner import run_replanner_turn

    captured = {}

    def fake_run(query, **kwargs):
        captured["llm_kwargs"] = kwargs.get("llm_kwargs", {})
        return {"results": _CUBE_PLAN}

    monkeypatch.setattr(fast_rlm, "run", fake_run)
    monkeypatch.setattr(
        "runtime.planner._load_available_primitives", lambda: {"box": "A box"}
    )

    run_replanner_turn(
        "fix it",
        [{"role": "system", "content": "failed at step 'x'"}],
        backend_url="http://backend.test",
        config={},
    )
    # first-pass baseline stays low; the replan path escalated to medium
    assert LLM_KWARGS.get("reasoning_effort") == "low"
    assert captured["llm_kwargs"].get("reasoning_effort") == "medium"


def test_repair_guidance_does_not_misattribute_brep_to_disjoint_unions():
    """The BRep_API build failure must point to the ATTRIBUTED op + preview_plan,
    not the old misleading 'disjoint unions' diagnosis that sent shell fixes astray."""
    from pathlib import Path

    text = (
        Path(__file__).resolve().parent.parent / "skills" / "repair_guidance.md"
    ).read_text(encoding="utf-8")
    assert "disjoint unions" not in text.lower()
    assert "preview_plan" in text
    assert "attributed" in text.lower()


def test_planner_toolset_is_single_object():
    """Single-object platform: the multi-body assembly fork tools must NOT be in
    the planner or replanner toolsets (delegate_features invited disconnected
    bodies; delegate_stage was measured harmful)."""
    from rlm.pull_tools import delegate_features, delegate_stage
    from runtime.planner import _PLANNER_TOOLS, _REPLANNER_TOOLS

    for tool in (delegate_features, delegate_stage):
        assert tool not in _PLANNER_TOOLS, f"{tool.__name__} must not be in _PLANNER_TOOLS"
        assert tool not in _REPLANNER_TOOLS, f"{tool.__name__} must not be in _REPLANNER_TOOLS"


def test_planner_task_prefers_single_block_and_library_params():
    """Fast general planning: few turns + exact param names from menu."""
    from runtime.planner import PLANNER_TASK

    low = PLANNER_TASK.lower()
    assert "available_primitives" in low or "param" in low
    assert "final" in low
    assert "single" in low or "one" in low or "1–2" in low or "2 turn" in low


def test_primitive_planning_teaches_revolve_for_turned_vessels():
    """A bottle/cup/vase must be modeled as ONE revolve of a walled profile —
    NOT cylinders + shell + a unioned cap (the _ed2b non-fusing anti-pattern)."""
    from pathlib import Path

    skill = (
        Path(__file__).resolve().parent.parent / "skills" / "primitive_planning.md"
    ).read_text(encoding="utf-8")
    low = skill.lower()
    assert "turned vessels" in low
    assert "revolve" in skill
    for w in ("bottle", "cup", "vase"):
        assert w in low, f"vessel skill should mention {w}"
    # the explicit anti-pattern must be named
    assert "shelled" in low
    assert "cap" in low


def test_primitive_planning_teaches_hollow_last():
    """When CSG + shell are unavoidable: union all solids FIRST, shell LAST —
    never union a solid onto an already-shelled thin wall."""
    from pathlib import Path

    skill = (
        Path(__file__).resolve().parent.parent / "skills" / "primitive_planning.md"
    ).read_text(encoding="utf-8")
    low = skill.lower()
    assert "hollow last" in low
    assert "union all solid features first" in low


def test_primitive_planning_skill_teaches_selection_principle():
    """The skill must steer toward the richest single primitive and away from
    fragile post-hoc finishes — naming the robust primitives explicitly."""
    from pathlib import Path

    skill = (
        Path(__file__).resolve().parent.parent / "skills" / "primitive_planning.md"
    ).read_text(encoding="utf-8")
    low = skill.lower()
    # the principle is stated
    assert "richest" in low or "single richest primitive" in low
    # the robust construction primitives are named
    for name in ("hollow_cylinder", "revolve", "filleted_box"):
        assert name in skill, f"skill should name {name}"
    # fragile finishes are framed as a fallback/last resort
    assert "last resort" in low or "fall back" in low or "fallback" in low


def test_run_planner_turn_propagates_exception(monkeypatch):
    """No ask_user fallback — an unrecoverable RLM failure must raise, not be masked."""
    import fast_rlm

    def fake_run(*args, **kwargs):
        raise RuntimeError("budget exhausted")

    monkeypatch.setattr(fast_rlm, "run", fake_run)
    # NOTE: run_planner_turn no longer calls list_primitives/list_kb_index — it
    # preloads the Rich Menu from the filesystem (_load_available_primitives) and
    # fast_rlm.run raises before any REPL tool runs, so no tool patching is needed.

    with pytest.raises(RuntimeError, match="budget exhausted"):
        run_planner_turn(
            "make a 60mm cube", [], backend_url="http://backend.test", config={}
        )


# ── live turn (opt-in) ───────────────────────────────────────────────────────


@pytest.mark.skipif(
    not os.getenv("RUN_RLM_LIVE"), reason="set RUN_RLM_LIVE=1 to run a real RLM turn"
)
def test_live_planner_turn_returns_typed_output():
    backend_url = os.getenv("DTCM_BACKEND_URL", "http://127.0.0.1:8001")
    out = run_planner_turn(
        "Design a 60mm x 60mm x 60mm solid cube.",
        chat_history=[],
        backend_url=backend_url,
    )
    assert out.part_name
