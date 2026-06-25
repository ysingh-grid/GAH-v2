"""Per-turn RLM planner: one user message in, one typed decision out.

The backend re-invokes `run_planner_turn` on every user message with the full
chat history. The RLM either asks one more clarifying question or, once it has
enough, emits a validated PrimitivePlan. That two-way decision is the
`PlannerOutput` model below, used as the fast-rlm `output_schema` so the
model's FINAL value is schema-checked before we ever see it.

This module owns the *pure* pieces (the output contract, the task prompt, the
result parser). The single impure call — `fast_rlm.run` — is isolated in
`run_planner_turn` so everything else is unit-testable without network or cost.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Tools the planner may call inside its REPL. Imported as objects so fast-rlm
# can extract their source; they must stay self-contained (see rlm/pull_tools).
from rlm.pull_tools import (
    fetch_kb_sections,
    list_kb_index,
    list_primitives,
    lookup_design_reference,
    lookup_primitive,
)
from runtime.schema import PrimitivePlan

if TYPE_CHECKING:
    from fast_rlm import RLMConfig

_PLANNER_TOOLS = [
    list_primitives,
    list_kb_index,
    fetch_kb_sections,
    lookup_primitive,
    lookup_design_reference,
]

PLANNER_TASK = """\
You are the PLANNER ORCHESTRATOR in a text-to-CAD system. You turn a request into ONE
validated PrimitivePlan: an ordered list of steps. Two kinds of step exist:
  • PRIMITIVE STEP — a placed library primitive folded into the body with a CSG
    operation (base / union / cut / intersect), plus parameters, position, orientation,
    and an optional pattern (polar/linear array).
  • FINISH STEP — a deterministic post-body modifier applied to the accumulated solid:
    fillet, chamfer, shell, hole, cbore, csk, mirror. These act on the WHOLE body so
    far, not a primitive. (Detailed shape near the end of this prompt.)

## HARD BUDGET: 6 REPL steps, then you MUST emit FINAL. (A step = one block.)

## ⚙️ GEOMETRY RULES (booleans are unforgiving — violating these fails compile or mesh):
- ORIGIN CONVENTION (get placement right or parts float/misalign):
    • CENTERED at `position` in ALL axes — box, cylinder, sphere, ellipsoid, capsule,
      torus, hollow_box, chamfered_box, filleted_box, rounded_cylinder. To rest the
      part flat on the XY plane (base at z=0), set position.z = height/2 (e.g. a
      12mm-tall cylinder hub → position.z = 6).
    • BASE at `position` (extrudes UP) — ring, prism, hexagon_prism, octagonal_prism,
      hollow_cylinder, cone, pyramid, profile_extrude, revolve. position.z = 0 sits
      these on the plane.
    • Unsure / wedge: lookup_primitive(key) and read its description before placing.
- OVERLAP, never just touch. Any `union` feature must extend ~0.5-1mm INTO the body
  it joins; a feature that only TOUCHES (tangent/coincident face) does NOT fuse and
  leaves disconnected components → mesh fails. Example: a spoke bridging a hub (r=15)
  to a rim (inner r=44) needs length ≈ 31 (not 29) so it overlaps both by ~1mm.
- CUTS must pass fully through, accounting for centering. A `cut` cylinder is CENTERED,
  so to pierce a body spanning z=0..T set the cut's position.z = T/2 and height = T+1
  (spans -0.5..T+0.5). Never leave a paper-thin film.
- ONE connected solid. After all unions the part must be a single connected body —
  every feature must overlap something already attached. (intersect/mirror excepted —
  see below — but the FINAL result must still be one connected body.)
- INTERSECT keeps only the overlap of the primitive and the body (boolean AND). Use it
  to carve a body down to a shared region — e.g. box ∩ sphere = a box with a domed/
  rounded bulge, cylinder ∩ box = a D-profile. The intersecting primitive must actually
  overlap the body or you get an empty solid (mesh fails).
- FINISH STEPS are available and deterministic — use them for edge treatments and holes
  instead of approximating with primitives:
    • fillet/chamfer to round or bevel real edges of the assembled body
    • shell to hollow it (mug, enclosure)
    • hole/cbore/csk to drill fasteners at exact (x,y) points on a face
    • mirror to build a symmetric part from one designed half
  You may STILL use filleted_box / chamfered_box / rounded_cylinder PRIMITIVES when the
  rounding is intrinsic to a sub-shape; prefer a FINISH STEP when rounding the final body.

## ⛔ Prohibitions:
- Do NOT invent fastener/standard dimensions — look them up (see Step 2).
- Keep REPL output small: never print the whole catalog or whole reference back.

## When to FORK vs design in ONE context — READ THIS, it decides quality + speed:
A FORK spawns a sub-agent with a FRESH context. That keeps any single API call SMALL,
so a big part never fills one call to the brim (which stalls/times out). Two valid
fork cases:

  (A) INDEPENDENT SOLIDS — distinct bodies that only meet at an interface.
      • cricket bat -> ["blade","handle"]    • bolt + nut -> ["bolt","nut"]
      Fork one child per solid; each designs freely in its OWN local frame.

  (B) FEATURES OF ONE CONNECTED BODY (hub+spokes+rim, flange+bolt-bosses+ribs) —
      fork one child per feature, but ONLY AFTER you fix a SHARED-FRAME CONTRACT
      yourself so the blind children still line up. Use this when designing the whole
      body in your own REPL would bloat your context (many features / standard dims).
        1. YOU decide the skeleton numbers FIRST: every shared anchor (radii, planes,
           bolt-circle positions) and HOW features OVERLAP (~0.5-1mm INTO each other —
           features that only touch do NOT fuse → mesh fails).
        2. YOU assign each feature an ABSOLUTE placement + an operation (EXACTLY ONE
           feature is "base"; the rest "union"/"cut").
        3. Each child builds ONLY its feature at the absolute position you gave it, in
           the shared frame — it NEVER invents or changes a shared anchor.
      Wheel example: you fix hub cyl r=15, rim ring inner=40/outer=44, spoke box
      spanning r=14..41 (overlaps hub & rim by ~1mm), polar ×5 — THEN fork
      [hub(base), rim(union), spoke(union)].

RULE: SIMPLE parts (a cube, a box with 2 holes) — do NOT fork; just emit the steps
yourself (fork has overhead). Fork when (A) independence OR (B) the single body is
complex enough that one context would balloon. (B) is what makes big parts fast +
reliable — small per-call context, alignment guaranteed by YOUR contract.

## Procedure — follow in order:

Step 1 — Your catalog + KB menu are ALREADY in context (pre-fetched for you). Do NOT
  call list_primitives() or list_kb_index() — that wastes a whole REPL step. Read:
    primitives = context["available_primitives"]   ← shape catalog (names)
    kb_index   = context["kb_index"]               ← {cadquery:{slug:desc}}  (CadQuery KB menu)
  ONLY if a key is missing, fall back to list_primitives() / list_kb_index().

Step 2 — Based on the request and the kb_index already in context, fetch ONLY the
  KB sections that are actually relevant. Pick ≤5 slugs. Examples:
    • User wants a mug → fetch ["3d-primitives", "modification", "revolve", "shell"]
    • User wants a bracket with holes → fetch ["3d-primitives", "holes", "multi-point"]
    • Simple box → fetch ["3d-primitives"] only — don't over-fetch
  kb = fetch_kb_sections(["slug-1", "slug-2", ...])

  IMPORTANT: kb tells you what the DETERMINISTIC COMPILER supports.
  PrimitiveStep operations: base / union / cut / intersect.
  FinishStep ops (post-body, deterministic): fillet / chamfer / shell / hole /
  cbore / csk / mirror. Plan fillet/shell/holes as FINISH STEPS — they compile
  to fixed CadQuery calls (.edges().fillet(), .faces().shell(), .hole(), etc.).

Step 3 — Read context["original_prompt"]. For any standard feature (bolt/screw holes,
  counterbores, bolt circles, ribs, mounting plates) call:
      ref = lookup_design_reference("<the feature + size, e.g. 'M6 counterbored holes'>")
  Use ref["fastener_dims"] for exact hole diameters (clearance/tap/cbore, in mm) and
  ADAPT ref["recipes"][name]["steps"] — fill the <...> placeholders with real mm values
  and positions, then inline them. Adapting a recipe beats composing CSG from scratch.
  If a REQUIRED dimension is still missing and no sensible default exists, FINAL with
  action="ask_user" NOW. Offer a concrete default you suggest, or ask the user to provide the value.

Step 4 — Decide structure with the FORK rule above.
  • SIMPLE single part (the common case): build the steps yourself. base first, then
    union/cut/intersect features (adapted recipes), then FINISH STEPS last
    (fillet/chamfer/shell/holes/mirror act on the finished body). One frame. Fastest.
  • FORK — independent solids (A) OR features of a complex body (B): fork IN PARALLEL
    with batch_llm_query (NEVER asyncio.gather — the engine blocks it). Give each child
    a SHORTLIST of candidate primitives + tools=[lookup_primitive, lookup_design_reference].
    For (B) you MUST pass each child its absolute placement + assigned operation from
    YOUR shared-frame contract — the child does not invent shared anchors:

      STEP_SCHEMA = {"type": "array", "items": {"type": "object"}}

      def design(feature, candidates, frame):
          return llm_query({
              "task": ("Build ONLY this feature, IN THE SHARED FRAME given. Use the "
                       "absolute position + operation provided — do NOT change any shared "
                       "anchor. Use lookup_primitive(key) for exact param names. Return a "
                       "JSON list of step objects: {id, primitive, operation, parameters, "
                       "position:[x,y,z], orientation:[rx,ry,rz], pattern?}."),
              "feature": feature,            # (B): {"name":"spoke","operation":"union",
                                             #   "position":[0,0,4],"overlap":"span r=14..41",
                                             #   "pattern":"polar count=5"}  — or just the
                                             #   sub-part name for (A) independent solids
              "shared_frame": frame,         # (B) the contract: every shared anchor/radius
                                             #   you fixed. Pass {} for (A).
              "candidate_primitives": candidates,   # 2-5 keys YOU pre-selected, NOT all
          }, STEP_SCHEMA, tools=[lookup_primitive, lookup_design_reference])

      sub_results = await batch_llm_query(*[design(f, c, frame) for f, c in features])

Step 5 — Assemble ONE steps array. If you forked, FLATTEN all child step-lists into
  one list. Enforce: EXACTLY ONE step has operation="base" and it is FIRST (the base
  feature you designated in your contract); every other primitive step is
  union/cut/intersect; FINISH STEPS last. Make ids UNIQUE — if children reused ids,
  prefix each with its feature name (e.g. "spoke_s1"). Children already returned
  ABSOLUTE positions in the shared frame, so do NOT re-place them. Then FINAL with:
    {"action": "plan_ready",
     "plan": {"part_name": <short_name>, "units": "mm", "steps": <all steps>}}

## STEP SHAPES — emit exactly these JSON shapes:

PRIMITIVE STEP:
  {"id": "s1", "primitive": "box", "operation": "base|union|cut|intersect",
   "parameters": {...}, "position": [x,y,z], "orientation": [rx,ry,rz],
   "pattern": {"type":"polar|linear", "count":N, "axis":[0,0,1], "angle_deg":360,
               "spacing":[0,0,0]}}   # pattern OPTIONAL, only on union/cut/intersect

FINISH STEP (no primitive; acts on the whole body so far):
  {"id": "f1", "op": "fillet|chamfer|shell|hole|cbore|csk|mirror",
   "selector": "<edge/face selector>", "value": <number or list>,
   "positions": [[x,y],...], "face": ">Z"}
  • fillet/chamfer: selector = edges (e.g. "|Z" all vertical, ">Z" top), value = radius/length (mm)
  • shell:          selector = face to open (e.g. ">Z"), value = wall thickness (mm)
  • hole:           face = drilled face (">Z"), value = diameter, positions = [[x,y],...]
  • cbore:          value = [clr_dia, bore_dia, bore_depth], positions, face
  • csk:            value = [clr_dia, csk_dia, csk_angle_deg], positions, face
  • mirror:         selector = mirror plane ("XY"/"XZ"/"YZ")

CadQuery selector cheatsheet: ">Z" top face, "<Z" bottom, "|Z" all Z-parallel edges,
"%Circle" circular edges, ">Z[-2]" second-from-top. Wrong selectors just no-op (fillet/
chamfer are skipped if they fail) — pick the obvious one for the edges you mean.

Return EXACTLY one of the two shapes defined by the output schema.
"""


class PlannerOutput(BaseModel):
    """The planner's typed FINAL: either a question for the user, or a plan.

    `action` discriminates. For ask_user, `question` is required (and
    `suggested_options` is encouraged). For plan_ready, `plan` is required.
    """

    model_config = ConfigDict(extra="forbid")

    action: Literal["ask_user", "plan_ready"]
    question: str | None = None
    suggested_options: list[str] = Field(default_factory=list)
    plan: PrimitivePlan | None = None

    @model_validator(mode="after")
    def _fields_match_action(self) -> PlannerOutput:
        if self.action == "ask_user":
            if not self.question:
                raise ValueError("action 'ask_user' requires a non-empty 'question'")
        elif self.action == "plan_ready":
            if self.plan is None:
                raise ValueError("action 'plan_ready' requires a 'plan'")
        return self


def parse_planner_result(result: dict[str, Any]) -> PlannerOutput:
    """Validate a fast-rlm FINAL dict into a PlannerOutput (raises on mismatch)."""
    return PlannerOutput.model_validate(result)


def build_planner_query(
    original_prompt: str,
    chat_history: list[dict[str, str]],
    *,
    available_primitives: list[str] | None = None,
    kb_index: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the structured context dict handed to the RLM for one turn.

    available_primitives + kb_index are pre-fetched by run_planner_turn and embedded
    here so the planner can skip the list_primitives()/list_kb_index() REPL steps —
    two fewer model calls per turn. Omitted (None) → the planner falls back to the
    tools (used by pure unit tests that don't pre-fetch).
    """
    query: dict[str, Any] = {
        "task": PLANNER_TASK,
        "original_prompt": original_prompt,
        "chat_history": chat_history,
    }
    if available_primitives is not None:
        query["available_primitives"] = available_primitives
    if kb_index is not None:
        query["kb_index"] = kb_index
    return query



def run_planner_turn(
    original_prompt: str,
    chat_history: list[dict[str, str]],
    *,
    backend_url: str,
    config: RLMConfig | None = None,
) -> PlannerOutput:
    """Run one planner turn against the RLM and return its typed decision.

    Args:
        original_prompt: The user's first request.
        chat_history: Prior turns as [{"role": "user"|"planner", "content": str}].
        backend_url: Base URL of the product backend, injected into the REPL as
            DTCM_BACKEND_URL so the pull tools can reach it.
        config: Optional fast-rlm RLMConfig; defaults to rlm.rlm_config.config.

    Returns:
        A PlannerOutput — action="ask_user" (question + options) or
        action="plan_ready" (validated PrimitivePlan).
    """
    import os

    import fast_rlm

    if config is None:
        from rlm.rlm_config import config as default_config

        config = default_config

    # Pre-fetch the catalog + KB menu ONCE (localhost HTTP) and embed them in the
    # context, so the planner skips the list_primitives()/list_kb_index() REPL steps
    # — two fewer model calls per turn (each call is a stall risk). The pull tools
    # read DTCM_BACKEND_URL from the env, so set it here before calling. On any
    # failure we pass None and the planner falls back to the tools.
    os.environ["DTCM_BACKEND_URL"] = backend_url
    try:
        available_primitives: list[str] | None = list_primitives()
    except Exception:
        available_primitives = None
    try:
        kb_index: dict[str, Any] | None = list_kb_index()
    except Exception:
        kb_index = None

    result = fast_rlm.run(
        build_planner_query(
            original_prompt,
            chat_history,
            available_primitives=available_primitives,
            kb_index=kb_index,
        ),
        config=config,
        tools=_PLANNER_TOOLS,
        output_schema=PlannerOutput,
        env_variables={
            "DTCM_BACKEND_URL": backend_url,
        },
    )
    return parse_planner_result(result["results"])


REPLANNER_TASK = """\
You are a single-purpose FORK-AND-RETURN agent: spawned by the geometry workflow to
fix ONE failed PrimitivePlan and return the corrected plan to your parent. You are
isolated (no tools, fresh context) and you speak only to the parent that spawned you.

The failure details and the prior plan are in chat_history (the last system message).
Your job:

1. Read the failure message in chat_history[-1]["content"].
2. Identify which parameter(s) caused the failure.
3. Call FINAL immediately with the corrected plan_ready — change only what is broken.
   OR call FINAL with ask_user if fixing requires information only the user can provide.

Rules:
- Do NOT call any tools (no list_primitives, no lookup_primitive, no web_search).
- Do NOT re-derive the plan from scratch — keep all correct steps unchanged.
- Change the minimum needed to fix the reported failure.
- Emit FINAL in your very first REPL block. No intermediate steps.
"""


def run_replanner_turn(
    original_prompt: str,
    chat_history: list[dict[str, str]],
    *,
    config: RLMConfig | None = None,
) -> PlannerOutput:
    """Run one replan turn — no tools, immediate FINAL, used after geometry failure.

    Unlike run_planner_turn this gives the model NO tools. It just sees the
    failure message in chat_history and must emit a corrected plan or ask_user
    in a single REPL step.  No tool calls = no timeouts = fast replan.
    """
    import fast_rlm

    if config is None:
        from rlm.rlm_config import config as default_config
        config = default_config

    query = {
        "task": REPLANNER_TASK,
        "original_prompt": original_prompt,
        "chat_history": chat_history,
    }
    result = fast_rlm.run(
        query,
        config=config,
        tools=_PLANNER_TOOLS,
        output_schema=PlannerOutput,
    )
    return parse_planner_result(result["results"])
