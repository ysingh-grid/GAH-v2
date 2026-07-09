"""Unit tests for runtime/replan.py — caps, stage->skill, feedback, re-entry."""

from runtime.replan import (
    INNER_CAP,
    OUTER_CAP,
    SHELL_FAIL_REWRITE,
    STAGE_TO_SKILL,
    build_edit_message,
    build_feedback_message,
    cap_for_stage,
    collect_feedback_detail,
    disconnected_cause_hint,
    enrich_execute_failure_detail,
    format_feature_findings,
    is_exhausted,
    is_shell_fail,
    plan_has_shell_finish,
    replan_for_edit,
    replan_with_feedback,
)
from runtime.schema import plan_from_dict, plan_to_dict

_CUBE = plan_from_dict(
    {
        "part_name": "cube",
        "steps": [{"id": "b", "primitive": "box", "operation": "base"}],
    }
)


def test_inner_stage_cap_is_five():
    assert cap_for_stage("cadquery_compile") == INNER_CAP == 5
    assert cap_for_stage("mesh_repair") == 5
    assert cap_for_stage("primitive_gap") == 5


def test_verifier_error_is_inner_not_fail_fast():
    """verifier_error (VLM transport/parse failure) gets a bounded replan pass —
    same inner cap as a geometry defect — never an immediate fail."""
    assert cap_for_stage("verifier_error") == INNER_CAP == 5
    assert not is_exhausted("verifier_error", 4)
    assert is_exhausted("verifier_error", 5)


def test_outer_stage_cap_is_three():
    assert cap_for_stage("visual_mismatch") == OUTER_CAP == 3


def test_is_exhausted_at_cap():
    assert not is_exhausted("cadquery_compile", 4)
    assert is_exhausted("cadquery_compile", 5)
    assert not is_exhausted("visual_mismatch", 2)
    assert is_exhausted("visual_mismatch", 3)


def test_every_stage_has_a_skill():
    for stage in ("cadquery_compile", "mesh_repair", "visual_mismatch", "primitive_gap"):
        assert stage in STAGE_TO_SKILL


def test_feedback_message_names_stage_and_plan_lean():
    msg = build_feedback_message("visual_mismatch", "too tall", _CUBE)
    assert "visual_mismatch" in msg
    assert "too tall" in msg
    assert "box" in msg  # step inventory
    # Lean: must NOT dump full skill files every replan
    assert "=== REPLAN PLAYBOOK ===" not in msg
    assert len(msg) < 2500


def test_is_shell_fail_detects_typed_and_raw():
    assert is_shell_fail("CAUSE: shell_fail — cannot shell")
    assert is_shell_fail(
        "failed at step 'hollow_shell' (op: finish shell): BRep_API: command not done"
    )
    assert not is_shell_fail("union_gap: features only touch")


def test_enrich_execute_failure_detail_adds_shell_fail_rewrite():
    raw = "failed at step 'hollow_shell' (op: finish shell): BRep_API: command not done"
    out = enrich_execute_failure_detail(raw)
    assert "shell_fail" in out
    assert "DELETE" in out or "MANDATORY" in out


def test_feedback_message_shell_fail_forces_mandatory_rewrite():
    plan = plan_from_dict(
        {
            "part_name": "adapter",
            "steps": [
                {
                    "id": "body",
                    "primitive": "box",
                    "operation": "base",
                    "parameters": {"length": 10, "width": 10, "height": 10},
                },
                {"id": "hollow_shell", "op": "shell", "selector": ">Z", "value": 2},
            ],
        }
    )
    assert plan_has_shell_finish(plan)
    msg = build_feedback_message(
        "cadquery_execute",
        "CAUSE: shell_fail — OCCT cannot shell this solid",
        plan,
    )
    assert "MANDATORY REWRITE" in msg or "shell_fail" in msg
    assert "DELETE" in msg or "shell" in msg.lower()
    assert SHELL_FAIL_REWRITE.split()[0] in msg or "shell_fail" in msg


def test_feedback_message_notes_verifier_error_is_not_a_plan_defect():
    msg = build_feedback_message(
        "verifier_error", "[verifier-error] VLM judge failed: unterminated JSON object", _CUBE
    )
    assert "verifier_error" in msg
    assert "NOT a" in msg  # the caveat: this stage doesn't mean the plan is wrong


def test_collect_feedback_detail_prefers_verifier_feedback_for_visual():
    assert collect_feedback_detail("visual_mismatch", {"feedback": "wrong shape"}) == "wrong shape"


def test_collect_feedback_detail_uses_error_for_other_stages():
    assert collect_feedback_detail("cadquery_compile", {"error": "boom"}) == "boom"


_SHELL_THEN_UNION = {
    "steps": [
        {"id": "body", "primitive": "cylinder", "operation": "base", "parameters": {}},
        {"id": "hollow", "op": "shell", "selector": ">Z", "value": 2.5},
        {"id": "cap", "primitive": "cylinder", "operation": "union", "parameters": {}},
    ]
}
_TOUCHING_UNIONS = {
    "steps": [
        {"id": "hub", "primitive": "cylinder", "operation": "base", "parameters": {}},
        {"id": "spoke", "primitive": "box", "operation": "union", "parameters": {}},
    ]
}


def test_disconnected_cause_hint_flags_shell_then_union():
    """A solid unioned AFTER a shell → point at revolve / hollow-last, not overlap."""
    hint = disconnected_cause_hint(_SHELL_THEN_UNION).lower()
    assert "shell" in hint
    assert "revolve" in hint or "hollow last" in hint


def test_disconnected_cause_hint_defaults_to_overlap_for_touching_unions():
    hint = disconnected_cause_hint(_TOUCHING_UNIONS).lower()
    assert "overlap" in hint
    assert "revolve" not in hint


def test_disconnected_cause_hint_none_plan_defaults_to_overlap():
    assert "overlap" in disconnected_cause_hint(None).lower()


def test_disconnected_cause_hint_multi_solid_union_is_union_gap():
    """Additive multi-solid (no cuts) → union_gap, not vessel folklore."""
    hint = disconnected_cause_hint(_TOUCHING_UNIONS, num_solids=2, num_shells=2).lower()
    assert "union_gap" in hint or "overlap" in hint
    assert "hollow_cylinder" not in hint  # no product-named vessel sermon


def test_disconnected_cause_hint_cut_plan_is_cut_sever():
    plan = {
        "part_name": "part",
        "steps": [
            {"id": "body", "primitive": "box", "operation": "base", "parameters": {}},
            {"id": "pocket", "primitive": "box", "operation": "cut", "parameters": {}},
        ],
    }
    hint = disconnected_cause_hint(plan, num_solids=2).lower()
    assert "cut_sever" in hint
    assert "hollow_cylinder" not in hint


def test_disconnected_cause_hint_cap_after_hollow_is_secondary_body():
    plan = {
        "part_name": "bottle",
        "steps": [
            {"id": "body", "primitive": "cylinder", "operation": "base", "parameters": {}},
            {"id": "hollow", "primitive": "cylinder", "operation": "cut", "parameters": {}},
            {"id": "cap_main", "primitive": "cylinder", "operation": "union", "parameters": {}},
        ],
    }
    hint = disconnected_cause_hint(plan, num_solids=2).lower()
    assert "cap" in hint or "secondary" in hint


def test_disconnected_cause_hint_multi_shell_enclosed_void():
    hint = disconnected_cause_hint(_TOUCHING_UNIONS, num_solids=1, num_shells=2).lower()
    assert "multi-shell" in hint or "enclosed" in hint or "void" in hint or "cavity" in hint
    assert "0.5" not in hint


def test_collect_feedback_detail_mesh_repair_uses_topology_from_payload():
    payload = {
        "after": {
            "is_watertight": True,
            "open_holes": 0,
            "self_intersections": 0,
            "num_components": 2,
        },
        "actions": ["none"],
        "num_solids": 1,
        "num_shells": 2,
    }
    detail = collect_feedback_detail("mesh_repair", payload, _TOUCHING_UNIONS)
    assert "components=2" in detail
    assert "shell" in detail.lower() or "void" in detail.lower() or "cavity" in detail.lower()


def test_collect_feedback_detail_mesh_repair_uses_targeted_hint_for_shell_then_union():
    payload = {
        "after": {
            "is_watertight": True,
            "open_holes": 0,
            "self_intersections": 0,
            "num_components": 2,
        },
        "actions": ["no repair needed (already clean)"],
    }
    detail = collect_feedback_detail("mesh_repair", payload, _SHELL_THEN_UNION)
    assert "components=2" in detail
    assert "revolve" in detail.lower() or "hollow last" in detail.lower()


def test_collect_feedback_detail_mesh_repair_overlap_hint_without_plan():
    payload = {
        "after": {
            "is_watertight": True,
            "open_holes": 0,
            "self_intersections": 0,
            "num_components": 2,
        },
        "actions": ["none"],
    }
    detail = collect_feedback_detail("mesh_repair", payload)  # no plan → generic overlap
    assert "components=2" in detail
    assert "overlap" in detail.lower()


# ── Task 4: enriched replan feedback (per-feature findings + step inventory) ──


def test_format_feature_findings_renders_status_and_note():
    block = format_feature_findings(
        [
            {"feature": "side frames", "status": "wrong", "note": "too thin; make ~50mm walls"},
            {"feature": "hinge pin", "status": "missing", "note": "add a 5mm cylinder"},
            {"feature": "base plate", "status": "present", "note": ""},
        ]
    )
    assert "side frames: WRONG — too thin; make ~50mm walls" in block
    assert "hinge pin: MISSING — add a 5mm cylinder" in block
    assert "base plate: PRESENT" in block


def test_format_feature_findings_empty_is_blank():
    assert format_feature_findings([]) == ""
    assert format_feature_findings(None) == ""  # type: ignore[arg-type]


def test_collect_feedback_detail_visual_appends_findings_when_present():
    detail = collect_feedback_detail(
        "visual_mismatch",
        {
            "feedback": "[visual_failure:missing_feature] frames missing",
            "feature_findings": [
                {"feature": "side frames", "status": "missing", "note": "add two tall walls"}
            ],
        },
    )
    assert "frames missing" in detail
    assert "Per-feature verifier findings" in detail
    assert "side frames: MISSING — add two tall walls" in detail


def test_feedback_message_includes_step_inventory():
    msg = build_feedback_message("visual_mismatch", "frames too thin", _CUBE)
    assert "CURRENT PLAN STEPS" in msg
    assert "b: base box" in msg  # the _CUBE step: id 'b', base, box


def test_feedback_message_delivers_plan_via_context_not_embedded_text():
    """The parse-prone 'Previous plan was: {json}' blob is gone; the plan is
    delivered structurally via context['current_plan'] and sub-agents are forbidden."""
    msg = build_feedback_message("cadquery_compile", "bad param", _CUBE)
    assert "Previous plan was" not in msg
    assert "context['current_plan']" in msg
    assert "do NOT call llm_query" in msg or "sub-agents" in msg


def test_replan_with_feedback_threads_current_plan_dict():
    captured = {}

    def fake_planner(prompt, history, current_plan=None):
        captured["current_plan"] = current_plan
        return _CUBE

    replan_with_feedback(
        original_prompt="make a cube",
        last_plan=_CUBE,
        failure_stage="cadquery_compile",
        detail="bad param",
        prior_history=[],
        planner_fn=fake_planner,
    )
    assert captured["current_plan"] == plan_to_dict(_CUBE)  # ready dict, not text


def test_replan_for_edit_threads_current_plan_dict():
    captured = {}

    def fake_planner(prompt, history, current_plan=None):
        captured["current_plan"] = current_plan
        return _CUBE

    replan_for_edit(
        original_prompt="a cube",
        last_plan=_CUBE,
        edit_text="make it taller",
        prior_history=[],
        planner_fn=fake_planner,
    )
    assert captured["current_plan"] == plan_to_dict(_CUBE)


def test_replan_appends_system_feedback_and_calls_planner():
    captured = {}

    def fake_planner(prompt, history, current_plan=None):
        captured["prompt"] = prompt
        captured["history"] = history
        return _CUBE

    out = replan_with_feedback(
        original_prompt="make a cube",
        last_plan=_CUBE,
        failure_stage="cadquery_compile",
        detail="syntax error",
        prior_history=[{"role": "user", "content": "hi"}],
        planner_fn=fake_planner,
    )
    assert out is _CUBE
    assert captured["prompt"] == "make a cube"
    # original history preserved + a system feedback turn appended
    assert captured["history"][0] == {"role": "user", "content": "hi"}
    assert captured["history"][-1]["role"] == "system"
    assert "cadquery_compile" in captured["history"][-1]["content"]


def test_replan_propagates_planner_exception():
    """No ask_user fallback — a planner_fn failure must raise, not be swallowed."""
    import pytest

    def failing_planner(prompt, history, current_plan=None):
        raise RuntimeError("RLM budget exhausted")

    with pytest.raises(RuntimeError, match="budget exhausted"):
        replan_with_feedback(
            original_prompt="make a cube",
            last_plan=_CUBE,
            failure_stage="cadquery_compile",
            detail="syntax error",
            prior_history=[],
            planner_fn=failing_planner,
        )


def test_replan_call_retries_twice_before_raising():
    """A flaky replan call gets REPLAN_CALL_RETRIES (2) attempts before it counts
    as a failure — distinct from the stage's outer attempt cap."""
    import pytest

    from runtime.replan import REPLAN_CALL_RETRIES

    calls = {"n": 0}

    def always_failing_planner(prompt, history, current_plan=None):
        calls["n"] += 1
        raise RuntimeError(f"attempt {calls['n']} failed")

    assert REPLAN_CALL_RETRIES == 2
    with pytest.raises(RuntimeError, match="attempt 2 failed"):
        replan_with_feedback(
            original_prompt="make a cube",
            last_plan=_CUBE,
            failure_stage="cadquery_compile",
            detail="syntax error",
            prior_history=[],
            planner_fn=always_failing_planner,
        )
    assert calls["n"] == 2  # tried exactly REPLAN_CALL_RETRIES times, no more


def test_replan_call_succeeds_on_second_attempt():
    """First call flakes, second succeeds — the transient failure is swallowed."""
    calls = {"n": 0}

    def flaky_then_ok_planner(prompt, history, current_plan=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient LLM hiccup")
        return _CUBE

    out = replan_with_feedback(
        original_prompt="make a cube",
        last_plan=_CUBE,
        failure_stage="cadquery_compile",
        detail="syntax error",
        prior_history=[],
        planner_fn=flaky_then_ok_planner,
    )
    assert out is _CUBE
    assert calls["n"] == 2


# ── edit replan (post-design edit requests, not failures) ───────────────────


def test_build_edit_message_is_not_failure_framed():
    msg = build_edit_message("make it 20mm taller", _CUBE)
    assert "make it 20mm taller" in msg
    assert "context['current_plan']" in msg  # plan delivered structurally, not embedded
    assert "not a failure" in msg.lower()
    assert "failed at stage" not in msg  # distinct wording from build_feedback_message


def test_replan_for_edit_calls_planner_with_edit_message():
    captured = {}

    def fake_planner(prompt, history, current_plan=None):
        captured["prompt"] = prompt
        captured["history"] = history
        return _CUBE

    out = replan_for_edit(
        original_prompt="a cube",
        last_plan=_CUBE,
        edit_text="add a hole in the top",
        prior_history=[{"role": "user", "content": "established facts"}],
        planner_fn=fake_planner,
    )
    assert out is _CUBE
    assert captured["history"][0] == {"role": "user", "content": "established facts"}
    assert "add a hole in the top" in captured["history"][-1]["content"]


def test_replan_for_edit_does_not_touch_stage_caps():
    """An edit is fresh user intent, not a bounded retry — cap_for_stage/
    is_exhausted are stage-keyed and untouched by anything edit-related."""
    assert cap_for_stage("cadquery_compile") == INNER_CAP
    assert cap_for_stage("visual_mismatch") == OUTER_CAP


def test_replan_for_edit_retries_on_flaky_call_then_raises():
    calls = {"n": 0}

    def always_failing(prompt, history, current_plan=None):
        calls["n"] += 1
        raise RuntimeError(f"attempt {calls['n']}")

    import pytest

    with pytest.raises(RuntimeError, match="attempt 2"):
        replan_for_edit(
            original_prompt="a cube",
            last_plan=_CUBE,
            edit_text="make it bigger",
            prior_history=[],
            planner_fn=always_failing,
        )
    assert calls["n"] == 2
