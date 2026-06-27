"""
Task 8 (deterministic): parallel strategy exploration plumbing.

We cannot run the live multi-agent engine offline, but the two load-bearing, deterministic pieces
ARE testable:
  (1) select_best_candidate — the host-owned rule the root uses to pick the winner among the
      parallel children (PASS > non-PASS; certified > needs_review; fewer steps breaks ties; a
      candidate with no plan/token is ineligible).
  (2) Token cross-validity — a token minted by the (shared) geometry kernel for a CHILD's plan
      authenticates at the orchestrator gate, because every child builds against the SAME kernel
      process / per-run secret. This is what lets the root FINAL a child's winning plan.
"""
import sys
import copy
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "cad_kernel"))

from tools.select_best import select_best_candidate
from cad_kernel.attestation import make_token, verify_token


def _cand(title, steps, verdict="PASS", tier="needs_review", token="tok"):
    return {"plan": {"title": title, "primitives_sequence": [{"sequence_id": i + 1} for i in range(steps)]},
            "verdict": verdict, "trust_tier": tier, "verification_token": token}


def test_select_prefers_pass_then_certified_then_simpler():
    cands = [
        _cand("A_fail", 2, verdict="FAIL"),
        _cand("B_pass_needs_review", 8, tier="needs_review"),
        _cand("C_pass_certified_big", 12, tier="certified"),
        _cand("D_pass_certified_small", 5, tier="certified"),
    ]
    best = select_best_candidate(cands)
    assert best["plan"]["title"] == "D_pass_certified_small", best
    print("PASS selector: PASS > certified > fewer steps -> picks the simple certified candidate")


def test_select_ignores_ineligible():
    # no token, or no plan -> ineligible even if 'PASS'
    cands = [{"verdict": "PASS", "trust_tier": "certified"},               # no plan
             {"plan": {"primitives_sequence": []}, "verdict": "PASS"},      # no token
             _cand("only_valid", 3, tier="needs_review")]
    best = select_best_candidate(cands)
    assert best and best["plan"]["title"] == "only_valid", best
    assert select_best_candidate([]) is None
    assert select_best_candidate([{"verdict": "PASS"}]) is None
    print("PASS selector ignores candidates without a plan or token (and handles empty)")


def test_child_token_authenticates_at_gate():
    secret = "shared-run-secret"        # the SAME secret the kernel server + orchestrator share
    child_plan = {"title": "child winner", "assembly_kind": "single_solid",
                  "primitives_sequence": [{"sequence_id": 1, "name": "b", "primitive_type": "box",
                                           "parameters": {"length": 10, "width": 10, "height": 10},
                                           "operation": "new", "rationale": "child plan"}]}
    # a child built against the shared kernel -> kernel mints this token
    token = make_token(secret, child_plan)
    # the root FINALs the child's plan unchanged; the orchestrator gate re-checks with the same secret
    assert verify_token(secret, child_plan, token), "child-minted token must authenticate at the gate"
    # tampering with the GEOMETRY after the child verified must fail (the token pins geometry).
    # A descriptive-metadata edit (e.g. title) does NOT — that is intended; the token pins the
    # authored geometry, not prose the agent may refine before FINAL.
    tampered = copy.deepcopy(child_plan)
    tampered["primitives_sequence"][0]["parameters"]["length"] = 20   # a REAL geometry change
    assert not verify_token(secret, tampered, token), "an altered GEOMETRY must invalidate the token"
    renamed = copy.deepcopy(child_plan); renamed["title"] = "edited"
    assert verify_token(secret, renamed, token), "a pure title edit must NOT invalidate the token"
    print("PASS a child-minted token authenticates the root's FINAL (same kernel secret)")


if __name__ == "__main__":
    test_select_prefers_pass_then_certified_then_simpler()
    test_select_ignores_ineligible()
    test_child_token_authenticates_at_gate()
    print("\nALL parallel-exploration plumbing tests passed.")
