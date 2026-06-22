# IMPROVEMENTS

PRD-driven verification log. Each entry: what the PRD claims, what the code
actually does, the gap, and the concrete betterment. No fixes applied yet —
this is the backlog from the section-by-section audit.

---

## PRD §01 — Executive Recommendation / "Thinking in 3D" verifier

**Audited:** `tools/verify_geometry.py`, `runtime/loop.py` (`_run_verify`, `_merge_metrics`)

### Finding 1 — No deterministic dimension gate (LLM judges everything)

- `verify_geometry` pastes kernel metrics as **text** into the Gemini prompt
  (`verify_geometry.py:108`). There is **zero code-side reconciliation** of
  measured vs. requested dimensions — no `if bbox_x != requested_x: fail`.
- Split today:
  - **Mesh validity** = genuinely deterministic-gated (`loop.py:131` gates on
    `inspect_mesh.passes` — watertight/manifold) ✅
  - **Dimensional / intent correctness** = **LLM-judged only** ❌
- `_merge_metrics` (`loop.py:65`) never passes the **requested** dimensions into
  `metrics`, so even in principle Gemini must re-extract target dims from raw
  prompt prose and eyeball-compare. No structured target → no deterministic
  check possible today.
- **PRD conflict:** §04 "images alone are not enough" wants kernel numbers as a
  **hard gate**; code makes them advisory text to a vision model. Undermines the
  §11 ">80% valid first-pass" metric by leaving size-correctness to LLM variance.

### Finding 2 — 🔴 Mock fallback is a silent-failure generator

- `verify_geometry.py:47-53`: missing `GEMINI_API_KEY` → `{"passed": True}`.
- In `run_geometry_loop` this returns **`status="success"`** with a trace that
  claims verified. A keyless run "passes" every part with zero verification.
- **PRD conflict:** §11 headline gate = **"0 Silent Geometry Failures."** This
  mock path is literally a silent-failure factory. Fail-safe is inverted:
  missing verifier should fail-**closed**.

### Finding 3 — Fail-closed elsewhere is correct (context)

- Parse errors (`verify_geometry.py:175`) and judge exceptions (line 221) both
  return `passed: False` — correct fail-closed behavior. Only the **mock key
  path** fails-open. Tell that it was a dev shortcut that leaked into prod
  semantics.

### Betterments (ordered by value)

- **A. Deterministic pre-gate** — new `runtime/verify_metrics.py`, run BEFORE the
  Gemini call. Plan already carries target dims (`PrimitivePlan`). Compute
  expected bbox/volume from the plan, assert actual within tolerance, fail
  `geometry_invalidity` deterministically. Vision becomes the tiebreaker for
  shape/intent, not the sole arbiter of size. **Highest-value change.**
- **B. Mock path fail-closed** — add a distinct `LoopResult.status = "unverified"`
  (separate from `success`), or return `passed: False`. Never emit `success`
  without a real verdict.
- **C. Pass target dims into `metrics`** — even keeping the LLM judge, hand it
  `{"requested": ..., "actual": ...}` pairs so it reconciles instead of guessing
  the target from prose.

### Claim-vs-maturity notes (design-review honesty)

- Exec summary sells "training data"; §14/roadmap correctly defers fine-tuning.
  Reword exec summary to "evaluation data now, training data later" to match what
  is built (`eval/` exists; no training pipeline does).
- "Thinking in 3D" currently rests on ONE single-shot Gemini call + a flat
  metrics dict. `render_views` makes 3 views but they collapse into one PNG to
  one judge call — no multi-view cross-consistency, no self-consistency sampling.

---

## PRD §02 / §03 — Business Context + Recommended System Shape

**Audited:** `primitives/library.json`, `runtime/schema.py`, `tools/inspect_mesh.py`,
`tools/verify_geometry.py`, `temporal/workflow.py`, `eval/eval_compare.py`

### Backed clean ✅

- CadQuery=authority, MeshLib=inspection, ForgeCAD=handoff, Temporal=coarse
  stages — all enforced in code, not just asserted.
- Agent Evaluation Platform pillar real (`eval/eval_compare.py` baseline-vs-run
  f1 scoring).

### Finding 1 — 🔴 "Semantic primitives" are actually GEOMETRIC primitives

- PRD §03 GRT: "typed primitives such as mounting plates, holes, ribs,
  clearances, mates, fillets, fixtures." Built (`library.json`, 20 keys): pure
  geometric shapes — box, cylinder, cone, sphere, torus, wedge, pyramid, prism,
  hexagon_prism, octagonal_prism, hollow_cylinder, hollow_box, ellipsoid,
  capsule, chamfered_box, filleted_box, rounded_cylinder, ring, profile_extrude,
  revolve. Operations: base/union/cut/finish + pattern (`runtime/schema.py:37`).
- Named-feature reconciliation:
  - hole → not a primitive; `cut` op + cylinder recipe
  - fillet/chamfer → ✅ `finish` op (general)
  - rib → `union` of thin box (expressible, not semantic)
  - mounting_plate → box + patterned `cut` (multi-step recipe)
  - clearance → ❌ ABSENT (and it is *in* single-part scope)
  - mate → ❌ absent (assembly; out of single-part scope — defensible)
  - fixture → ❌ absent
- The agent emits "cut a cylinder", never "add an M6 hole." No semantic
  vocabulary, only geometric CSG. Matches locked grilled-design decision #9
  (CSG + escalate organic to `primitive_gap`) — deliberate — but PRD §02/§03
  language still oversells "semantic." 
- **Betterment (real industry value):** add a thin semantic-recipe layer on top
  of the geometric library — `mounting_plate`, `hole`, `rib`, `boss`, `slot` as
  named composite recipes that expand to CSG steps. This is what makes it a "CAD
  agent" vs a "CSG script generator." Alternatively, reword PRD to "geometric
  primitive + CSG operation layer" to match what is built. Pick one — the
  claim/build mismatch is the design-review honesty risk.

### Finding 2 — "Tool Portability" pillar half-violated

- §02 claims semantics above "any mesh library, or model provider."
- **Mesh library ❌** — `inspect_mesh.py:12` MeshLib-only, no fallback,
  "per design". Hard-coupled. Contradicts pillar (deliberate decision #7) — PRD
  and locked decision disagree; reconcile the wording.
- **Model provider ⚠️** — planner provider-swappable (fast-rlm/OpenRouter), but
  `verify_geometry` hardcodes Gemini (`from google import genai`). Verifier not
  provider-portable.
- **Betterment:** extract a `Verifier` protocol so the judge provider is
  swappable like the planner is; either add a MeshLib adapter seam or soften the
  PRD portability claim to "above any editor or kernel."

### Finding 3 — "Risk Containment" approval gate appears UNIMPLEMENTED

- §02 pillar + §06 `approval_gate` + §10 `SIGNAL /approve`. No `@workflow.signal`
  / approval handler in `temporal/workflow.py` (grep → only `_NO_RETRY`). Only
  HITL is planner `ask_user` (clarification, not manufacturing approval).
- The policy/approval gate for risky exports is absent. Risk-containment pillar
  currently unbacked.
- **Betterment:** add a `@workflow.signal approve(decision)` + a wait-for-signal
  gate before export when a risk flag is set; expose via the §10 `/approve`
  endpoint. (MVP roadmap §12 weeks 5-8 lists "approval signals" — confirm
  whether deferred or dropped.)

### Note — "Durable Workflows / retries"

- All activities use `_NO_RETRY`. The pillar's "retries" is handled at the
  loop/replan level, NOT Temporal retry. Defensible (geometry failures should
  replan, not blind-retry) but pillar wording implies Temporal-level retry it
  does not do.

---

## PRD §03 Diagram 03.1 — High-Level Architecture (5 durable boxes)

**Audited:** `temporal/workflow.py`, `temporal/shared.py` (DesignStage),
`backend/designs/routes.py`, `backend/designs/runner.py`

### 🔴 Finding 1 — "HITL wait" is drawn but architecturally absent (headline)

- Diagram box 3 footer: "durability · retry · HITL wait"; drawn `approve` stage.
- Reality: **zero `workflow.wait_condition`, zero `@workflow.signal`, zero
  `approve`** anywhere in `temporal/`. On `ask_user` the workflow writes a trace
  and `return`s `needs_user` (`workflow.py:168-178`) — it **terminates**. The
  clarification answer must start a BRAND-NEW workflow, losing the durable
  continuity Temporal exists to provide.
- This matters most because durable HITL pause is the whole reason Temporal is
  in the stack. A true gate would be `@workflow.signal provide_answer(...)` +
  `await workflow.wait_condition(...)`. None exists.
- **Betterment:** implement a real durable HITL pause — signal handler +
  wait_condition for both clarification (`needs_user`) and the missing manufacturing
  `approve` gate. Otherwise drop "HITL wait"/`approve` from the diagram and
  document the chat-socket model as the intended design.

### Finding 2 — PRODUCT API is WebSocket-chat-driven, not signal/query-driven

- Diagram: "signals · queries · evidence". Built (`routes.py`): only
  `POST /designs` (201), `GET /designs/{id}`, `WS /designs/{id}/chat`.
- No signal endpoints (§10 `/iterate`, `/approve`, `/params`), no query endpoints
  (`/status`, `/code`, `/evidence`), no `/export`. The WS chat streams progress
  (replaces queries) and carries user turns (replaces signals).
- Reasonable simplification, but the drawn Temporal signal/query machinery (and
  all of §10) is superseded by a chat socket. Reconcile diagram + §10 with the
  WS-driven reality, or build the REST signal/query surface.

### Finding 3 — `export` and `emit`-as-stage absent; inspect/repair bundled

- `export` stage/endpoint: absent entirely.
- `emit` (.forge.js): produced inside `generate_activity` (parallel compile),
  returned in DesignResult — exists but not a distinct stage.
- `INSPECTING` / `REPAIRING` defined in DesignStage enum but never set on
  `self._stage` (they happen inside `generate_activity`), so the `current_stage`
  query never surfaces them. Vocabulary exists, observability not wired.
- **Betterment:** either split inspect/repair into their own activities for the
  timeline granularity the diagram promises, or remove them from the enum to stop
  implying observability that is not delivered.

### Positives (keep)

- Workflow mirrors `run_geometry_loop` (same caps, same inner/outer counting) —
  honest parity, with `_run_in_process` fallback.
- `current_stage` query → live UI streaming is real.
- Trace written on EVERY terminal path (success/failed/needs_user).

---

## PRD §03 Diagram 03.2 — Low-Level Runtime Turn Anatomy

**Audited:** `runtime/planner.py` (`build_planner_query`, `_PLANNER_TOOLS`),
`backend/designs/runner.py`, `tools/verify_geometry.py`, `rlm/pull_tools.py`,
`runtime/loop.py`

### 🔴 Finding 1 — INPUT CONTEXT is 1/5; the RLM is starved (headline)

- Diagram lists 5 context streams loaded as REPL variables: design prompt,
  project constraints, ForgeCAD examples, previous traces, target review rubric.
- Actual `build_planner_query` = `{task, original_prompt, chat_history}`. Only
  design prompt is genuinely present.
- Rich context-as-variables is the WHOLE reason to use an RLM over a plain LLM
  call (fast-rlm thesis: explore an arbitrarily long prompt programmatically).
  Handed a one-line prompt, there is nothing to explore.
- Two absences hurt most:
  - `previous traces` = the flywheel's memory. Traces are WRITTEN (§14) but
    NEVER read back into planning. `load_trace`/`list_traces` exist, unused at
    plan time. The "feedback enriches future attempts" arc (Diagram 03.1) is not
    wired into planner input.
  - `target review rubric` appears in TWO boxes (input + verifier) and threads to
    NEITHER. `verify_geometry` has no rubric param.
- **Betterment (high value, cheap):** feed top-K relevant `previous traces` + a
  structured `rubric` into `build_planner_query` as RLM variables. Makes the RLM
  actually be an RLM, realizes the §14 flywheel claim, gives few-shot grounding
  to lift the ">80% first-pass" metric. Read tools already exist.

### Finding 2 — "grep docs · parse examples" no longer happens

- `read_skill`/`list_skills` exist in `pull_tools.py` but are NOT in
  `_PLANNER_TOOLS` (= list_primitives, lookup_primitive, web_search). Deliberately
  pulled (fork-and-return perf: sub-skill cascade blew the budget). Legitimate,
  but diagram still advertises doc-grep/example-parsing the planner can't do.
  Reconcile diagram with code.

### Finding 3 — intent rubric + exports drawn, absent

- `intent rubric` (3D VERIFIER box): no rubric param in `verify_geometry`.
- `exports` (EMIT+REVIEW box): no export pack/stage (consistent with §03 Finding 3).

### Backed faithfully ✅

- GEOMETRY TOOLS measure·collide·watertight·render — all present
  (`self_intersections` = collide).
- REPAIR LOOP 3 branches + loopback to plan — exact match to `loop.py`.
- STATE / DURABILITY / HANDOFF property boxes — backed.
- REASONING "not screenshot-only" — true, but measurements are advisory text to
  the judge, not a deterministic gate (see §01 Finding 1).

---

## PRD §04 — Spatial Reasoning ("Thinking with Images, Extended into 3D")

**Audited:** `tools/inspect_mesh.py`, `runtime/planner.py` (`run_replanner_turn`,
REPLANNER_TASK, tools=[]), `runtime/loop.py`, `tools/verify_geometry.py`

### 🔴 Finding 1 — The repairing agent is BLIND; only the judge sees (headline)

- PRD §04 frames ONE agent that "plans with semantic primitives, observes
  rendered views and raw geometry evidence, repairs failures." Reality = TWO
  agents bridged by a text string:
  - PLANNER emits plan blind (no geometry yet).
  - HOST loop runs CadQuery/MeshLib/render.
  - VERIFIER (Gemini) SEES the 3-view PNG + metrics → pass/fail + prose feedback.
  - REPLANNER (`run_replanner_turn`, tools=[]) gets ONLY `failure_detail` STRING
    → fixes the plan. It never sees the render or the metrics dict.
- The entity that sees (judge) does not design; the entity that revises (replanner)
  is fixing geometry it cannot observe. Lossy text channel caps repair quality.
- Same root cause as §01 (metrics advisory) and §03-diagram-02 (planner starved):
  evidence is COMPUTED then NOT ROUTED to the deciding agent.
- "Thinking in 3D" is half-true: verification fuses images+measurements;
  design/repair does neither (text-in, plan-out).
- **Betterment:** make replan evidence-bearing — hand `run_replanner_turn` the
  structured metrics dict (minimum) + render PNG (ideal; fast-rlm/Gemini is
  multimodal). Replanner observes the failure instead of reading a summary.
  Compounds with the §04 trace-feedback fix.

### Finding 2 — "Raw Geometry Evidence" 8 claimed, ~4.5 delivered

- inspect_mesh returns: dimensions ✅ (bbox/volume), topology ⚠️ (counts only —
  faces/verts/components, no adjacency), intersections ✅ (self_intersections),
  watertightness ✅, mesh defects ✅ (open_holes+self_intersections).
- ABSENT: proximity ❌ (needs 2+ bodies — out of single-part MVP scope,
  defensible), normals ❌ (MeshLib supports; not wired — cheap add),
  **face references ❌** (faces_count is a COUNT, not addressable face IDs/handles).
- face references is the important gap: addressable faces enable feature-based
  editing + ForgeCAD `.onFace()` handoff. System has triangle counts, not handles.
- **Betterment:** wire normals (cheap); decide whether face-addressability is in
  scope — if the ForgeCAD editable-handoff promise (§HANDOFF) is to be real,
  face references matter. Reconcile the 8-item claim with MVP scope otherwise.

---

## PRD §05 — Geometry Ownership (canonical state boundaries)

**Audited:** restatement of §01-§05 — no new code; reconciled against confirmed
evidence in `loop.py`, `workflow.py`, `inspect_mesh.py`, `eval/`.

### Positive — this is the project's best-executed idea ✅

- The boundary model is genuinely enforced, not just asserted: CadQuery owns
  solids, MeshLib owns mesh evidence, ForgeCAD is non-authoritative handoff,
  Temporal owns coarse stages. The anti-pattern it guards ("editor code/images/
  meshes/solids as interchangeable truth") is actually prevented in code.
- Semantic Plan row strongest: `PrimitivePlan` validated+traced (auditable) +
  dual-compile cadquery+forge (portable).

### Finding 1 — "approval" claimed as owned state in THREE rows, unbacked in all

- Design Intent ("user approval state"), Rendered Views ("human approval"),
  Durable State ("approval waits, signals") — no `@workflow.signal`, no
  `wait_condition` (§02/§03). The table assigns a canonical owner to a state with
  no implementation. Third surfacing of the approval gap.

### Finding 2 — scope-wording overclaims (not architecture)

- "feature generation" (CadQuery row): CSG, not feature-based modeling — no
  semantic features (§02).
- "proximity" (MeshLib row): not computed; single-part has no proximity (§05).

---

## RECURRING ROOT CAUSE (cross-section theme)

Confirmed 3×+ (§01 verifier, §03-diagram-02 planner input, §04 spatial reasoning):
**evidence is COMPUTED but NOT ROUTED to the deciding agent.**
- Metrics computed → pasted as advisory text to judge, never a deterministic gate.
- Traces written → never read back into planning.
- Render + metrics seen by judge → only a prose string reaches the replanner.
Single highest-leverage systemic fix: route structured evidence (metrics dict,
top-K traces, render) INTO the planning/repair/gate decision points.

Second recurring theme: **the Temporal orchestration shell is under-built vs the
PRD** — no HITL wait, no signals, no approval gate, no export. The system is
WebSocket-chat-driven; the durable-pause value prop of Temporal is unrealized.

The PURE GEOMETRY LOOP (plan→compile→execute→inspect→repair→render→verify→replan,
bounded caps, always-traced) is solid and honestly built. Gaps cluster in the
ORCHESTRATION + EVIDENCE-ROUTING shell around it.

---

## PRD §06 — Runtime Contract (10 runtime primitives)

**Audited:** `tools/render_views.py`, `tools/repair_mesh.py` + prior tool reads.

### 🔴 Finding 1 — render_views is 3/6, and the missing views are the critical ones

- Claims "front, side, top, isometric, section, exploded" (6). Reality: 3 views —
  iso, high_rear, front (`render_views.py:7-9`). No side, top, SECTION, or EXPLODED.
- Section view is the load-bearing absence: it's how internal geometry (bores,
  shells, cavities) is verified. Directly explains the §01 verifier weakness — the
  judge CANNOT prove internal features because no section cut is rendered. Solid
  block vs hollow shell look identical in exterior views; only a section reveals it.
  The "false convergence" risk the validator prompt itself warns about is
  structurally unaddressable with 3 exterior views.
- **Betterment (high value, ties §01):** add a section view (CadQuery/VTK clip
  plane) to render_views. Single rendering change that lets the verifier catch
  hollow-vs-solid + internal-feature failures.

### 🔴 Finding 2 — mesh_repair has NO policy gate; auto-runs structural remesh

- "without hiding failed design intent" ✅ genuinely implemented (actions[] list,
  before/after returned).
- "policy gates" (backing column) ❌ absent. `fixSelfIntersections` voxel remesh
  (`repair_mesh.py:60`) runs AUTOMATICALLY with no gate — exactly the "non-trivial
  geometry change" PRD §13 says to "require human review for." Structural repair
  can silently change the part; loop accepts if `passes`. Same approval-gate gap.
- **Betterment:** add a repair policy gate — volume-delta threshold + structural
  repairs route to the (missing) human approval gate per §13.

### Finding 3 — tool-level overclaims (catalog)

- mesh_inspect: normals ❌, clearances ❌ (§05).
- measure_geometry: not a standalone tool (folded into exec+inspect); face refs ❌,
  tolerance evidence ❌.
- visual_verify: rubric ❌ (§04).
- forgecad_emit: review notes ❌, exports thin.
- approval_gate: explicitly "Temporal Signal" — does not exist (5th surfacing).

### Backed ✅

- primitive_plan, solid_generate, trace_capture fully backed.

---

## PRD §07 — MVP Loop (minimum viable workflow)

**Audited:** grep across runtime/backend/rlm (zero matches for requirements/risk/
review-evidence/extract); `skills/` dir; `runtime/planner.py`.

### 🔴 Finding 1 — MVP incomplete by its OWN definition

- Section lists 5 required MVP surfaces: language-to-geometry, deterministic
  inspection, visual reasoning, editable output, AND HUMAN APPROVAL.
- Score: 4/5. Human approval ❌ not built. Approval is a REQUIRED MVP surface here,
  not a weeks-9-12 expansion. The approval gap (surfaced 6× now) becomes
  MVP-incomplete per the document itself.

### 🔴 Finding 2 — Step 01 requirements extraction does not exist

- No code extracts dimensions/constraints/assumptions/manufacturing_risk/
  review_evidence into a structured artifact. Planner reads raw prompt, forks
  straight to part-design.
- Chains through whole audit: manufacturing_risk never captured → nothing triggers
  an approval gate even if built; review_evidence/rubric never captured → origin of
  the §04/05/07 missing-rubric gap.
- **Betterment (one artifact closes four gaps):** add a Step-01 extraction emitting
  `Requirements{dims, constraints, assumptions, manufacturing_risk, rubric}`. Feeds
  the missing rubric (§04/05/07), the missing approval trigger (risk→gate), AND
  gives the RLM real context to explore (§04 starvation).

### Finding 3 — all 8 skills are orphaned at plan-time

- `skills/` has 8 guides (intent_extraction, dimension_reasoning, primitive_planning,
  …). `read_skill`/`list_skills` pulled from `_PLANNER_TOOLS` (§04); PLANNER_TASK
  inlines the procedure. Live planner cannot reach ANY skill. `intent_extraction.md`
  (which would do Step 01) is unreachable. Dead weight — re-wire or remove.

### Backed ✅

- Steps 02 (validated plan), 03 (CadQuery + trace) fully backed. Steps 04-05 backed
  with the inspection/verifier caveats already logged (§01/§05/§07).

---

## PRD §08 Diagram 08.1 — Worker Boundaries (queues, workers, gates)

**Audited:** `temporal/worker.py`, full-repo grep for run_forgecad /
compile_plan_to_forge callers.

### 🔴 Finding 1 (SHARPEST) — translation-drift gate is DEAD CODE

- `run_forgecad` (forgecad `run` + `compare 3d` gate) has ZERO production callers
  (grep: only tools/__init__.py export + tests/). Never executes in pipeline.
- `compile_plan_to_forge` IS wired (loop.py:94, runner.py:268) → .forge.js emitted
  but NEVER validated (no JS-run check, no geometric compare vs canonical solid).
- Live risk, mitigation switched off:
  1. Decision #6 dual-template compiles CadQuery + ForgeCAD from TWO separate
     template sets. If they disagree, user gets editable code that doesn't match
     the verified solid.
  2. §13 lists CadQuery→ForgeCAD translation drift as HIGH risk; `compare 3d` is
     THE designed mitigation; `run_forgecad` implements it; nothing calls it.
  3. `FailureCategory.translation_drift` can only fire from CompileForgeError
     (template string error), NEVER from real geometric drift.
- Handoff is emit-and-pray. test_run_forgecad.py passes → false sense of security.
- **Betterment (HIGH, smallest diff/highest risk-reduction in backlog):** wire
  `run_forgecad(forge_js, run_id, reference_stl=<canonical STEP/STL>)` as a stage
  after a verified solid, gate handoff on `compare_passed`. Tool + threshold(90) +
  failure routing (forge_compile→translation_drift) already exist; just call them.

### 🔴 Finding 2 — 1 worker / 1 queue vs 5 drawn

- worker.py = single Worker(task_queue="design", workflows=[DesignWorkflow],
  activities=[all]). Diagram shows 5 queues + 5 workers.
- Deferred per §12 weeks 9-12 (aspirational, not a bug). BUT consequence: §14
  "model tiering via task queues" (cheap planner / frontier verifier per-queue) is
  UNBUILDABLE on one-worker topology. Diagram = target, code = MVP-collapsed.

### Finding 3 — worker-card claims that don't hold

- W·01 "FAILURE: retry or gate" — gate ❌ (approval, 7th surfacing).
- W·04 Verifier "escalate to human review" — no escalation; returns needs_user
  terminally (§03).
- W·05 ForgeCAD Adapter "FAILURE translation drift" — no detection (Finding 1).
- PRODUCT API "prompt · rubric · approval policy" — neither passed (§04/§02).

---

## PRD §09 — State & Durability

**Audited:** prior reads of workflow.py, shared.py, trace.py, routes.py.

- Temporal=Stage State: 5/8 (signals ❌, approval decisions ❌; rest ✅).
- Queries=Live Review: only `current_stage` (phase). 1/6 — no preview/score/
  failure/URIs/approval-req query. 🔴
- Signals=Human Control: NONE exist. 0/5. 🔴
- Runtime Trace: attempt-level not per-primitive-call; "verifier scores" = bool,
  not numeric. Backed mostly ✅.
- History Mgmt: by-reference ✅ (paths not blobs); Continue-As-New ❌ (moot for
  bounded single-part loop, but no safety for §09's "long-running explorations").

## PRD §10 — Product API Contract (10 endpoints) — ~1.5/10 BUILT

- Built: POST /designs (no /api/v1; rubric/output-target params ❌); WS
  /designs/{id}/chat (chat, not spec'd /stream).
- ABSENT (8): SIGNAL /iterate, QUERY /status, QUERY /code, QUERY /evidence,
  SIGNAL /approve, SIGNAL /params, GET /trace, POST /export.
- Entire signal+query+trace+export REST surface replaced by ONE chat WebSocket.
  §03 finding quantified: 10-endpoint contract → 2 endpoints + 1 socket.
- **Betterment:** either build the REST signal/query surface (needed for the
  durable HITL + approval work) or formally re-spec §10 to the WS-driven design.

## PRD §11 — Decision Metrics (8 "review gates") — 2 TRUE, 2 FALSE, 4 unenforced

- ✅ ENFORCED: 100% outputs with trace; A/B eval (partial, eval_compare).
- 🔴 FALSE: "0 silent geometry failures" (verifier mock-pass returns success
  keyless, §01); "100% human gates for risky exports" (no gate/export, 8th
  surfacing). THESE ARE THE TWO THE PRD STAKES CREDIBILITY ON ("review gates,
  not marketing claims").
- ⚠️ UNENFORCED: >80% first-pass (LLM-judged, gameable); <2 repairs (caps allow
  up to 7 = inner5+outer2); <5m (engineered via perf commits, never measured live);
  <40k events (no Continue-As-New).
- **Betterment:** make the metrics real gates — (1) fix mock-pass (§01-B) to make
  "0 silent failures" true; (2) build approval gate for "100% human gates"; (3)
  add a metric harness that actually measures first-pass-rate + workflow-time from
  traces, so the numbers are computed not asserted.

---

## AUDIT SUMMARY (PRD §01-§11)

**The pure geometry loop is real, honest, well-tested.** plan→compile(cadquery+
forge)→execute→inspect→repair→render→verify→replan, bounded caps, always-traced,
clean CadQuery/MeshLib/ForgeCAD ownership. This is the project's solid core.

**The gaps cluster in the orchestration + evidence-routing shell**, in priority:

1. 🔴 **Translation-drift gate is dead code** (§08) — `run_forgecad`/`compare 3d`
   built+tested, ZERO production callers; .forge.js emitted unvalidated; HIGH §13
   risk with mitigation switched off. SMALLEST DIFF / HIGHEST ROI: just call it.
2. 🔴 **Verifier mock-pass = silent-failure factory** (§01) — keyless → success;
   breaks the headline "0 silent geometry failures" gate. Fail-closed fix.
3. 🔴 **No approval gate / HITL wait** (§02/03/06/07/08/09/10/11, surfaced 8×) —
   no @workflow.signal, no wait_condition; "100% human gates" = 0%; MVP-incomplete
   per §07's own surface list. Temporal's durable-pause value prop unrealized.
4. 🔴 **Evidence computed but not routed to deciding agent** (§01/04/05) — metrics
   advisory not gated; traces write-only (never read into planning); replanner
   blind (text-only). Add deterministic pre-gate + evidence-bearing replan +
   trace-feedback into planner context.
5. 🔴 **render_views 3/6, no section view** (§06) — verifier structurally cannot
   see internal geometry (hollow-vs-solid). Add a section clip-plane view.
6. ⚠️ **Semantic vs geometric primitives** (§02/03) — library is CSG shapes, not
   the named semantic features (mounting_plate/hole/rib/clearance/mate). Either add
   a semantic-recipe layer or re-word the PRD.
7. ⚠️ **API contract ~1.5/10; 1 worker vs 5; skills orphaned; req-extraction
   absent** — orchestration scaffolding is MVP-collapsed vs the drawn target.

Cheapest high-impact sequence: #1 (wire compare-3d) → #2 (fail-closed mock) →
#5 (section view) → #4 (deterministic pre-gate) → #3 (approval gate + HITL wait).

---

## PRD §13 — Risks & Mitigations (mitigation cross-check)

**Punchline: all 3 HIGH risks have mitigations that are NOT active.** PRD states
mitigations in present tense as if in place.

- HIGH "visual verifier misses geometric failures" — mitigation "pair every review
  with MeshLib/CadQuery evidence" is NOMINAL: evidence is advisory text to the
  judge, not a deterministic gate (§01). Risk LIVE.
- HIGH "CadQuery→ForgeCAD translation drift" — mitigation "translation tests
  comparing ForgeCAD vs accepted geometry" IS the dead code: run_forgecad/compare-3d
  zero callers (§08). Risk UNMITIGATED.
- HIGH "semantic primitives too weak" — schema/validation ✅, but examples =
  orphaned skills (§07) and the risk MATERIALIZED: primitives are geometric not
  semantic (§02).
- MED mesh-repair human-review ❌ (§07); MED Continue-As-New ❌ (§09); MED
  cost-routing/cache ❌ (§08); MED resource-limits/quotas ❌ (but CadQuery runs
  TEMPLATED code not LLM-freestyle → small RCE surface, good structural choice).
- LOW scope-creep ✅ honored.
- The three HIGH risks are the three LEAST mitigated. Reviewer headline.

## PRD §14 — Trace Capture & Evals (flywheel DOUBLY BROKEN)

- "1 trace schema per attempt" is FALSE in implementation:
  - execute_cadquery writes FIXED path outputs/{run_id}/solid.stl; run_id constant
    across loop → each repair attempt OVERWRITES the previous (solid.stl,
    threeview.png clobbered).
  - Trace written ONCE, terminal only (_finalize/_record) → captures only LAST
    attempt's artifacts + total count.
- §14's core value ("failed attempts expose missing primitives/weak verifiers")
  loses the failed-attempt artifacts. Only final attempt survives; intermediate
  failures persist only as feedback strings.
- Combined with §04 (traces never read back into planning): flywheel broken on
  BOTH ends — write-only AND per-run-lossy.
- **Betterment:** trace per-attempt (sub-folder outputs/{run_id}/attempt_N/), persist
  each attempt's plan+code+render+verdict; THEN feed top-K back into planner (§04).
  Closes the flywheel end-to-end.
- Capture gaps: constraints/assumptions ❌ (no extraction §07); annotated failure
  views ❌; human review notes ❌; human approval/export readiness labels ❌.
- Pipeline: Capture ✅, Normalize ⚠️ (compute_metrics_posthoc), Classify ✅ (6-cat),
  Regress ⚠️ (eval_compare), Improve/Fine-tune deferred (honest).

## PRD §15 — Conclusion (repeats the two governing overclaims)

- "exposes semantic primitives" — geometric not semantic (§02).
- "preserving recoverability, approval gates, audit references" — approval gates
  absent (9th surfacing).
- "reliably verify, hand off editable geometry" — verify mock-leaky (§01); handoff
  unvalidated (§08).

---

## CLOSING — what to fix, in order

The pure geometry loop is real and well-built. Every gap is in the orchestration +
evidence-routing + flywheel shell. Ranked by ROI:

1. Wire compare-3d gate (§08) — dead code, HIGH risk, smallest diff.
2. Fail-close verifier mock-pass (§01) — restores "0 silent failures" gate.
3. Add section render view (§06) — lets verifier see internal geometry.
4. Per-attempt tracing + feed top-K traces into planner (§04/§14) — fixes the
   doubly-broken flywheel; the RLM's whole reason to exist.
5. Deterministic dimension pre-gate before the LLM judge (§01) — moves first-pass
   off LLM variance.
6. Approval gate + real HITL wait_condition (§02/03/06/07/09/10/11/13/15, 9×) —
   makes "100% human gates" true + realizes Temporal's durable-pause value.
7. Evidence-bearing replan (§05) — give the replanner metrics+render, not a string.
8. Reconcile or build: semantic-recipe layer (§02), REST signal/query API (§10),
   requirements extraction (§07), re-wire orphaned skills (§07).
