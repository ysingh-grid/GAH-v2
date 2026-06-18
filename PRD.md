Design Review Memo

Engineering Design Review — Architecture Decision Memo

# Geometry AgentHarness

A durable platform for evaluating and building CAD agents that reason with semantic primitives, images, and 3D geometry.

Date
:   May 2026

Audience
:   Engineering Leads

Decision
:   Approve Direction + Surface Risks

Stack
:   RLM + Temporal + CadQuery + MeshLib

Geometry Agent Runtime◇
Thinking with Images◇
Thinking in 3D◇
CadQuery Canonical Solids◇
MeshLib Inspection◇
ForgeCAD Editable Surface◇
Temporal Coarse Stages◇
Geometry Agent Runtime◇
Thinking with Images◇
Thinking in 3D◇
CadQuery Canonical Solids◇
MeshLib Inspection◇
ForgeCAD Editable Surface◇
Temporal Coarse Stages◇

01 — Decision

## Executive Recommendation

Approve the architecture direction, with the condition that geometry reasoning is treated as a first-class runtime capability rather than a thin wrapper around an editor.

This memo refines the original ForgeCAD harness into a **Geometry Agent Harness**: a reusable platform capability for evaluating and building AI agents for CAD workflows. The architecture combines **Recursive Language Models** for context exploration, **Temporal.io** for durable orchestration, and a **Geometry Agent Runtime** where semantic primitives compile to CadQuery, inspection and repair run through MeshLib, and ForgeCAD remains the user-facing editable surface.

The business case is not limited to faster part generation. The platform creates an auditable loop for CAD automation: natural-language intent becomes geometric operations, every attempt produces traces, visual and deterministic checks evaluate quality, and successful traces become reusable evaluation and training data. This is the foundation for safer CAD agents, lower iteration cost, and domain-specific model improvement over time.

The central feasibility risk is spatial reasoning. CAD agents cannot rely on text-only planning or screenshot-only verification. They need **Thinking with Images** and **Thinking in 3D**: a loop where the agent plans with semantic geometry primitives, observes rendered views and raw geometry evidence, repairs failures, and then verifies the final artifact from both visual and deterministic perspectives.

The review question is not whether an LLM can write CAD code once. The question is whether the system can observe, inspect, repair, and explain geometry across repeated attempts.

Design Review Position

---

02 — Business Context

## Why This Platform Exists

The target product capability is a reusable harness for CAD agents: a system that lets teams create, evaluate, audit, and improve agents that design geometry from intent. ForgeCAD is valuable in this architecture because it gives users an editable code-first surface, but the platform value comes from the full loop around it: planning, 3D reasoning, deterministic inspection, durable execution, trace capture, and model improvement.

#### Agent Evaluation Platform

Run repeatable CAD tasks, capture traces, compare model behavior, and score outputs

#### Lower Iteration Cost

Automate routine design attempts while preserving human review for risky outputs

#### Spatial Reasoning

Extend Thinking with Images into multi-view and geometry-aware Thinking in 3D

#### Durable Workflows

Use Temporal to survive crashes, retries, approval waits, and long-running jobs

#### Editable Deliverables

Return ForgeCAD code and exports that engineering users can inspect and modify

#### Trace Flywheel

Convert successful and failed design attempts into evaluation and training assets

#### Risk Containment

Gate manufacturing-sensitive decisions through human approval and policy checks

#### Tool Portability

Keep agent semantics above any one editor, kernel, mesh library, or model provider

---

03 — Architecture

## Recommended System Shape

The architecture separates user-facing CAD editing from geometry authority. The agent reasons through semantic primitives, CadQuery owns canonical solid generation, MeshLib owns mesh inspection and repair, ForgeCAD presents editable code and previews, and Temporal records durable stage transitions. This gives engineering leads clean boundaries for quality, state, and failure handling.

UX

### ForgeCAD — Presentation and Editable Surface

ForgeCAD is not the core geometry authority. It receives generated editable model code, previews, exports, and review artifacts so engineers can inspect, adjust, and continue from agent output.

GRT

### Geometry Agent Runtime — Semantic Primitive Layer

The runtime exposes typed primitives such as mounting plates, holes, ribs, clearances, mates, fillets, fixtures, and inspections. It compiles those primitives into tool-specific operations and preserves a compact execution trace.

CAD

### CadQuery + MeshLib — Geometry Authority

CadQuery solids are canonical during generation. MeshLib is canonical for mesh inspection, repair, proximity checks, and geometric evidence. This prevents the system from relying on screenshots or editor code as the source of truth.

RLM

### Recursive + Multimodal Reasoning

RLM handles long-context exploration and decomposition. Multimodal calls evaluate rendered views, screenshots, and 3D evidence so the agent can think with images and extend that loop into geometry-aware 3D reasoning.

WF

### Temporal — Durable Stage Orchestration

Temporal owns workflow durability across coarse stages: planning, generation attempt, inspection, repair, verification, approval, and export. Primitive-level detail stays in trace artifacts to avoid event-history bloat.

Diagram ◉ 03.1 — High-level architecture · five durable boxes

Zoom · 0

INTENT → DURABLE LOOP → 3D REASONING → GEOMETRY AUTHORITY → EDITABLE CAD + TRACE

ENGINEER
prompt · rubric · approval
ForgeCAD review surface
editable code · preview · export

PRODUCT API
thin translation layer

POST /designs

signals · queries · evidence

TEMPORAL WORKFLOW
coarse stages only
plan → generate → inspect
repair → verify → approve
emit → export → trace

durability · retry · HITL wait

GEOMETRY AGENT RUNTIME
semantic primitives backed by geometry tools

RLM
context
decompose

3D
images +
geometry

TRACE
evals
labels

CADQUERY

MESHLIB

RENDER

ARTIFACT STORE + EVAL CORPUS
solids · meshes · renders · primitive trace · verifier labels

intent

workflow

activity

feedback enriches evals and future attempts

Read left-to-right. Temporal coordinates the durable stages; the Geometry Runtime owns the detailed primitive loop; ForgeCAD receives accepted editable output.

Diagram ◉ 03.2 — Low-level architecture · runtime turn anatomy

Zoom · 1 · runtime

ONE TEMPORAL ACTIVITY CAN CONTAIN MANY PRIMITIVE OPERATIONS; THE TRACE IS STORED AS AN ARTIFACT

INPUT CONTEXT
▸ design prompt
▸ project constraints
▸ ForgeCAD examples
▸ previous traces
▸ target review rubric
loaded as variables; summarized only when useful

RLM PLANNER
context exploration + decomposition

grep docs · parse examples

spawn focused sub-calls
outputs: primitive plan + assumptions

SEMANTIC PRIMITIVE PLAN
validated schema before tool execution

mounting\_plate

holes

ribs

clearance

mates

fillets

GEOMETRY TOOLS
authoritative evidence, not decorative checks

CadQuery
canonical
solids

MeshLib
inspect
repair

measure · collide · watertight · render

3D VERIFIER
raw geometry + rendered views
▸ multi-view images
▸ measurements
▸ intent rubric

REPAIR LOOP
bounded attempts, explicit failures
if invalid: revise primitives
if mesh defect: repair or fail
if mismatch: ask / iterate

EMIT + REVIEW
accepted geometry leaves the runtime

ForgeCAD code

exports

trace

PASS: EMIT ARTIFACTS · FAIL: BOUNDED REPAIR OR HUMAN CLARIFICATION · ALWAYS: TRACE CAPTURE

State

CadQuery solids are canonical during generation; MeshLib evidence is canonical during inspection and repair.

Durability

Temporal sees the turn as coarse activities and stores heavy primitive detail by artifact reference.

Reasoning

The verifier consumes raw measurements and rendered views, so Thinking in 3D is not screenshot-only.

Handoff

ForgeCAD receives editable code, accepted previews, exports, and review notes after verification.

---

04 — Spatial Reasoning

## Thinking with Images, Extended into 3D

The harness must treat 3D reasoning as both an in-loop design capability and a post-generation verification capability. During generation, the agent observes geometry evidence, revises primitives, and repairs defects. At the end of each attempt, a verifier evaluates whether the artifact satisfies intent using both rendered views and deterministic geometry checks.

#### Semantic Primitive Planning

The agent plans in typed CAD concepts: holes, ribs, mounting plates, offsets, mates, clearances, fastener patterns, envelopes, and manufacturability constraints.

#### Raw Geometry Evidence

CadQuery and MeshLib expose dimensions, topology, intersections, proximity, normals, watertightness, face references, and mesh defects for deterministic inspection.

#### Rendered Visual Evidence

Multi-view renders let multimodal models judge shape intent, orientation, visual plausibility, assembly alignment, and defects that are easier to see than specify numerically.

#### Repair and Re-Verification

Failures route back into the primitive plan. The agent can revise dimensions, add constraints, repair meshes, regenerate previews, and re-run the verifier before asking for approval.

### Why Images Alone Are Not Enough

A rendered screenshot can reveal whether a part looks wrong, but it cannot prove constraints, tolerances, clearances, topology, or manufacturability. The runtime must combine visual inspection with geometric measurements. That is the practical meaning of Thinking in 3D: the agent observes both pixels and primitives, then acts on the underlying geometry rather than only describing the image.

---

05 — Geometry Ownership

## Canonical State Boundaries

The refined architecture assigns one clear owner for each representation. This avoids a common failure mode in CAD agent systems: treating generated editor code, preview images, meshes, and solids as interchangeable sources of truth.

| Representation | Canonical Owner | Role in the Harness |
| --- | --- | --- |
| Design Intent | Workflow input + user approval state | Stable requirements, constraints, review decisions, and manufacturing caveats |
| Semantic Plan | Geometry Agent Runtime | Typed primitive sequence that is auditable and portable across tools |
| Generated Solids | CadQuery | Canonical representation during parametric construction and feature generation |
| Mesh Evidence | MeshLib | Canonical representation for mesh inspection, repair, collision, proximity, and watertightness |
| Rendered Views | Geometry Runtime artifact store | Evidence for multimodal review, human approval, and regression comparison |
| Editable CAD | ForgeCAD | User-facing code, preview surface, and handoff artifact; not the core geometry authority |
| Durable State | Temporal | Coarse stage transitions, retries, approval waits, signals, and artifact references |
| Primitive Trace | Trace artifact store | Compact execution detail for audits, evals, debugging, and future fine-tuning |

---

06 — Runtime Contract

## Semantic Primitives Backed by CadQuery and MeshLib

The Geometry Agent Runtime is the execution boundary between model reasoning and CAD tooling. The agent does not directly freestyle arbitrary CAD code as the main interface. It proposes and revises semantic primitives, then the runtime compiles those operations into CadQuery generation, MeshLib inspection and repair, render artifacts, and ForgeCAD handoff code.

| Runtime Primitive | Function | Backing Capability |
| --- | --- | --- |
| primitive\_plan | Create a typed plan of CAD features, constraints, dimensions, and expected evidence. | RLM + schema validation |
| solid\_generate | Compile semantic primitives into canonical solids and parametric construction steps. | CadQuery |
| mesh\_inspect | Check watertightness, topology, intersections, normals, clearances, and mesh defects. | MeshLib |
| mesh\_repair | Repair or simplify mesh outputs where appropriate without hiding failed design intent. | MeshLib + policy gates |
| measure\_geometry | Collect dimensions, volumes, bounding boxes, face references, and tolerance evidence. | CadQuery + MeshLib |
| render\_views | Produce canonical visual evidence: front, side, top, isometric, section, and exploded views. | Geometry renderer |
| visual\_verify | Use multimodal models to compare rendered evidence against user intent and rubric. | Thinking with Images / 3D verifier |
| forgecad\_emit | Generate editable ForgeCAD model code and attach previews, exports, and review notes. | ForgeCAD adapter |
| trace\_capture | Persist primitive plan, tool evidence, verification scores, and repair attempts as artifacts. | Artifact store + Temporal reference |
| approval\_gate | Block release or export when manufacturing-sensitive assumptions need human signoff. | Temporal Signal |

---

07 — MVP Loop

## Minimum Viable Workflow

The first implementation should prove the full spatial reasoning loop before expanding into multi-part child workflows or fine-tuning. The MVP needs enough surface area to show language-to-geometry, deterministic inspection, visual reasoning, editable output, and human approval.

#### Prompt and Requirements

User intent enters as a workflow input. The system extracts dimensions, constraints, assumptions, manufacturing risk, and required review evidence.

#### Semantic Primitive Plan

RLM creates a typed plan using feature and inspection primitives. The plan is validated before any geometry tool executes.

#### CadQuery Solid Generation

The runtime compiles primitives into canonical CadQuery solids, retaining parameters and construction trace for repair and explainability.

#### MeshLib Inspection and Repair

Mesh evidence is checked for geometric validity, collisions, clearances, and mesh defects. Repair attempts are bounded and recorded.

#### Multi-View 3D Verification

The verifier consumes raw geometry evidence plus rendered views, scores against intent, and sends failures back to the primitive plan.

#### ForgeCAD Handoff and Approval

The system emits editable ForgeCAD code, previews, exports, and trace artifacts. Human approval gates release for sensitive outputs.

---

08 — Worker Boundaries

## Execution Surfaces and Ownership

This section defines runtime ownership. Temporal owns durable progression and retries. Workers own bounded execution. The artifact store owns heavy geometry evidence. ForgeCAD owns the editable human handoff.

Diagram ◉ 08.1 — Worker ownership · queues, artifacts, and gates

Runtime map

TEMPORAL RECORDS STAGES · WORKERS EXECUTE BOUNDED JOBS · ARTIFACTS HOLD HEAVY EVIDENCE

PRODUCT API
prompt · rubric · approval policy
starts workflow

TEMPORAL NAMESPACE
workflow state, retries, timeouts, signals, queries, artifact references

design queue

planning queue

geometry queue

verify queue

handoff queue

PLANNER
RLM context pass
primitive plan

GEOMETRY
CadQuery solids
MeshLib inspect

VERIFIER
images + geometry
pass/fail rubric

HANDOFF
ForgeCAD code
exports + notes

ARTIFACT STORE
solids · meshes · renders
primitive trace · scores
Temporal stores references

FAILED VERIFICATION RE-ENTERS AS A NEW PLANNING ATTEMPT, NOT AS HIDDEN STATE MUTATION

W · 01 / durable

#### Design Workflow

Owns stage order, retries, timeouts, signals, queries, and artifact references. It does not own primitive execution.

* Queue design
* State stage only
* Failure retry or gate

W · 02 / reasoning

#### Planning Worker

Explores context and emits a typed primitive plan plus assumptions. It can ask for clarification when intent is underspecified.

* Queue planning
* Output primitive plan
* Failure ambiguity

W · 03 / geometry

#### Geometry Worker

Runs CadQuery and MeshLib inside an isolated runtime. This is where canonical solids, mesh diagnostics, and repairs are produced.

* Queue geometry
* State artifact trace
* Failure invalid geometry

W · 04 / evidence

#### Verifier Worker

Scores the attempt using measurements and rendered views. It decides whether to pass, repair, or escalate to human review.

* Queue verify
* Input image + geometry
* Failure mismatch

W · 05 / handoff

#### ForgeCAD Adapter

Emits editable code, previews, exports, and review notes only after the accepted geometry has passed the verifier or approval gate.

* Queue handoff
* Output editable CAD
* Failure translation drift

---

09 — State & Durability

## Coarse Durable Stages, Detailed Trace Artifacts

Temporal should record coarse workflow stages rather than every semantic primitive call. This preserves durable recovery, retries, approval waits, and auditability without exploding event history or confusing orchestration with geometry execution.

#### Temporal = Stage State

Workflow history captures stage boundaries, activity outcomes, artifact references, retries, timeouts, signals, queries, and approval decisions.

#### Runtime Trace = Primitive Detail

The Geometry Runtime records primitive calls, parameters, measurements, renders, mesh diagnostics, repair attempts, and verifier scores as trace artifacts.

#### Queries = Live Review

Temporal Queries expose current phase, latest preview, verification score, failure reason, artifact URIs, and approval requirements without mutating workflow state.

#### Signals = Human Control

Signals carry approval, rejection, parameter changes, rubric updates, and iteration requests into a running workflow without polling or restarting the job.

### History Management Decision

Primitive traces should be attached to workflow history by reference, not embedded in full. The workflow can use Continue-As-New for long-running explorations, but the stronger first control is to keep Temporal history at the stage level and store large geometry, image, mesh, and trace payloads in an artifact store.

---

10 — Interface

## Product API Contract

The external API wraps Temporal workflow operations and artifact access. Starting a design creates a workflow, iteration and approval become signals, status and previews are queries, and large geometry evidence is read from the artifact store by reference.

POST/api/v1/designsStart a workflow from prompt, project context, output target, and evaluation rubric

SIGNAL/api/v1/designs/:id/iterateSend revision instructions, updated constraints, or changed review criteria

QUERY/api/v1/designs/:id/statusRead phase, progress, verifier score, failure reason, and approval requirement

QUERY/api/v1/designs/:id/codeRead current editable ForgeCAD source code and generation metadata

QUERY/api/v1/designs/:id/evidenceRead geometry measurements, mesh diagnostics, rendered views, and trace links

SIGNAL/api/v1/designs/:id/approveApprove, reject, or request changes at a human-review gate

SIGNAL/api/v1/designs/:id/paramsSend parameter changes into a running workflow for repair or regeneration

GET/api/v1/designs/:id/traceFetch the primitive trace artifact and related Temporal history references

POST/api/v1/designs/:id/exportTrigger accepted output export: ForgeCAD, STEP, STL, mesh, preview pack, or report

WS/ws/v1/designs/:id/streamStream stage changes, previews, verifier updates, approval gates, and export status

---

11 — Performance

## Decision Metrics

These metrics should be treated as review gates, not marketing claims. The first milestone is to prove a reliable single-part loop before optimizing speed or moving into multi-part orchestration.

>80%

Valid Single-Part
First Pass

<2

Average Repair
Iterations

100%

Outputs with Trace
Artifacts

0

Silent Geometry
Failures

<5m

MVP Single-Part
Workflow Time

<40k

Temporal Events
Before Continue

100%

Human Gates for
Risky Exports

A/B

Model and Runtime
Eval Harness

---

12 — Roadmap

## Implementation Phases

The roadmap prioritizes proving the spatial reasoning loop before expanding into multi-part workflows, model fine-tuning, or broad productization. The first milestone should be a single-part design loop that engineering leads can evaluate against real geometry evidence.

Weeks 1–4

MVP Geometry Loop

* Implement Temporal workflow with coarse stages
* Define semantic primitive schema and validation
* Compile primitives into CadQuery solids
* Run MeshLib inspection for validity and clearances
* Generate multi-view renders and evidence bundle
* Emit editable ForgeCAD code for accepted outputs

Weeks 5–8

Reasoning and Review

* Add RLM context exploration over docs and examples
* Build 3D verifier using geometry and render evidence
* Implement bounded repair loop and failure taxonomy
* Add approval signals and live status queries
* Persist primitive traces and verifier rubrics
* Create eval suite for representative CAD prompts

Weeks 9–12

Scale and Productization

* Add multi-part child workflows after MVP loop works
* Introduce task queues for planning, geometry, render, export
* Harden sandboxing, artifact storage, and policy gates
* Add OpenTelemetry and workflow cost reporting
* Use traces for evals, distillation, and fine-tuning
* Load test concurrent workflows and large artifact payloads

---

13 — Risks

## Risks & Mitigations

| Risk | Severity | Mitigation |
| --- | --- | --- |
| Semantic primitives are too weak | High | Start with a narrow single-part primitive set. Require schemas, validation, examples, and explicit unsupported-feature errors before expanding scope. |
| Visual verifier misses geometric failures | High | Never rely on rendered images alone. Pair every visual review with MeshLib/CadQuery evidence for dimensions, intersections, clearances, topology, and constraints. |
| CadQuery to ForgeCAD translation drift | High | Treat CadQuery as canonical during generation. Add translation tests that compare rendered and measured ForgeCAD outputs against the accepted geometry artifact. |
| Mesh repair hides design mistakes | Med | Separate repairable mesh defects from semantic design failures. Record every repair, cap repair attempts, and require human review for non-trivial geometry changes. |
| Temporal event history overflow | Med | Persist primitive detail as artifacts and store references in workflow history. Continue-As-New before 40k events for long-running explorations. |
| RLM cost and latency amplification | Med | Cap recursion depth, require bounded repair loops, cache context exploration, and route simple inspections to smaller models or deterministic checks. |
| Sandbox and tool execution risk | Med | Run geometry tools in isolated workers with resource limits, read-only inputs where possible, no ambient credentials, timeout enforcement, and artifact size quotas. |
| Scope expands before MVP proof | Low | Defer multi-part orchestration, fine-tuning, and broad export support until the single-part Thinking in 3D loop passes the decision metrics. |

---

14 — Trace Capture & Evals

## From Runtime Traces to Better CAD Agents

Every attempt should become evaluation data before it becomes training data.

The most valuable platform byproduct is a structured record of how agents think and act in geometry space. Successful attempts show reusable strategies. Failed attempts expose missing primitives, weak verifiers, bad assumptions, and translation drift. The trace corpus should first power regression tests and model/runtime comparisons; fine-tuning comes later, after the team trusts the labels and failure taxonomy.

### What Gets Captured

#### Planning Traces

Prompt interpretation, extracted constraints, assumptions, primitive plans, repair hypotheses, and unsupported-feature decisions.

#### Geometry Evidence

CadQuery construction metadata, MeshLib diagnostics, measurements, collision checks, clearances, repair outcomes, and artifact links.

#### Visual Evidence

Canonical render sets, annotated failure views, verifier prompts, model judgments, human review notes, and screenshot comparisons.

#### Outcome Labels

Pass/fail reason, first-pass status, number of repairs, human approval decision, export readiness, and regression category.

### Trace-to-Evaluation Pipeline

| Stage | Process | Output |
| --- | --- | --- |
| 1. Capture | Persist stage metadata, primitive trace, geometry evidence, rendered views, verifier scores, and human decisions after each attempt. | Raw trace bundle |
| 2. Normalize | Convert traces into a stable schema with prompt, plan, artifacts, measurements, rendered evidence, repair actions, and outcome labels. | Queryable corpus |
| 3. Classify | Tag failures by root cause: primitive gap, geometry invalidity, visual mismatch, translation drift, verifier miss, or user ambiguity. | Failure taxonomy |
| 4. Regress | Replay representative prompts against new models, primitive schemas, verifier rubrics, and runtime versions. | Agent eval suite |
| 5. Improve | Use trace patterns to add primitives, tighten rubrics, improve repair policies, and create targeted examples for future model adaptation. | Runtime and model backlog |
| 6. Fine-Tune Later | Only after label quality stabilizes, transform successful and failed traces into supervised or preference data for domain-specialized models. | Training-ready dataset |

### Model Tiering Strategy

Once the evaluation harness is stable, model routing can become cost-aware. Smaller or specialized models can handle routine primitive planning and repair suggestions, while frontier multimodal models remain reserved for ambiguous intent, novel geometry, and high-risk verification. Temporal task queues make that routing operational, but the routing policy should be driven by measured quality rather than assumption.

The trace flywheel is therefore practical: traces improve evals, evals reveal where the runtime or model fails, and only trusted labels graduate into fine-tuning or distillation. This protects the platform from training on noisy geometry mistakes.

1

Trace Schema
per Attempt

6

Core Failure
Categories

A/B

Model and Runtime
Comparisons

Later

Fine-Tune After
Label Trust

---

15 — Conclusion

## Decision Summary

The recommended direction is to approve the Geometry Agent Harness as a platform capability for CAD agent evaluation and development. The architecture is strongest when ForgeCAD is treated as the editable product surface, not the geometry authority. CadQuery owns solid generation, MeshLib owns inspection and repair evidence, and the Geometry Agent Runtime exposes semantic primitives above both.

Temporal remains important, but its role is durable orchestration across coarse stages rather than recording every primitive call. That separation keeps workflow history manageable while preserving recoverability, approval gates, and audit references. The runtime trace becomes the detailed evidence layer for engineering review, evals, and eventual model improvement.

The next decision should be an MVP build focused on one thing: prove the Thinking in 3D loop for single-part CAD workflows. Multi-part orchestration, model fine-tuning, and broad export coverage should wait until that loop can reliably generate, inspect, repair, verify, and hand off editable geometry.

Engineering Design Review

Geometry Agent Harness — RLM + Temporal + CadQuery + MeshLib + ForgeCAD — May 2026