"""
attestation.py — the unforgeable verification token shared by the kernel server
(which MINTS a token on a real PASS) and the orchestrator gate (which AUTHENTICATES
it after FINAL).

Why this exists (the deterministic spine, not a bandage):
The live logs proved the agent FINALs plans without ever building/verifying them — the
whole in-loop "prove it sound yourself" contract simply did not fire. Prompt threats do
not change that. The fix is structural: a run produces a result ONLY if it carries a
token that could ONLY have come from a genuine build_verify_render PASS.

- The token is an HMAC over the CANONICAL hash of the plan (excluding the token field
  itself), so a valid token proves THAT EXACT plan passed — copying a token from a
  different plan fails, and embedding the token does not change the hash.
- The signing secret is per-run, lives only in the kernel server's env + the orchestrator
  process, and is NEVER exposed to the model's REPL — so the model cannot forge a token.
- Forging a valid HMAC without the secret is cryptographically infeasible; a fabricated
  token is rejected loud at the gate and the run is discarded.

Engine constraint (intentional): the fast-rlm output schema can only force the token to
be PRESENT at FINAL (JSON-Schema/Ajv cannot run an HMAC). AUTHENTICITY is enforced here,
in the orchestrator's post-FINAL gate. Presence (in-loop) + authenticity (at the gate)
together make a genuine PASS the only practical path to a completed run.
"""

import hashlib
import hmac
import json

SECRET_ENV_VAR = "FORGECAD_RUN_SECRET"
TOKEN_FIELD = "verification_token"
# Fields excluded from the token identity. `verification_token` (obviously) and
# `overall_dimensions` — the latter is an EMERGENT/host-owned OUTPUT (the kernel measures the
# true bounding box), not part of the geometry the agent authors.
_HASH_EXCLUDED = (TOKEN_FIELD, "overall_dimensions")
# The ONLY step fields the kernel uses to BUILD/place a piece. `name`/`part` are kept because
# `attach.to` may reference a step by name and `part` groups a multi-step part.
_GEOMETRY_STEP_FIELDS = ("sequence_id", "primitive_type", "parameters", "operation",
                         "position", "rotation", "attach", "pattern", "part", "name")
_PASS_TAG = "PASS"


def _geometry_identity(plan: dict) -> dict:
    """Project a plan down to ONLY its geometry-determining fields. This is what the token pins, so a
    genuinely-verified plan is invariant to descriptive-metadata edits (title / assumptions /
    clarifications / engineering_requirements / per-step rationale) that do NOT change the built
    solid. The kernel builds the solid ONLY from `assembly_kind` + `primitives_sequence` (and, within
    a step, only the build fields above), so those are the only fields the geometry token must pin."""
    steps = []
    for s in (plan.get("primitives_sequence") or []):
        if isinstance(s, dict):
            steps.append({k: s[k] for k in _GEOMETRY_STEP_FIELDS if k in s})
    return {"assembly_kind": plan.get("assembly_kind", "single_solid"),
            "primitives_sequence": steps}


def _hash_identity(identity: dict) -> str:
    blob = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _raw_plan_hash(plan: dict) -> str:
    """Fail-safe geometry hash from the RAW dict (no schema normalization). Used only if the schema
    cannot be imported/normalized; still geometry-only so it stays metadata-invariant."""
    return _hash_identity(_geometry_identity(plan or {}))


def canonical_plan_hash(plan: dict) -> str:
    """Stable sha256 hex of a plan's AUTHORED GEOMETRY, canonicalized.

    The dict is SCHEMA-NORMALIZED through `GeometryPlan` (coercing int<->float, filling derived
    defaults, fixing key order) and then PROJECTED to its GEOMETRY-DETERMINING fields only —
    `assembly_kind` + each step's build fields (primitive_type/parameters/operation/position/
    rotation/attach/pattern/part/name). So the token pins the GEOMETRY and survives BOTH
    representational noise AND descriptive-metadata edits the agent makes between verifying and
    FINAL:
      - a derived/auto-set field appearing or not (e.g. `contains_freeform`);
      - `int` vs `float` (8 vs 8.0), key order, or omitted fields carrying their schema default;
      - a reworded `title`, an added `assumption`/`clarification`, an edited
        `engineering_requirements`, a reworded per-step `rationale` — none of which change the
        built solid.
    This is what stops a genuinely-verified plan from being DISCARDED at the gate over a benign
    edit — the exact failure that downgraded a sound impeller to a best-effort artifact (the agent
    renamed the title + added an assumption after the token was minted). A REAL geometry change
    (a parameter, an operation, an added/removed step) still changes the projection, so a
    forged/altered plan is still rejected, and the per-run signing secret is still required to mint
    — forgery protection is unchanged.

    FAIL-SAFE: if the schema cannot be imported or the plan cannot be normalized, fall back to the
    RAW geometry projection. The mint (kernel server) and the gate (orchestrator) both import the
    SAME schema, so they hash identically; the function never raises (the gate must not crash).
    """
    try:
        import sys as _sys
        from pathlib import Path as _Path
        _root = _Path(__file__).resolve().parent.parent
        if str(_root) not in _sys.path:
            _sys.path.insert(0, str(_root))
        from schemas.geometry_plan import GeometryPlan
        normalized = GeometryPlan(**plan).model_dump(mode="json")
        return _hash_identity(_geometry_identity(normalized))
    except Exception:
        return _raw_plan_hash(plan)


def make_token(secret: str, plan: dict) -> str:
    """Mint the verification token for a plan that PASSED. Bound to the plan hash + the
    PASS tag, signed with the per-run secret."""
    plan_hash = canonical_plan_hash(plan)
    msg = (plan_hash + ":" + _PASS_TAG).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def verify_token(secret: str, plan: dict, token: str) -> bool:
    """Constant-time check that `token` is the authentic PASS token for `plan` under
    `secret`. Returns False for a missing/forged/wrong-plan token."""
    if not secret or not token or not isinstance(token, str):
        return False
    expected = make_token(secret, plan)
    return hmac.compare_digest(expected, token)
