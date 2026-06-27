"""
geometry_server.py — host-side MCP server for the BUILD -> VERIFY -> RENDER stage.

Runs the native stack (CadQuery/OCP + MeshLib + matplotlib) that the WASM REPL
cannot. Solids live here in a host registry; only ids + JSON reports cross back.

Tools:
  build_plan(plan)                      -> {solid_id, ok, steps, failed_step?}
  verify_solid(solid_id, ...)           -> FIXED battery report (the verdict)
  render_solid(solid_id)                -> {png_path}  (only after a build)
  build_verify_render(plan, ...)        -> one-shot convenience
  run_advisory(solid_id, fn_name, ...)  -> ADVISORY MeshLib measurement (never the verdict)
  meshlib_browse / meshlib_search / meshlib_doc  -> KB grounding for the battery/advisory

Never print to stdout (MCP channel) — use stderr.
"""
import os
import sys
import uuid
from pathlib import Path

from mcp.server.fastmcp import FastMCP

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "meshlib_kb_pack" / "tools"))

import kernel
import verify as verify_mod
import fidelity as fidelity_mod
from attestation import canonical_plan_hash, make_token, SECRET_ENV_VAR, TOKEN_FIELD

from pydantic import BaseModel, ConfigDict


class ToolResult(BaseModel):
    """B2 — deterministic read-path. A tool that returns this (instead of a bare ``dict``) makes
    FastMCP emit UNWRAPPED ``structuredContent``, so the fast-rlm ``mcp_call`` proxy returns a REAL
    dict to the agent — its natural ``result["verdict"]`` / ``result.get(...)`` /
    ``isinstance(result, dict)`` then just work (a bare ``-> dict`` returns a STRING, which the
    agent kept mis-reading — the failure that discarded a passing, tokened chair).

    Also dict-compatible so host-side callers/tests that index it like a dict keep working."""
    model_config = ConfigDict(extra="allow")

    def __getitem__(self, key):
        try:
            return getattr(self, key)
        except AttributeError:
            raise KeyError(key)

    def __contains__(self, key):
        return hasattr(self, key)

    def get(self, key, default=None):
        return getattr(self, key, default)


def _bbox_from_plan(plan: dict):
    ov = (plan or {}).get("overall_dimensions") or {}
    if not ov:
        return None
    return [ov.get("width", 0), ov.get("length", 0), ov.get("height", 0)]

RENDER_DIR = Path(os.environ.get("RENDER_DIR", ROOT / "renders"))
RENDER_DIR.mkdir(exist_ok=True)

mcp = FastMCP("GeometryKernel")
_SOLIDS = {}  # solid_id -> cq solid

# ---- Attempt ledger (in-process, per-run) ----------------------------------
# The server is spawned ONCE per run and persists across every build_verify_render
# call, so a plain in-memory ledger spans the whole agent loop. It turns blind
# retries into deterministic, escalating guidance: if the SAME geometric check keeps
# failing across attempts (or the agent re-submits an identical failing plan), the
# tool says so explicitly instead of letting the agent spin.
_LEDGER = {
    "total_attempts": 0,
    "plan_attempts": {},   # plan_hash -> count of times this exact plan was submitted
    "check_streak": {},    # failing-check name -> consecutive attempts it has failed
}


# ---- Best-candidate checkpoint (Task 1) -------------------------------------
# Across the WHOLE run (root + every parallel child share THIS one server process), bank the
# best geometrically sound + coherent candidate, ranked fidelity-pass(2) > sound+coherent(1).
# Persisted to FORGECAD_CHECKPOINT_FILE so the orchestrator can ALWAYS deliver the best REAL
# artifact at run end — even when the agent never FINALs (budget exhaustion), which is exactly
# how the latest office-chair run lost a perfectly sound chair. Deterministic: the stored plan
# rebuilds the identical solid host-side, so we persist the plan (the source of truth), not the
# heavy solid.
_CHECKPOINT_FILE = os.environ.get("FORGECAD_CHECKPOINT_FILE")
_BEST = {"rank": -1}


def _update_best(plan: dict, measured_bbox, png_path, trust_tier: str,
                 fidelity: dict, fidelity_pass: bool, rank_override: float = None):
    """Record this candidate iff it is at least as good as the current best.
    Rank: fidelity-pass(2) > sound+coherent(1) > sound-but-interpenetrating last-resort(0.5).
    `rank_override` banks a last-resort candidate (sound + coherent but failing ONLY the mating
    gate) so the orchestrator can still deliver SOMETHING — it is never token-minted and stays
    needs_review. On a tie the LATEST (more refined) candidate wins. Writes the file atomically."""
    rank = rank_override if rank_override is not None else (2 if fidelity_pass else 1)
    if rank < _BEST.get("rank", -1):
        return
    _BEST.update({"rank": rank, "plan": plan, "measured_bbox": measured_bbox,
                  "png_path": png_path, "trust_tier": trust_tier, "fidelity": fidelity})
    # Re-read the path at CALL time too (defensive: the env should be present at import, but this
    # guards against any late/edge env delivery). If there is genuinely no path, say so loudly —
    # that is the signal that a future run's "delivered nothing" was a checkpoint-channel problem.
    ckpt = _CHECKPOINT_FILE or os.environ.get("FORGECAD_CHECKPOINT_FILE")
    if not ckpt:
        print("[geometry_server] WARNING: geom PASS but NO FORGECAD_CHECKPOINT_FILE set — "
              "candidate banked in-memory only; the orchestrator cannot promote it.", file=sys.stderr)
        return
    try:
        import json as _json
        record = {"rank": rank, "trust_tier": trust_tier, "measured_bbox": measured_bbox,
                  "png_path": png_path, "fidelity": fidelity, "plan": plan}
        tmp = ckpt + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            _json.dump(record, f)
        os.replace(tmp, ckpt)
        print(f"[geometry_server] checkpoint BANKED (rank={rank}, trust_tier={trust_tier}) -> {ckpt}",
              file=sys.stderr)
    except Exception as e:
        print(f"[geometry_server] checkpoint write FAILED: {e}", file=sys.stderr)


def _new_id():
    return "solid-" + uuid.uuid4().hex[:8]


def _record_and_advise(plan_hash: str, failing_checks: list, verdict_pass: bool) -> str:
    """Update the ledger with this attempt's outcome and return a structured next_action
    string. `failing_checks` is the list of failing check names (empty on PASS)."""
    led = _LEDGER
    led["total_attempts"] += 1
    led["plan_attempts"][plan_hash] = led["plan_attempts"].get(plan_hash, 0) + 1
    same_plan_count = led["plan_attempts"][plan_hash]

    failing_set = set(failing_checks or [])
    # bump streaks for currently-failing checks; reset the rest.
    for name in list(led["check_streak"].keys()):
        if name not in failing_set:
            led["check_streak"][name] = 0
    for name in failing_set:
        led["check_streak"][name] = led["check_streak"].get(name, 0) + 1

    if verdict_pass:
        return ("verdict PASS — this plan is sound + right-sized. Embed the returned "
                f"'{TOKEN_FIELD}' into THIS exact plan dict and FINAL it. Do not modify the "
                "plan after verifying, or the token will no longer match.")

    if same_plan_count >= 2:
        return ("FORBIDDEN MOVE: you re-submitted an IDENTICAL plan that already failed "
                f"(attempt #{same_plan_count} for the same plan). Re-running an unchanged plan "
                "cannot change the verdict — you MUST change the geometry (dimensions, "
                "placement/attach, primitive vs custom) before verifying again.")

    repeated = sorted(n for n in failing_set if led["check_streak"].get(n, 0) >= 2)
    if repeated:
        return (f"NO-PROGRESS on {repeated}: this/these check(s) have now failed across "
                f"{max(led['check_streak'][n] for n in repeated)} attempts. Stop repeating the "
                "same kind of fix — pivot strategy (primitive<->custom, a different "
                "decomposition, reconcile declared dims to the measured bbox), or FINAL your "
                "best sound candidate and record the residual issue in 'assumptions'.")

    return ("first/new failure for these checks — read report['checks'], fix the cited "
            "GEOMETRIC cause, and re-verify.")


def _validate_plan_schema(plan: dict):
    """A1 (host-enforced): validate a plan against the REAL GeometryPlan model — the SAME contract
    the FINAL gate and host_tools.validate_plan use. Returns a list of {location, message} on
    failure, [] if valid, or None if the validator itself could not be loaded (fail-open: do NOT
    block the build on our own import problem)."""
    import sys as _sys
    if str(ROOT) not in _sys.path:
        _sys.path.insert(0, str(ROOT))
    try:
        from schemas.geometry_plan import GeometryPlan
    except Exception as e:
        print(f"[geometry_server] schema validator load failed ({e}); skipping in-loop validation",
              file=sys.stderr)
        return None
    try:
        GeometryPlan(**plan)
        return []
    except Exception as e:
        errs = []
        if hasattr(e, "errors"):
            for err in e.errors():
                loc = ".".join(str(x) for x in err.get("loc", []))
                errs.append({"location": loc, "message": err.get("msg", "")})
        else:
            errs = [{"location": "", "message": str(e)}]
        return errs


@mcp.tool()
def build_plan(plan: dict) -> dict:
    """Execute a GeometryPlan deterministically into a solid (stored host-side).
    Returns {ok, solid_id, steps, failed_step?}. On failure, steps[].error tells
    you exactly which step broke."""
    res = kernel.build_plan(plan)
    if not res["ok"]:
        return {"ok": False, "steps": res["steps"], "failed_step": res.get("failed_step"),
                "error": res.get("error")}
    sid = _new_id()
    _SOLIDS[sid] = res["solid"]
    return {"ok": True, "solid_id": sid, "steps": res["steps"]}


@mcp.tool()
def verify_solid(solid_id: str, declared_bbox: list = None, expected_components: int = 1) -> dict:
    """Run the FIXED MeshLib battery (the VERDICT). declared_bbox = [x,y,z] from the
    plan's overall_dimensions; expected_components > 1 for intentional assemblies."""
    solid = _SOLIDS.get(solid_id)
    if solid is None:
        raise ValueError(f"unknown solid_id {solid_id!r} (build first)")
    return verify_mod.verify_solid(solid, declared_bbox=declared_bbox,
                                   expected_components=expected_components)


@mcp.tool()
def render_solid(solid_id: str) -> dict:
    """Render a built solid to a multi-view PNG (after verify). Returns {png_path}."""
    from render import render_solid as _render
    solid = _SOLIDS.get(solid_id)
    if solid is None:
        raise ValueError(f"unknown solid_id {solid_id!r} (build first)")
    out = str(RENDER_DIR / f"{solid_id}.png")
    return {"png_path": _render(solid, out)}


def _build_verify_render_impl(plan: dict, declared_bbox: list = None,
                              expected_components: int = None, render: bool = True,
                              render_format: str = None) -> dict:
    """Implementation shared by build_verify_render and its alias. (render_format is accepted and
    IGNORED — deterministic tolerance for an observed model mistake; the format is fixed host-side.)"""
    plan_hash = canonical_plan_hash(plan)

    # A1 (host-enforced): validate against the SAME GeometryPlan contract the FINAL gate uses,
    # IN-LOOP. Otherwise the loop builds a raw dict that may "pass geometry" yet be un-FINAL-able
    # (e.g. pattern+operation:"new", which the validator forbids) — the trap that made a chair run
    # loop 9x then fake a token. Reject early with the concrete cause + the working construction.
    _schema_errors = _validate_plan_schema(plan)
    if _schema_errors:
        na = _record_and_advise(plan_hash, ["schema_invalid"], verdict_pass=False)
        detail = "; ".join(f"{e['location']}: {e['message']}" for e in _schema_errors)
        hint = ""
        if any("pattern" in (e.get("message") or "").lower() for e in _schema_errors):
            hint = (" A pattern fuses/cuts into ONE body (operation join/cut/intersect); for "
                    "SEPARATE repeated parts (e.g. casters), use explicit per-instance steps each "
                    "`attach`-ed to its target — do NOT pattern separate bodies.")
        return {"stage": "validate", "ok": False, "errors": _schema_errors,
                "next_action": f"SCHEMA INVALID — fix before building: {detail}.{hint} {na}"}

    res = kernel.build_plan(plan)
    if not res["ok"]:
        fs = res.get("failed_step")
        failing = [f"build_failure:step_{fs}" if fs is not None else "build_failure"]
        na = _record_and_advise(plan_hash, failing, verdict_pass=False)
        err = res.get("error")
        # C2: lead next_action with the concrete, design-level build error (e.g. a
        # GeometryCombineError) so the actionable FIX reaches the agent, not just the generic ledger.
        na = f"BUILD FAILED: {err}\n{na}" if err else na
        return {"stage": "build", "ok": False, "steps": res["steps"],
                "failed_step": fs, "error": err, "next_action": na}

    solid = res["solid"]
    meta = res.get("meta", {})
    sid = _new_id()
    _SOLIDS[sid] = solid

    # Harness-derive expectations (do NOT trust model-omitted defaults).
    if declared_bbox is None:
        declared_bbox = _bbox_from_plan(plan)
    kind = plan.get("assembly_kind", "single_solid")
    if expected_components is None:
        expected_components = 1 if kind == "single_solid" else meta.get("part_count", 1)

    # P5: explicit user-stated max-envelope (a non-negotiable). Read from env; FAIL-OPEN on any error.
    _size_constraint = None
    try:
        _sc = os.environ.get("FORGECAD_SIZE_CONSTRAINT")
        if _sc:
            import json as _json_sc
            _size_constraint = _json_sc.loads(_sc)
    except Exception:
        _size_constraint = None

    v = verify_mod.verify_solid(solid, declared_bbox=declared_bbox,
                                expected_components=expected_components,
                                plan=plan, part_solids=meta.get("part_solids"),
                                fusion_audit=meta.get("fusion_audit"),
                                size_constraint=_size_constraint)
    geom_pass = v["verdict"] == "PASS"
    failing = [c["name"] for c in v.get("checks", []) if not c.get("passed")]

    measured_bbox = v.get("measured_bbox")
    out = {"stage": "verify", "solid_id": sid, "verdict": v["verdict"],
           "report": v, "build_steps": res["steps"], "measured_bbox": measured_bbox}

    # Render + fidelity ONLY on a geometrically sound + coherent candidate (cost control).
    fidelity = None
    if geom_pass:
        png = None
        try:
            from render import render_solid as _render
            png = _render(solid, str(RENDER_DIR / f"{sid}.png"))
            out["png_path"] = png
        except Exception as e:
            print(f"[geometry_server] render failed: {e}", file=sys.stderr)
        fidelity = fidelity_mod.critique([png], measured_bbox=measured_bbox,
                                         part_names=meta.get("parts")) if png else \
            {"status": "unavailable", "missing_major_features": [], "notes": "render unavailable"}
        out["fidelity"] = fidelity

    # --- Task 2: fidelity is ADVISORY. It grades quality + sets the TRUST TIER; it NEVER blocks
    #     the token or flips the geometry verdict. The token mints on geometry+coherence PASS.
    #     A sound-but-blocky candidate is DELIVERED as `needs_review`, not discarded — the old
    #     hard gate (final_pass = geom_pass AND not fidelity_reject) is exactly what made the
    #     sound chair at step 7 of the failing run yield nothing. Fidelity feedback is still
    #     surfaced so the agent can choose to refine toward `certified`.
    fidelity_status = (fidelity or {}).get("status")
    fidelity_pass = fidelity_status == "pass"
    fidelity_reject = fidelity_status == "reject"
    contains_custom = any((s or {}).get("primitive_type") == "custom"
                          for s in (plan.get("primitives_sequence") or []))
    trust_tier = "certified" if (fidelity_pass and not contains_custom) else "needs_review"
    final_pass = geom_pass  # fidelity no longer gates the verdict/token
    if geom_pass:
        out["trust_tier"] = trust_tier

    # The ledger sees the GEOMETRY verdict (fidelity is advisory, not a failing check).
    base_advice = _record_and_advise(plan_hash, failing, verdict_pass=final_pass)
    if geom_pass and fidelity_reject:
        miss = ", ".join(fidelity.get("missing_major_features") or []) or "(unspecified)"
        out["next_action"] = (
            "verdict PASS (sound + coherent) — TOKEN ISSUED; this is deliverable now as "
            "trust_tier='needs_review'. FIDELITY REVIEW (advisory) says the form could match the "
            f"request more closely: {miss}. {fidelity.get('notes', '')} You MAY embed the token and "
            "FINAL now, OR refine the form (contour/round/orient — do NOT drop requested features) "
            "and re-verify to earn trust_tier='certified'. " + base_advice)
    elif geom_pass and fidelity_status == "unavailable":
        out["next_action"] = ("verdict PASS (geometry + coherence) — TOKEN ISSUED (trust_tier="
                              f"'{trust_tier}'). NOTE: visual fidelity check was UNAVAILABLE, so "
                              "'looks-like-the-request' is unverified. " + base_advice)
    else:
        out["next_action"] = base_advice

    # Mating gate (Task 4/5): when parts interpenetrate, lead next_action with the exact offending
    # pair(s) + fix so the agent can pull them apart to a flush mate. `only_interpenetration` means
    # the geometry is otherwise sound + coherent (the ONLY failing check is the mating gate).
    coh = v.get("coherence") or {}
    inter = coh.get("interpenetrations") or []
    only_interpenetration = (not geom_pass) and kind == "assembly" and set(failing) == {"no_interpenetration"}
    if inter and not geom_pass:
        pairs = "; ".join(f"{x['partB']}<->{x['partA']} ({x['overlap_mm3']}mm^3, "
                          f"{round(x['overlap_fraction'] * 100)}% buried)" for x in inter)
        fixes = " | ".join(x["hint"] for x in inter)
        out["interpenetrations"] = inter
        out["next_action"] = (
            "MATING GATE FAILED — parts interpenetrate ('dug inside'), so NO token was issued. "
            f"Interpenetrating pair(s): {pairs}. {fixes}\n" + out.get("next_action", ""))

    # --- Task 1: bank the best sound+coherent candidate seen this run (ranked fidelity-pass >
    #     sound+coherent). Persisted so the orchestrator can ALWAYS deliver the best real artifact.
    if geom_pass:
        _update_best(plan, measured_bbox, out.get("png_path"), trust_tier, fidelity, fidelity_pass)

    # EYES IN THE LOOP: a verify failure is the hardest thing for a blind agent to debug. On ANY
    # geometry/coherence failure (B3: broadened from connectivity-only), render the (failing)
    # geometry and attach a vision spatial description so the agent can SEE what is disconnected/
    # floating/misplaced/mis-oriented. Fail-open: if vision is unavailable, simply omit the note
    # (verdict unchanged). Not run when geometry passed (the fidelity critic covers form there).
    geometry_failed = not geom_pass
    if geometry_failed:
        try:
            png = out.get("png_path")
            if not png:
                from render import render_solid as _render
                png = _render(solid, str(RENDER_DIR / f"{sid}.png"))
                out["png_path"] = png
            desc = fidelity_mod.spatial_critique([png], issue=v.get("localized_fix"),
                                                 part_names=meta.get("parts"))
            if desc:
                out["visual_inspection"] = desc
                out["next_action"] = f"{out['next_action']}\nVISUAL INSPECTION (look at your model): {desc}"
        except Exception as e:
            print(f"[geometry_server] spatial critique skipped: {e}", file=sys.stderr)

    # Last-resort banking (Task 4): a sound + coherent candidate that fails ONLY the mating gate is
    # banked at the lowest rank (0.5) so the orchestrator can still deliver a clearly-tagged
    # best-effort artifact if the agent never reaches a flush version. Never token-minted; always
    # needs_review. Preserves the "never deliver nothing" invariant while the token stays hard-gated.
    if only_interpenetration:
        _update_best(plan, measured_bbox, out.get("png_path"), "needs_review",
                     fidelity=None, fidelity_pass=False, rank_override=0.5)

    # A3: transparency — if the kernel auto-snapped any declared-attach part into contact (Fix A),
    # surface it so the agent/user knows a part was moved to honor its attach (fail-open).
    try:
        _snap = meta.get("snapped") or []
        if _snap:
            out["snapped"] = _snap
            _mv = ", ".join(f"{s['part']}->{s['to']} ({s['moved_mm']}mm)" for s in _snap)
            out["next_action"] = (out.get("next_action", "") +
                                  f"\nNOTE: {len(_snap)} part(s) were auto-snapped to their declared "
                                  f"attach target(s) to enforce contact: {_mv}. Verify they landed "
                                  f"where intended (tighten your offsets if not).")
    except Exception as e:
        print(f"[geometry_server] snap surfacing skipped: {e}", file=sys.stderr)

    if final_pass:
        secret = os.environ.get(SECRET_ENV_VAR)
        if secret:
            out[TOKEN_FIELD] = make_token(secret, plan)
            out["token"] = out[TOKEN_FIELD]  # A3: alias key — the agent sometimes reads ["token"]
    return out


@mcp.tool()
def build_verify_render(plan: dict, declared_bbox: list = None,
                        expected_components: int = None, render: bool = True,
                        render_format: str = None) -> "ToolResult":
    """Build -> verify (geometry + assembly COHERENCE) -> render -> FIDELITY critique (advisory).

    The verification_token is minted when the result is (a) geometrically sound AND (b) ONE
    coherent object (single_solid = one fused body; assembly = every part sound AND all parts form
    one connected, contact-touching cluster). A vision critique then GRADES the form against the
    ORIGINAL request and sets `trust_tier` ('certified' if it looks right, else 'needs_review') —
    this is ADVISORY: it never blocks the token or flips the verdict, so a sound+coherent model is
    always deliverable (you may FINAL it, or refine toward 'certified'). The token is the ONLY way
    to FINAL; copy the returned 'verification_token' verbatim into the plan. `declared_bbox`/
    `expected_components` are derived from the plan automatically — you do not need to pass them
    (`render_format` is accepted but ignored). The plan is also schema-validated first; an invalid
    plan is returned with stage='validate' and no token. Read `next_action` every time: it gives
    escalating, geometry-aware guidance (incl. which part is disconnected or which feature is
    missing)."""
    return ToolResult(**_build_verify_render_impl(plan, declared_bbox, expected_components, render, render_format))


@mcp.tool()
def build__verify_render(plan: dict, declared_bbox: list = None,
                         expected_components: int = None, render: bool = True,
                         render_format: str = None) -> "ToolResult":
    """ALIAS (A3): deterministic tolerance for the observed double-underscore misspelling of
    build_verify_render. Identical behavior. (This only neutralizes the observed mistake; novel
    typos still fail, because tool-name resolution lives in fast-rlm, which we do not modify.)"""
    return ToolResult(**_build_verify_render_impl(plan, declared_bbox, expected_components, render, render_format))


@mcp.tool()
def critique_render(solid_id: str, intent: str = None) -> dict:
    """Render a built solid and run the visual fidelity critique against the ORIGINAL request
    (advisory standalone view of what build_verify_render does internally). Returns the
    structured critique. Does NOT mint a token."""
    solid = _SOLIDS.get(solid_id)
    if solid is None:
        raise ValueError(f"unknown solid_id {solid_id!r} (build first)")
    from render import render_solid as _render
    png = _render(solid, str(RENDER_DIR / f"{solid_id}.png"))
    return {"png_path": png, "fidelity": fidelity_mod.critique([png], intent=intent)}


@mcp.tool()
def run_advisory(solid_id: str, fn_name: str, kwargs: dict = None) -> dict:
    """Run an RLM-PROPOSED MeshLib measurement as ADVISORY ONLY (never the verdict)."""
    solid = _SOLIDS.get(solid_id)
    if solid is None:
        raise ValueError(f"unknown solid_id {solid_id!r}")
    return verify_mod.run_advisory(solid, fn_name, **(kwargs or {}))


# ground the battery/advisory with the curated MeshLib KB
try:
    from meshlib_kb_tools import register as register_meshkb
    register_meshkb(mcp, kb_path=str(ROOT / "meshlib_kb_pack" / "knowledge" / "meshlib_kb.json"))
    print("[geometry_server] MeshLib KB tools registered", file=sys.stderr)
except Exception as e:
    print(f"[geometry_server] WARNING: MeshLib KB tools not registered: {e}", file=sys.stderr)


if __name__ == "__main__":
    mcp.run()
