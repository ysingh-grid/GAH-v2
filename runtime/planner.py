"""Per-turn RLM planner: one user message in, one typed decision out.

The backend re-invokes `run_planner_turn` on every user message with the full
chat history. The RLM either asks one more clarifying question (gathering
measurements, optionally via web_search) or, once it has enough, emits a
validated PrimitivePlan. That two-way decision is the `PlannerOutput` model
below, used as the fast-rlm `output_schema` so the model's FINAL value is
schema-checked before we ever see it.

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
    web_search,
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
    web_search,
]

PLANNER_TASK = """\
You are the PLANNER ORCHESTRATOR in a text-to-CAD system. You turn a request into ONE
validated PrimitivePlan: an ordered list of CSG steps, each a placed library primitive
with an operation (base / union / cut / finish), parameters, position, and orientation.

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
  every feature must overlap something already attached.
- NO `finish` operation. The compiler supports ONLY base / union / cut. For rounded
  or chamfered edges use the filleted_box / chamfered_box / rounded_cylinder PRIMITIVES
  (operation union/base/cut) — never emit operation="finish".

## ⛔ Prohibitions:
- NEVER call web_search unless the user EXPLICITLY asked you to search in chat_history.
- Do NOT invent fastener/standard dimensions — look them up (see Step 2).
- Keep REPL output small: never print the whole catalog or whole reference back.

## When to FORK vs design in ONE context — READ THIS, it decides quality:
A FORK (sub-agent) is ONLY for a GENUINELY SEPARATE SOLID — a distinct physical body
that could be manufactured on its own and only meets others at an interface.
  • cricket bat -> ["blade", "handle"]   (two separate solids)  -> FORK each
  • bolt + nut  -> ["bolt", "nut"]                              -> FORK each
A SINGLE complex part with interdependent FEATURES (holes, ribs, bosses, pockets,
fillets on ONE body) is NOT multiple sub-parts. Its features share one coordinate
frame and must be positioned relative to each other. Fragmenting them across blind
sub-agents (who never see each other) produces features that don't line up.
  • flanged manifold, bracket with bolt pattern, housing with ribs -> ONE context.
RULE: if sub-parts share a body / must align to each other -> DESIGN IN ONE CONTEXT
(do it yourself across your REPL steps, no fork). Fork ONLY truly independent solids.

## Procedure — follow in order:

Step 1 — In ONE block, get the catalog and the KB menu:
  primitives = list_primitives()   ← shape catalog
  kb_index = list_kb_index()       ← compact menu: {cadquery: {slug: desc}, forgecad: {slug: desc}}
  print(primitives, kb_index)      ← never print full catalog; just skim it

Step 2 — Based on the request and the kb_index you just read, fetch ONLY the
  KB sections that are actually relevant. Pick ≤5 slugs. Examples:
    • User wants a mug → fetch ["3d-primitives", "modification", "revolve", "shell"]
    • User wants a bracket with holes → fetch ["3d-primitives", "holes", "multi-point"]
    • Simple box → fetch ["3d-primitives"] only — don't over-fetch
  kb = fetch_kb_sections(["slug-1", "slug-2", ...])

  IMPORTANT: kb tells you what the DETERMINISTIC COMPILERS support.
  The plan schema ONLY supports: operation = base / union / cut.
  There is NO finish operation at compile time. For rounded edges, use
  filleted_box / chamfered_box / rounded_cylinder PRIMITIVES instead.
  Do NOT plan fillet/shell/hole as plan steps — the compilers will reject them.

Step 3 — Read context["original_prompt"]. For any standard feature (bolt/screw holes,
  counterbores, bolt circles, ribs, mounting plates) call:
      ref = lookup_design_reference("<the feature + size, e.g. 'M6 counterbored holes'>")
  Use ref["fastener_dims"] for exact hole diameters (clearance/tap/cbore, in mm) and
  ADAPT ref["recipes"][name]["steps"] — fill the <...> placeholders with real mm values
  and positions, then inline them. Adapting a recipe beats composing CSG from scratch.
  If a REQUIRED dimension is still missing and no sensible default exists, FINAL with
  action="ask_user" NOW. Offer: (a) "Search the web for standard {name} dimensions",
  (b) a concrete default you suggest.

Step 4 — Decide structure with the FORK rule above.
  • ONE coherent part (the common case): build the steps yourself. Start with the
    base solid (operation="base"), then union/cut features (adapted recipes). For
    rounded/chamfered edges pick a filleted_box / chamfered_box / rounded_cylinder
    PRIMITIVE — there is no finish op. Keep every feature in the same coordinate frame.
  • Multiple independent solids ONLY: fork one sub-agent per solid, IN PARALLEL, with
    batch_llm_query (NEVER asyncio.gather — the engine blocks it). Give each child a
    SHORTLIST of candidate primitives (not the whole catalog) and tools=[lookup_primitive,
    lookup_design_reference]:

      STEP_SCHEMA = {"type": "array", "items": {"type": "object"}}

      def design(part, candidates):
          return llm_query({
              "task": ("Design ONE independent solid. Use lookup_primitive(key) for exact "
                       "parameter names and lookup_design_reference(q) for standard dims/"
                       "recipes. Return a JSON list of step objects: {id, primitive, "
                       "operation, parameters, position:[x,y,z], orientation:[rx,ry,rz]}."),
              "sub_part": part,
              "request": context["original_prompt"],
              "candidate_primitives": candidates,   # 2-5 keys YOU pre-selected, NOT all
          }, STEP_SCHEMA, tools=[lookup_primitive, lookup_design_reference])

      sub_results = await batch_llm_query(*[design(p, c) for p, c in parts_with_candidates])

Step 5 — Assemble ONE steps array. Exactly ONE step has operation="base" and it is
  FIRST. Unique ids. Then FINAL with:
    {"action": "plan_ready",
     "plan": {"part_name": <short_name>, "units": "mm", "steps": <all steps>}}

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


def build_planner_query(original_prompt: str, chat_history: list[dict[str, str]]) -> dict[str, Any]:
    """Assemble the structured context dict handed to the RLM for one turn."""
    return {
        "task": PLANNER_TASK,
        "original_prompt": original_prompt,
        "chat_history": chat_history,
    }


def _user_granted_web_search(chat_history: list[dict[str, str]]) -> bool:
    """True iff the user's MOST RECENT message explicitly granted web access.

    The planner offers a "Search the web for ..." option on an ask_user turn;
    clicking it sends that text back as a user message. We grant web access only
    for the turn right after the user says so — never speculatively, never carried
    forward. This is what flips DTCM_WEB_SEARCH_ALLOWED for the web_search gate.
    """
    for turn in reversed(chat_history):
        if turn.get("role") == "user":
            return "search the web" in turn.get("content", "").lower()
    return False


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
            DTCM_BACKEND_URL so the pull tools (incl. web_search) can reach it.
        config: Optional fast-rlm RLMConfig; defaults to rlm.rlm_config.config.

    Returns:
        A PlannerOutput — action="ask_user" (question + options) or
        action="plan_ready" (validated PrimitivePlan).
    """
    import fast_rlm

    if config is None:
        from rlm.rlm_config import config as default_config

        config = default_config

    result = fast_rlm.run(
        build_planner_query(original_prompt, chat_history),
        config=config,
        tools=_PLANNER_TOOLS,
        output_schema=PlannerOutput,
        env_variables={
            "DTCM_BACKEND_URL": backend_url,
            # Permission gate for web_search: only "1" when the user's latest
            # message explicitly granted web access. The tool raises otherwise.
            "DTCM_WEB_SEARCH_ALLOWED": "1" if _user_granted_web_search(chat_history) else "0",
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
        tools=[],  # no tools — fix the plan directly from the failure message
        output_schema=PlannerOutput,
    )
    return parse_planner_result(result["results"])
