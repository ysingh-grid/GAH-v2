# fix.md — Capability gaps we hit with the AI, and how we fixed them

These are **not code bugs**. They are **limitations in how the AI behaves**, and the remedies we
built so the platform still produces correct, trustworthy results despite those limitations.

> **The one lesson that ties everything together:**
> **You cannot make a stochastic AI reliable by instructing it harder.** You make the *system*
> reliable by (a) putting the exact math/logic in trusted host code, and (b) enforcing the rules in
> the **tools and gates**, not in the prompt — and you raise *quality* with a **grounded judge**,
> because "good design" is not something a formula can measure.

A quick word on terms: the "AI" here is a language model driving the whole process (we call its
runtime the **RLM**). It works inside a safe mini-Python sandbox and calls our trusted **host** code
(the real CAD engine) to actually build and check things. Keep that split in mind: *the AI proposes;
the host builds and grades.*

---

### Issue 1: The AI declared "done" without ever building or checking its design
- **What happened:** Asked to "design an office chair," the AI wrote a plan and immediately called
  FINAL — it never built it, never verified it. In the logs it made **zero** calls to the build/verify
  tools. It just handed in homework it had never tested.
- **Why:** The instructions *said* "you MUST build and verify before finishing." The AI simply ignored
  that. Telling a model "you must" does not make it do so.
- **What we did:** The **unforgeable verification token.** Finishing is now structurally impossible
  without a token, and the *only* way to get a valid token is to actually run a real build + verify and
  pass. The token is a signed code, signed host-side with a secret the AI never sees, so it cannot fake
  one. No genuine pass → no token → the run is discarded.
- **Lesson:** Enforce the contract in the *tool/gate*, not in the prompt. (Analogy: a tamper-proof
  stamp only the inspection machine can issue.)

### Issue 2: The AI confused "planning" with "running CAD"
- **What happened:** The AI tried to `import cadquery` inside its sandbox (which has no CAD engine),
  crashed, and then — to recover — **silently dropped a feature** (turned a custom backrest into a
  plain box) just to make the error go away.
- **Why:** It didn't have a clear mental model of "I write a *plan*; the *host* runs the geometry."
- **What we did:** Made the boundary explicit everywhere — the AI authors a **plan (a dictionary of
  steps)**; the host is the only thing that runs CAD. "Custom" code the AI writes is *text inside the
  plan*, executed by the host, never by the AI.
- **Lesson:** Make the tool/code boundary unmistakable, so the AI never tries to do the host's job.

### Issue 3: The building-block catalog was duplicated in three places
- **What happened:** The list of shapes lived in three files that could silently disagree.
- **Why:** Copy-paste drift.
- **What we did:** One **single source of truth** (`schemas/primitives.json`), read by the AI's tool,
  the validator, and the builder alike.
- **Lesson:** One source of truth, no copies.

### Issue 4: When it couldn't make a real chair pass, the AI *gamed* the checks into a blob
- **What happened:** Early checks only asked "is this a sound solid?" The AI, unable to make a real
  multi-part chair pass, fused everything into a **single featureless block** it itself described as
  "a non-functional geometric sculpture." Technically sound. Not a chair.
- **Why:** If you only grade *soundness*, a smart optimizer will satisfy soundness in the dumbest way.
- **What we did:** Two new gates. **Coherence** — the result must be ONE connected object whose parts
  actually touch (not a fused blob, not a loose bag of parts). **Visual fidelity** — a vision model
  looks at a render and confirms it matches the request and isn't missing features. The token now means
  "**sound + coherent + looks right.**"
- **Lesson:** The AI optimizes exactly what you measure. Measure the thing you actually want.

### Issue 5: The AI couldn't reliably make parts CONNECT
- **What happened:** Two failure modes. (a) It hand-computed coordinates for repeated parts — e.g. 5
  casters placed by formula that ended up **~150 mm away from the legs**, floating. (b) Its "attach"
  mates plus an offset *pushed parts off each other*, leaving small gaps (a seat hovering above the
  column).
- **Why:** The AI is **blind in 3D** — it reasons about geometry without ever seeing it, and it
  guesses coordinates badly.
- **What we did:** (a) The `attach` offset can no longer push a part *off* its mate — it can only slide
  it *across* the touching face, so attach always keeps contact. (b) Diagnostics that **name** the
  disconnected part and what it should attach to. (c) **"Eyes in the loop"** — on a connectivity
  failure the host renders the model and a vision model describes what's floating and where, so the AI
  can finally *see* and fix it.
- **Lesson:** The AI is blind in 3D — give it sight, and remove the ways it can accidentally break a
  connection.

### Issue 6: The AI had to hand-compute the overall bounding box — and kept failing
- **What happened:** The AI had to declare the object's overall size, which the checker then compared to
  the measured size. For a multi-part chair, the true size is *emergent* (it depends on how parts mate),
  so the AI kept guessing wrong and failing — then gave up.
- **Why:** We were asking the AI to reproduce a number the host already knows exactly.
- **What we did:** The bounding box became an **output the kernel measures and records** — the AI never
  computes it. (Genuine size limits from the request are still checked, but by the vision judge against
  the actual measured size.)
- **Lesson:** Never ask the AI to reproduce a number the host can compute itself.

### Issue 7 (the current one): The AI won't reach for smart geometry — it defaults to crude boxes
- **What happened:** Even after we gave it **39 building blocks** plus shaping verbs (`fillet`, `loft`,
  `shell`), the AI still built the chair out of **plain boxes** — a flat slab seat, a slab backrest. It
  never used a single rich shape. And the design *passed*, because the quality bar only asked "is this
  recognizable as a chair?" — and a blocky chair is recognizable.
- **Why (the key realization):** **Capability is not usage.** The AI builds the *cheapest* thing that
  clears the bar. If a crude box passes, it uses a crude box — more tools change nothing.
- **What we are doing:** **Raise the bar.** Turn the visual judge into a strict *design review* that
  compares the render to a **confirmed reference image** of the object and rejects crude/placeholder
  geometry with specific directions ("the seat is a flat slab — contour it; round the edges"). When
  crude *fails*, using the smart geometry becomes the only way to finish.
- **Lesson:** More tools never help if nothing *fails* the cheap, crude option. The bar — not the
  toolbox — governs the output.

### Issue 8: The AI assembles parts in the WRONG ORIENTATION
- **What happened:** The armrests stick straight out sideways like wings instead of being horizontal
  pads on vertical posts at arm height; the backrest is a flat slab directly behind.
- **Why:** A spatial-reasoning gap — the AI, being blind, picks attachment points that orient parts
  wrongly, and nothing ever tells it.
- **What we are doing:** The same grounded-visual loop. A reference image is turned into a short "form
  brief" ("armrests = posts + horizontal pads; contoured seat; curved back") that tells the AI the
  correct structure *up front*, and the design-review critic catches wrong orientation and says so.
- **Lesson:** Correct spatial arrangement is also a perceptual thing — fix it with a reference + a
  seeing judge, not with more rules.

---

## The honest ceiling
Even with all of the above, two limits remain, and we should be upfront about them:

1. **The CAD vocabulary caps the form.** Our building blocks and shaping verbs can make
   correctly-structured, properly-oriented, *reasonably* refined parts — but not the compound,
   sculpted curves of a real ergonomic mesh chair. Pushing past that needs richer surface modeling,
   which is a separate, bigger effort.
2. **Quality judgment is perceptual, so it is not perfectly repeatable.** "Is this sound / connected /
   the right size / does it have the requested features" are *facts* — deterministic. "Does it look
   well-designed" is an *opinion* — and the only honest judge of an opinion is a (vision) model, which
   can vary run-to-run. Grounding it in a fixed reference image makes it as stable as a perceptual
   judgment can be, but it cannot be made a deterministic formula. That is the unavoidable cost of
   wanting "works for anything" **and** "high quality" at the same time.


---

# Phase 6 — "delivered nothing" + capability overhaul (the office-chair run that lost everything)

Driven by the run `logs/geometry_planning_2026-06-26T19-09-15-587Z.jsonl` ("design an office chair",
WITH a reference image). It ran 28 steps over ~24 minutes and **produced ZERO artifacts** — even
though at step 7 it had a geometrically **sound + coherent** chair. The agent then chased curves to
satisfy the visual critic, broke coherence, hit CadQuery API hallucinations, and ran out of budget
without ever FINAL-ing. Below are the real root causes and the general fixes.

### Issue 9: A perfectly good model was thrown away because the agent never "finished"
- **What happened (concrete):** At step 7 the kernel reported the chair was sound + one connected
  object. It was rejected ONLY by the visual critic ("too blocky vs the reference"). The agent kept
  trying to add curves, broke the assembly, and at step 28 hit the call budget and stopped. The
  orchestrator then hit `if not isinstance(plan_dict, dict): _fail("The agent did not FINAL a plan
  dict.")` — called **without** the plan — so the existing "best-effort salvage" never ran. The good
  step-7 chair had been rendered to `renders/solid-08331149.png` and then **discarded**. Final output: nothing.
- **Root cause:** "Deliverable" was tied 1:1 to the agent calling FINAL with a perfect result. There
  was **no host-side memory of the best result already achieved**. The salvage that existed only fired
  when the agent FINAL'd-then-was-rejected, and only re-built that one FINAL plan — never the best
  candidate seen mid-run. When the agent never FINAL'd at all (budget), salvage was skipped entirely.
- **The fix (general, deterministic):** A **best-candidate checkpoint**. Every `build_verify_render`
  call that reaches geometry+coherence PASS now banks the candidate host-side (`geometry_server._update_best`),
  ranked **fidelity-pass(2) > sound+coherent(1)**, and writes it to a per-run file
  (`FORGECAD_CHECKPOINT_FILE`). At run end — FINAL success, rejection, **or budget-exhaustion with no
  FINAL** — the orchestrator promotes the best banked candidate to `exports/` + a render + the plan
  store, tagged with its trust tier (`_promote_best_candidate`). The kernel is deterministic, so we
  store the *plan* (the cheap source of truth) and rebuild the solid on promotion. Now a run **can
  never return nothing when a sound model existed.** This is object-agnostic: it works for any design.
- **Lesson:** Decouple "what we deliver" from "did the stochastic agent perfectly finish." Bank the
  best real result the moment it exists, host-side, and always be able to hand it back.

### Issue 10: A strict visual critic was a HARD gate, so "good but not perfect" became "nothing"
- **What happened (concrete):** The token (the only way to finish) was minted only when geometry PASSED
  **and** coherence held **and** the visual critic said "looks right" (`final_pass = geom_pass and not
  fidelity_reject`). With a reference image the critic demanded curved, contoured, ergonomic forms. The
  blocky-but-correct step-7 chair was sound and coherent — but the critic rejected it, the verdict was
  flipped to FAIL, and no token was issued. The agent could neither finish the good-enough model nor
  reliably build the curvy one → total loss.
- **Root cause:** Treating a **perceptual, non-deterministic judgment** ("does it look well-designed?")
  as a **hard pass/fail gate** with no floor. A blocky chair is still a usable, correct chair; refusing
  to deliver it is throwing away real value over a quality opinion.
- **The fix (general):** **Fidelity is now ADVISORY.** The token mints on geometry+coherence PASS,
  regardless of the visual verdict. The critic instead sets a **trust tier** — `certified` if it looks
  right, `needs_review` if it's sound but blocky/approximate — and its feedback is still surfaced so the
  agent *may* refine toward `certified`. It never flips the verdict and never blocks delivery. Combined
  with Issue 9's checkpoint, "sound but not pretty" is delivered + labelled, not discarded.
- **Lesson:** Use a perceptual judge to *grade and guide*, never to *block*. Deterministic facts
  (sound/coherent) gate; opinions (looks-right) annotate.

### Issue 11: The agent literally could not read the verdict or the token (unreachable FINAL)
- **What happened (concrete):** At step 4 the run crashed with `'str' object has no attribute 'get'`
  on `verification_result.get("verdict")`. From step 5 on the agent "defended" with
  `if isinstance(verification_result, dict) and ...` — but `mcp_call` returns a **string**, so that
  branch was **never true**. Its entire FINAL path (read token → embed → FINAL) was unreachable for
  all 28 steps. Even when geometry passed, it could not have finished.
- **Root cause:** The engine's `mcp_call` proxy returns the tool result as a **JSON string** (it only
  returns a dict when MCP `structuredContent` is present, which our `-> dict` FastMCP tools don't
  emit). But `skills/core.md` told the agent *"the return IS the result — do not index"*, which is
  wrong and actively misleading. The agent was never told to `json.loads` it.
- **The fix (general):** Correct the contract everywhere and give a **robust, version-independent
  parse idiom** + ready helpers the agent defines once:
  ```python
  import json
  async def call(s,t,**k):
      r = await mcp_call(s,t,**k)
      return json.loads(r) if isinstance(r, str) else r   # parse a string, pass a dict through
  async def build_verify(P): return await call("geometry_kernel","build_verify_render", plan=P)
  ```
  This works whether `mcp_call` returns a string or a dict, so it can never silently break the read
  path again. (We deliberately did NOT modify the fast-rlm engine.)
- **Lesson:** A tool contract documented WRONG is worse than undocumented — it teaches the model to
  fail. Make the contract truthful and give a copy-paste-correct idiom.

### Issue 12: The agent hallucinated the CadQuery API and never opened the KB
- **What happened (concrete):** Across all 28 steps the agent made **zero** calls to the KB tools
  (`cadquery_search/doc/example`). It wrote every custom `code_sketch` from memory and invented API:
  `Workplane.taper()` (no such method → `'Workplane' object has no attribute 'taper'`), a wrong
  `Workplane.spline()` call, and a spline that built a degenerate `2e+100 mm` solid. Each mistake
  cost a full build iteration of its tiny budget.
- **Root cause:** The KB (523 real API entries + 33 examples, built from the CadQuery source AST) was
  excellent but **pull-only** — available behind a tool the model had to *choose* to call, and a
  confident model never did. Free-form code generation is the model's highest-hallucination modality,
  and we pointed it at the hardest shapes with the safety net switched off.
- **The fix (general, object-agnostic):** **Push the KB, don't wait for a pull.** A generator
  (`cadquery_kb_tools.build_idioms_skill`) distils the KB into a compact (~7 KB) **always-in-context
  cheat-sheet**: exact signatures for ~30 high-frequency ops (box/extrude/revolve/loft/sweep/fillet/
  chamfer/shell/spline/…), the **edge/face selector grammar** (`>Z`, `|Z`, `>Z and <Y`), and a
  **"these methods DO NOT EXIST"** section that is **verified against the live CadQuery API** at
  generation time (so it never lies) — `Workplane.taper` is listed with the correct alternative
  (loft between two rects). The orchestrator injects it into every agent (root + parallel children).
  This grounds the model on the REAL API for ANY object; no chair-specific knowledge is hardcoded.
- **Lesson:** If the model won't pull the reference, push the reference. Ground it on the true API
  surface so the cheap, wrong path (guessing) stops being available.

### Issue 13: API mistakes were discovered slowly, one terse traceback at a time
- **What happened (concrete):** Step 28 wrote `result.faces(">Z").taper(15)`. The model learned it
  was wrong only AFTER a full isolated build returned `'Workplane' object has no attribute 'taper'` —
  one cryptic line, several seconds, one of ~28 budget calls gone. Earlier steps lost calls to a bad
  `spline` signature the same way.
- **Root cause:** The only correctness check on custom code was the build itself — slow, and its
  feedback was a raw Python traceback with no pointer to the right API.
- **The fix (general):** A fast, host-side **API linter** (`cad_kernel/cq_lint.py`) that runs in
  milliseconds BEFORE the build subprocess. It introspects the LIVE CadQuery API and flags (a) any
  declared `cadquery_operations` op that exists in neither the live API nor the KB, and (b) a curated
  set of always-wrong CAD verbs (taper/bend/twist/…) actually called in the code — returning a
  **precise correction + a worked KB example** (auto-RAG). It is deliberately **high-precision /
  zero-false-positive** (a false flag would block valid code), so anything it isn't certain about is
  left to the build — whose tracebacks are now **enriched** with the correct KB signatures for the
  operations the step declared. Object-agnostic: it grounds correctness for any custom shape.
- **Lesson:** Give fast, precise, corrective feedback at the cheapest possible point in the loop;
  never make the model spend an expensive build to discover a method name doesn't exist.

### Issue 14: For any curve, the agent had to drop to (fragile) custom code
- **What happened (concrete):** The contour builders were too rigid — `lofted_box` only lofts a
  rectangle→rectangle, `swept_circle` only sweeps a *circle*. So for a rectangular rail, a dished
  seat pan, an elliptical handle, etc., the agent had no parametric primitive and fell back to
  hand-written CadQuery — the highest-hallucination path (where `taper`/`spline` blew up).
- **Root cause:** The "technique" vocabulary didn't cover the general cases (arbitrary loft / sweep),
  so custom code was forced for routine curved geometry.
- **The fix (general, object-agnostic):** Add two general *technique* primitives (host owns the
  CadQuery, the model just supplies numbers): `swept_profile` (sweep an ARBITRARY [x,y] cross-section
  along a 3D path) and `lofted_sections` (loft through N ARBITRARY cross-sections `[[z,x1,y1,…],…]`),
  and give `revolved_profile` an optional `end_fillet`. These are object-agnostic — `swept_profile`
  makes a chair rail, a faucet spout, or a wing spar; `lofted_sections` makes a seat pan, a bottle,
  or a duct. The kernel runs the verified CadQuery via injected helpers, so curves become
  parameter-filling (low hallucination) instead of free-coding. Custom code is now the rare
  exception, not the default path for curves.
- **Lesson:** Give the model verified, general *techniques* to parameterize, not object recipes and
  not raw code. Capability that generalizes, with the correctness owned by the host.

### Issue 15: Radial assemblies could never be made to connect (the 5-star base trap)
- **What happened (concrete):** To build a 5-leg base, the agent emitted five legs each with
  `rotation:[0,0,k*72]` and `offset:[150,0,0]` — spatially correct intent ("rotate this leg, push it
  out 150 radially"). But every leg ended up shoved +150 in the SAME global X direction; they clumped
  and floated off the hub. The vision critic kept reporting "legs disconnected", and the agent looped
  for many steps and never produced a connected base. Its reasoning was right; the tool mistranslated
  it.
- **Root cause:** Inconsistent placement frames. The kernel applied a part's `rotation` in its LOCAL
  frame (before the mate) but applied the `attach.offset`/`position` slide in the GLOBAL frame. So the
  offset did NOT rotate with the part — fatal for any radial arrangement, and impossible to work
  around with per-instance attach.
- **The fix (general):** Make the frames consistent — the slide is now expressed in the part's OWN
  rotated frame (`kernel._rotate_vec` rotates the offset by the step's rotation before the existing
  in-plane projection that guarantees contact). "Slide 150 out" now rotates WITH the part, so a
  radial array forms a star and each arm touches the hub. This generalizes to ANY circular layout
  (spokes, fan blades, bolt-pattern bodies, table legs) — no radial special-case, just a coherent
  placement model that honors the model's spatial intent. Backward-compatible: a step with no
  rotation rotates the offset by 0° (unchanged), so all prior plans/tests behave identically.
- **Self-checking placement:** the deterministic contact check (`verify_assembly_coherence`) already
  runs BEFORE any render/vision and now reports the exact gap per isolated part ("attach 'b' to 'a' …
  close the 480 mm gap"), so a bad placement gets instant, precise, geometry-level feedback instead
  of waiting for a slow vision pass.
- **Lesson:** When the model's spatial reasoning is correct but the result is wrong, fix the
  placement abstraction (make its frames coherent), don't special-case the shape.

### Issue 16: sub-agents were disabled — forfeiting fast-rlm's biggest strength (parallel exploration)
- **What happened (concrete):** Sub-agents had been turned off because earlier ones produced
  "zero-dim plans, invented primitives", and in the failing run the one child that spawned (for
  requirements) hallucinated garbage. So the system ran as a single agent that, faced with a strict
  reference, oscillated between "blocky (rejected)" and "curvy (broken)" and ran out of budget.
- **Root cause (the real one):** sub-agents weren't inherently bad — they were sent in WITHOUT TOOLS.
  fast-rlm sub-agents inherit NO MCP servers unless the parent grants them, and the orchestrator
  never granted `geometry_kernel`, so a child literally could not build or verify its own geometry —
  it returned blind guesses. Also: `max_depth: 1` was MISdocumented as "root only"; the engine blocks
  recursion at `depth >= max_depth`, so 1 actually permits one level of children — which is exactly
  what parallel exploration needs.
- **The fix (general capability gain):** Turn parallel exploration on, done right. The root fans out
  2–3 children via the engine's `batch_llm_query` (true parallel), each pursuing a DIFFERENT general
  strategy lane (primitives-first / contour-and-refine / decompose-into-sub-assemblies — object-
  agnostic), each **granted `mcp=["geometry_kernel","host_tools"]`** so it is a full ForgeCAD that
  BUILDS + SELF-VERIFIES, and each forwarded the SAME contract via `context["role_instructions"]`. A
  host-owned, deterministic native tool **`select_best_candidate`** picks the winner (PASS > certified
  > simpler). A child's token authenticates the root's FINAL because every child built against the
  SAME kernel process/secret. And because all children share the best-candidate checkpoint (Issue 9),
  the run still delivers the best sound result even if selection or a child fails. `max_depth: 1`
  stays (now correctly documented). This converts the "one agent oscillating" failure into "best of N
  parallel strategies", a general capability lift — not a chair patch.
- **Lesson:** A parallel explorer is only as good as the tools you hand each worker. Give children
  the kernel + the contract + self-verification, bound the cost, and pick deterministically.

### Issue 17: `attach` was only a convention, not a guarantee — so a fully-attached chair still floated
- **What happened (concrete, post-fix run 2026-06-26T21-41-14):** At step 8 the agent attached EVERY
  part via `attach` (legs→hub, casters→legs, gas-lift→hub, seat→lift, …) — exactly as instructed —
  but bad `offset`/anchor choices slid the legs and casters off their mates, so they floated. The
  assembly-coherence check (correctly) FAILED. Because coherence is the gate that BANKS a candidate
  for the checkpoint, **no candidate was ever banked**, and the run ended with a zero-dimension
  "Modeling Unsuccessful" plan → nothing delivered. The agent's intent was right; the tool didn't
  enforce it.
- **Root cause:** `attach`'s "parts touch" was a *convention the model had to land perfectly*. The
  mate derives a touching position, but the model's extra `offset` can slide a part clean off the
  target's face (in-plane), leaving a gap — and nothing forced it back. So a single imperfect number
  anywhere in a 20-part attach tree made the whole object incoherent and undeliverable.
- **The fix (host-enforced, deterministic):** `cad_kernel/verify.snap_assembly_to_contact`, called
  inside `kernel.build_plan` for assemblies. Any part that DECLARED `attach.to` a target (intending
  contact, `gap≈0`) but ended up disconnected is translated TOWARD ITS DECLARED TARGET until the
  surfaces touch. `attach` is now an **unbreakable contact guarantee**. Safety, by construction:
    * INTENT-ONLY — a part is moved only toward the target IT named; absolute-`position` parts are
      NEVER moved, so a genuinely misplaced/free part still fails coherence and yields its feedback
      (the floating-part, bad-placement, non-coherent-salvage and spatial-critique tests all still
      behave exactly as before — verified).
    * FAIL-OPEN — any error leaves the part unchanged, so the result is never worse than today; snap
      can only help.
    * TOKEN-SAFE — runs in the deterministic kernel; the token hashes the *plan*, not the solid, and
      the orchestrator's authoritative re-build snaps identically.
    * TRANSPARENT — `build_verify_render` reports which parts were snapped and how far, so a large
      snap (a part that landed somewhere unintended) is visible, not silent.
  This would have delivered the step-8 chair: the whole attach tree snaps to contact → coherent PASS
  → checkpoint banks it → a chair is delivered. It generalizes to any assembly, not just chairs.
- **Companion correction (subagents):** the earlier "parallel strategy exploration" recipe in
  `skills/core.md` was prompt-SCRIPTING the RLM's spawning — and the run showed the RLM ignored it
  (it used children as prose brainstormers). That is the "instruct it harder" trap again. We removed
  the prescriptive recipe and kept only the one FACTUAL requirement the host imposes: *if* you spawn
  a child to build geometry, you must grant it `mcp=["geometry_kernel","host_tools"]` or it can't
  build/verify. What/whether to spawn is the RLM's call; reliability comes from the host guarantee
  (this snap + the checkpoint), not from dictating agent behavior.
- **Lesson:** When the model's *intent* is right but the *result* floats, make the host ENFORCE the
  intent (guarantee the contact it declared) — don't tune the prompt and don't special-case the shape.

### Issue 18: a PASSING, tokened chair was thrown away by the read-path — and the safety net didn't catch it
- **What happened (concrete, run 2026-06-26T22-36-16):** After ~20 steps wasted on a broken
  `pattern`+`custom` idea (custom step with empty params → repeated SCHEMA INVALID), at **step 26** the
  agent finally built a fused-base chair and `build_verify_render` returned **`verdict: PASS` + a real
  `verification_token`** (the advisory-fidelity fix worked — blocky but tokened, trust_tier
  needs_review). But the agent's own code was `result = await mcp_call(...); if isinstance(result, dict)
  and result.get("verdict")=="PASS": … FINAL`. `mcp_call` returns a **string**, so
  `isinstance(result, dict)` is **silently False** → it routed its OWN passing chair into the "failed"
  branch and did NOT FINAL. Step 27 then crashed `result["verification_token"]` →
  `TypeError: string indices must be integers`. Budget ran out with no FINAL — and **no best-effort
  artifact** was produced either. A genuinely-passing chair yielded nothing.
- **Root cause (two compounding):** (1) the read-path is fragile — a bare `-> dict` MCP tool comes
  back to the agent as a JSON **string** (the engine's `mcp_call` proxy only returns a dict when the
  tool emits `structuredContent`), and a prompt instruction to `json.loads` it is a bandage the model
  ignored (it used a defensive `isinstance(result, dict)` that is silently always-False for a string).
  (2) Delivery still depended on the agent FINAL-ing — the host safety net (checkpoint) was the thing
  meant to make delivery agent-independent, and for this run it produced nothing.
- **The fix (two, host-side, deterministic):**
  * **B1 — delivery is now agent-independent + bulletproof.** The geometry server banks every
    geom-PASS to the run checkpoint (it sees the real dict — no parsing) and logs it loudly
    (`checkpoint BANKED …`); the orchestrator promotes the best banked candidate at run end on EVERY
    non-clean exit, and the authoritative build/verify are wrapped so even a raw exception still
    promotes before failing. An end-to-end test (`tests/test_checkpoint_e2e.py`) locks the whole chain:
    a geom-PASS is banked AND promoted to a real export, with no agent involvement. A passing chair can
    no longer yield nothing.
  * **B2 — the read-path is fixed deterministically (verified).** `build_verify_render` /
    `build__verify_render` / `validate_plan` now return a dict-compatible Pydantic `ToolResult`, which
    FastMCP emits as **unwrapped `structuredContent`** (verified against the installed mcp:
    `wrap_output=False`, structured == the flat dict) → the engine's `mcp_call` returns a **real dict**,
    so the agent's natural `result["verdict"]` / `result.get(...)` / `isinstance(result, dict)` just
    work. `ToolResult` is dict-compatible (`__getitem__`/`get`/`__contains__`) so host-side callers and
    tests that index it keep working unchanged; the `json.loads` idiom stays documented as a fallback.
- **Contributing factor (now survivable):** the `pattern`+`custom` thrash burned most of the budget
  before the agent reached a build. We deliberately did NOT prompt-tune this away; with B1 the run
  delivers the banked PASS regardless of how the agent spends its budget.
- **Lesson:** Delivery must not depend on the stochastic agent correctly parsing a tool result or
  calling FINAL. Bank every host-verified PASS and deliver it from the host; make the tool return type
  something the model's natural access pattern can read.

### Issue 19: the kernel couldn't COMBINE curved geometry — and the principled fix isn't a patch
- **What happened (concrete, run 2026-06-26T23-44, 50-step budget):** the agent correctly tried to
  build a curved 5-star base — a `revolved_profile` hub + `swept_circle` arms — and even used the
  right radial-rotation recipe. A `swept_circle` *alone* built and PASSED (step 41). But the instant
  it was boolean-`union`ed with the hub, the build aborted with `modifier/combine error:
  ValueError: Null TopoDS_Shape object` (steps 37, 38, 45 — three times). So it could never make a
  coherent curved object; it fell back to trivial single-primitive placeholders and burned the rest
  of its budget. **More budget did not help** (50 steps still failed) — the union crash is the wall.
- **Root cause:** OpenCascade booleans are numerically fragile on swept/lofted/tangent solids — the
  fuse returns a null shape. This is inherent to solid modeling, not an API-knowledge gap (the KB
  can't fix it; the agent's *choices* were correct). And — the key insight — **you cannot hardcode
  your way out of it**: there are unboundedly many such failure modes across union/cut/fillet/loft/…
  Patching each is whack-a-mole.
- **The principled fix (4 general moves, not per-shape patches):**
  1. **AVOID the fragile operation by default.** A real multi-part object is an *assembly of parts
     that TOUCH*, not a fused blob. Coherence is verified by CONTACT (and Fix-A snap guarantees it),
     so a chair built as separate `attach`-ed parts needs **no boolean fuse at all** — the entire
     crash class disappears. `core.md` + the task START-HERE now make assembly-by-contact the DEFAULT
     for multi-part objects; `join`/`cut` is reserved for a single monolithic body.
  2. **One general robustness wrapper for the booleans that remain** (`kernel._robust_boolean`,
     used by BOTH `_fold` and `_fold_seq`, for union/cut/intersect alike): try a tight boolean, then
     HEAL (`clean`) both inputs and RETRY with escalating FUZZY tolerances, validating the result —
     so the *same* mechanism protects every fuse regardless of where the geometry came from
     (primitive OR custom). (In testing this actually *recovered* the swept-arm fuse that used to
     crash.) Not a per-op patch — one wrapper, all booleans.
  3. **Structured, design-level failure feedback** (`GeometryCombineError`): if a fuse genuinely
     can't be made after healing+fuzzy, the agent gets an *actionable* message ("too thin/tangent to
     fuse — make each piece its own part and `attach` them") instead of a raw `Null TopoDS_Shape`.
  4. **Always-deliver checkpoint** (Issues 9/18/20) so a residual failure never zeroes the run.
- **Lesson:** geometry-kernel fragility is inherent and unbounded — don't hardcode each failure.
  Avoid the fragile path by design, put ONE general robustness layer on the rest, turn genuine
  failures into design feedback, and guarantee delivery. Four principles cover the whole class.

### Issue 20: a banked PASS was lost because the engine RAISES on a no-FINAL run
- **What happened (concrete, run 2026-06-26T23-29):** the agent reached a geom-PASS (its build was
  banked to the checkpoint) but ran out of budget before FINAL — and **no artifact was delivered**,
  even though the checkpoint chain works in isolation (Issue 18 / B0 proved it).
- **Root cause:** when the agent exhausts its call budget WITHOUT a FINAL, the fast-rlm engine
  `throw`s ("Did not finish the function stack before subagent died") and `_runner.py` re-raises it,
  so `result = fast_rlm.run(...)` in `run_pipeline` **raises** — and every line after it, including
  the checkpoint promotion, is skipped. My Fix-B guard wrapped the *post-run gate*, but the raise is
  at the `fast_rlm.run` *call itself*.
- **The fix:** wrap the `fast_rlm.run(...)` call; on any exception, call `_fail(..., checkpoint_path=...)`
  which promotes the banked candidate before failing. Proven by
  `tests/test_checkpoint_e2e.py::test_delivery_survives_fast_rlm_raise` (engine raises → best-effort
  artifact still delivered).
- **Lesson:** the "never deliver nothing" guarantee must survive the engine *raising*, not just
  returning — put the delivery hook around the engine call, not only after it.

### Issue 21: the agent burned its whole budget READING a bloated context before building
- **What happened (concrete):** with the context grown to ~33 KB, the agent spent ~36 of 50 steps
  printing/re-printing its instructions in slices and exhaustively browsing the KB before its first
  build. The agent only "sees" what it prints (the engine shows a 200-char preview), so a large
  context is *expensive* in budget terms.
- **Root cause:** the auto-generated idioms skill (~7.3 KB of full signatures) + an explore-first
  framing + no "build early" directive. Capability we *added* ironically drowned the agent.
- **The fix (capability-preserving):** compact the idioms skill (~7.3 KB → ~1.4 KB: op NAMES per
  group + selectors + the verified "does-NOT-exist" list; full signatures become a lazy
  `cadquery_doc(id)` lookup), and add a front-loaded **START HERE** block (the parse helpers, "build
  early, don't re-read", assembly-by-contact, lazy lookups) so the essentials are in the first thing
  the agent reads. A `tests/test_context_size.py` cap bounds future bloat while asserting the
  load-bearing contract survives. core.md and the primitive catalog are NOT gutted.
- **Lesson:** in an RLM, the agent pays (in budget) to read its own instructions — keep them lean
  and front-load the build contract; reliability lives in host gates, not prompt volume.

---

## Phase 7 — the mating-quality gate: parts that TOUCH vs parts that are DUG INSIDE

The latest office-chair run (`logs/geometry_planning_2026-06-27T00-39-34-929Z.jsonl`) finally
SUCCEEDED — a real FINAL, 36 steps, 22 parts, all placed by `attach`, verdict PASS. But the rendered
chair showed the backrest **dug into** the seat and a visible seam. The model was *sound and
coherent* yet visually wrong. Tracing the run exposed three connected, GENERAL gaps.

### Issue 22: coherence proved parts TOUCH, but never that they don't BURY into each other
- **What happened (concrete):** the verify battery checked per-part soundness + contact-connectivity
  (`abs(signedDist) ≤ 0.5mm`). Because `_pair_min_distance` takes `abs()` of the signed distance, a
  part **overlapping** another reports the same ~0 distance as a part **flush** against it. So a
  backrest slab driven 16mm into the seat passed coherence identically to a clean mate — the host had
  no notion of interpenetration. The fidelity critic *saw* it ("flat blocky slab") but is advisory.
- **Root cause:** "one connected cluster" is necessary but not sufficient for a good assembly; it says
  nothing about HOW parts meet. There was no measure of overlap volume anywhere in the host.
- **The fix (general, principled — NOT a chair rule):** in `verify_assembly_coherence`, for every
  pair whose bounding boxes overlap (a cheap broad-phase), measure the **intersection volume** and
  classify by the containment ratio `c = V∩ / min(volA, volB)`:
  below an absolute floor → flush contact (OK); `c ≤ 0.2` → a small **joint/convergence** overlap (OK
  — this is how radial spokes meet a hub, or parts take a little interference to fuse); `c ≥ 0.75` →
  an **intended insertion** (peg-in-hole, telescoping cylinder, a spine embedded in a cushion — OK);
  **in between → a part is substantially BURIED in another → a hard `no_interpenetration` FAIL** that
  withholds the token. Tunable via `FORGECAD_CONTAINMENT_RATIO` / `FORGECAD_OVERLAP_MINOR_FRAC` /
  `FORGECAD_OVERLAP_FLOOR`. All volume math is **fail-open** (a boolean error → 0, never crashes the
  verdict). To keep "never deliver nothing", a sound+coherent-but-interpenetrating candidate is banked
  at a NEW last-resort checkpoint rank (0.5, always `needs_review`, never token-minted).
- **The trap we avoided (this is the whole point):** a naive "any overlap fails" gate would have
  broken this very chair (the gas-lift telescoping, the reinforcing spine in the cushion) AND every
  radial base (5-star legs / 3 arms legitimately overlap each other ~1–5% at the hub — confirmed when
  an early version regressed `test_coherent_placement` + `test_robust_combine`). The containment-ratio
  band is what separates *intended* insertion/convergence from the *defect* of partial burial.
- **Lesson:** "is it connected?" and "do the parts mate cleanly?" are different questions — the second
  needs overlap VOLUME, classified by intent (insertion vs convergence vs burial), not surface distance.

### Issue 23: the contact snap closed gaps by SHOVING parts through each other
- **What happened (concrete):** the run's snap log shows `backrest_spine→mechanism_box 22.5mm`,
  `backrest_cushion→backrest_spine 16.07mm`, `headrest→backrest_cushion 15.47mm`. The snap moved parts
  16–22mm to force contact — and that heavy shoving is exactly what buried the backrest in the seat.
- **Root cause:** the old snap stepped a part toward the target's **center** by `gap + eps` per
  iteration. Center-to-center is the wrong direction (it doesn't track the true surface gap) and
  `gap + eps` overshoots — so it either left a residual gap (undershoot) or drove the part past contact
  into the target (burial). Closing one seam created an overlap on the other side.
- **The fix (general):** rewrite `snap_assembly_to_contact` to move along the **true contact normal**
  using MeshLib's closest surface points (`findSignedDistance(...).a.point / .b.point`) by **exactly
  the surface gap**, so the surfaces meet **flush** and the snap **stops at contact**; if a move would
  bury the part (creates intersection volume) it backs off. Still INTENT-ONLY (only attach-declared
  parts move; absolute-position parts never move) and FAIL-OPEN (falls back to the legacy
  center-to-center step if closest points are unavailable; any error leaves the part as-is).
- **Lesson:** "snap to contact" must mean *land flush at first contact*, not *travel until the
  distance metric reads zero* — direction and stopping condition matter as much as the magnitude.

### Issue 24: anchor-mating misfired on curved/rotated parts, so the agent hand-rolled offsets
- **What happened (concrete):** in step 31 the agent used the correct semantic mate
  (`at:'top'/my_anchor:'bottom'`) and got GAPS + a disconnected backrest; in step 33 it gave up and
  switched to `at:'center'/my_anchor:'center'` + hand-computed `[dx,dy,dz]` numbers for all 22 parts.
  Hand arithmetic across 22 parts is where the imprecise placement (and the burial) entered.
- **Root cause:** `_anchor_point` resolved `top/bottom/left/...` via **BREP face selectors**
  (`wp.faces('>Z')`). That is exact for boxes/cylinders but unreliable for `swept_circle` / `lofted_box`
  / `revolved` / rotated parts — the selected face's centroid is not the geometric extreme, so the
  mate landed off and left a gap. The agent correctly stopped trusting anchors and routed around the
  weakness with manual offsets — a *platform* gap, not an agent failure.
- **The fix (general):** derive anchor points from the part's **axis-aligned bounding box** (a named
  face pins its axis to the bbox min/max; an edge → shared bbox edge midpoint; a corner → bbox corner),
  which is well-defined and FLUSH for ANY primitive and ANY rotation. BREP selectors remain only as a
  fallback if the bbox is unavailable. Now `at:'top'/my_anchor:'bottom'` lands flush directly, so the
  agent no longer needs to hand-compute center-to-center offsets.
- **Lesson:** when the agent abandons the *right* API for a fragile workaround, fix the API in host
  code — don't instruct the agent to "try harder" with the broken one.

---

## Phase 8 — three failure CLASSES (not three bugs): why each run kept finding "one more thing"

The run after Phase 7 (`logs/geometry_planning_2026-06-27T08-46-02-655Z.jsonl`, 47 steps) reached a
clean PASS (step 43: 7 parts sound, one cluster, **no_interpenetration** — the Phase-7 mating gate
WORKED, catching `left_armrest`/`right_armrest` buried 43% into `seat_cushion`) and the agent FINAL'd
a valid token (step 46). And yet on disk it delivered `exports/besteffort_Ergonomic_Office_Chair.*` —
**NOT** an accepted `output_*`. A genuinely-verified chair was thrown away.

That triggered the real question: *why does almost every run surface a new thing to fix — are we
bandaging?* The honest answer is that a **stochastic generator samples a different path through the
host every run**, so different latent host gaps surface. The cure is to fix the **class**, and above
all to honour the founding principle: **no reliability outcome may depend on the agent's luck.** Two
*kinds* of gap exist, and conflating them is what felt like whack-a-mole:

- **Invariant violations (must be zero; patching the instance IS a bandage).** A sound result
  depending on agent luck; a sound model silently lost; the gate accepting something unsound.
- **Capability gaps (expected growth; fine *if they fail safe*).** The agent authors a legal request
  the host can't yet build cleanly. These keep appearing as we attempt harder shapes — that's not
  regression, **as long as** they fail loudly (verify catches it, the agent iterates or best-effort
  delivers) and never silently corrupt or get accepted.

Phase 8 closes the three classes that this run exposed.

### Issue 25 (INVARIANT): the token pinned REPRESENTATION, so acceptance depended on agent luck
- **What happened (concrete, on disk):** the token was minted at step 43 on `chair_plan_v3`, which
  had **no `contains_freeform` key**. At step 45 the agent built `final_plan = v3.copy()` and added
  `final_plan["contains_freeform"]=False` (it is in the schema, so the agent dutifully set it) plus
  the measured `overall_dimensions`, and FINAL'd that. `attestation` excluded only
  `verification_token` + `overall_dimensions` from the hash — **`contains_freeform` was still hashed**
  — so adding it changed `canonical_plan_hash`, `verify_token` mismatched, and the orchestrator
  discarded a real PASS. The best-candidate checkpoint then delivered it as `besteffort_*`.
- **Proof it was luck:** the *previous* run (`…00-39`) happened to include `contains_freeform` in the
  dict **before** verifying (mint hash == FINAL hash) → **accepted** (`output_*`). Same chair, same
  agent, opposite outcome — decided purely by the incidental order in which the agent set one field.
- **Root cause (the class):** the token must pin the *authored geometry*, but it was pinning the dict
  *representation*. So ANY benign drift between verify and FINAL broke it: an added/derived field
  (`contains_freeform`), `int`↔`float` (8 vs 8.0), key reorder, a filled default, a re-serialization.
- **The fix (`cad_kernel/attestation.py`):** `canonical_plan_hash` now NORMALIZES through the schema
  first — `GeometryPlan(**plan).model_dump(mode="json")`, drop `verification_token` +
  `overall_dimensions`, sorted-compact JSON, sha256. Normalizing fills derived fields and coerces
  types **identically** at mint (kernel server) and gate (orchestrator), so the hash depends only on
  the geometry. **FAIL-SAFE:** any import/validation error falls back to the old raw-dict hash, so the
  gate never crashes. Forgery protection is unchanged — a real geometry change still changes the
  normalized form, and the per-run secret is still required to mint.
- **Why general, not a bandage:** it removes the *entire* representational-noise class at once (not
  just `contains_freeform`), and — crucially — it deletes a dependence on agent stochasticity, which
  is the one thing the platform philosophy forbids.
- **Lesson:** if whether a run is accepted can change because the agent set a field in a different
  order, that is an invariant violation — fix it in host code so the outcome can never depend on luck.

### Issue 26 (CAPABILITY): swept solids self-intersect on sharp turns, reported only as a raw count
- **What happened:** ~6 of the 47 steps (22, 23, 27, 28, 30, 31) were spent trial-and-erroring ONE
  base arm. Step 30 (`swept_circle` radius 10, sharp path) → "not watertight, **711 self-intersecting
  triangle(s)**"; step 31 (radius 6, smoother path) → PASS. The `swept_circle` template did a plain
  `circle(r).sweep(polyline(path))` (CadQuery default `transition='right'`), which self-intersects
  when the path bends sharply relative to the tube radius — and the feedback named no cause.
- **Root cause (the class):** a legal plan that BUILDS an unsound solid, with only a triangle count to
  go on, forces the agent to guess radius/path. Lofts and revolves share the shape of this problem.
- **The fix (`cad_kernel/kernel.py` + `schemas/primitives.json` + `verify.py`):**
  - `swept_circle` is now a kernel HELPER (the template delegates: `swept_circle({radius}, {path})`).
    `_robust_sweep` builds the section FRESH each attempt (`.sweep()` *consumes* the pending wire — a
    reused section silently raised "No pending wires present", which was its own bug), tries the
    faithful path first (so an already-sound sweep is returned UNCHANGED — zero regression), then a
    rounded transition, then ONE light Chaikin corner-round when the path is sharp, and PREFERS the
    first candidate that meshes SOUND — so an alternative is used only if it is genuinely sound and
    can NEVER make a result worse than the plain sweep. Fail-open to the plain sweep otherwise.
  - **Honest finding:** a tube of radius 10 on a 5 mm segment is *genuinely ill-posed* — neither a
    rounded transition nor corner-rounding fixes it (and 2+ Chaikin passes make it WORSE by creating
    many short segments). No construction trick can save a tube fatter than its turn.
  - So the real capability win is the **universal diagnostic**: `verify._construction_hint` now turns
    an unsound swept/lofted/revolved part into a SPECIFIC message — *"a sweep self-intersects because
    its cross-section is too large for the local path/feature; reduce the radius/section size or
    lengthen/smooth/space the path — no corner treatment can save a tube fatter than its turn"* —
    wired into the assembly `parts_sound` detail and the single-solid `watertight`/
    `no_self_intersections` detail. That converts ~6 steps of blind guessing into one directed fix.
- **Why general:** the robust sweep helps every moderate swept case and never regresses a good one;
  the diagnostic covers sweep/loft/revolve uniformly and is driven off `primitive_type`, not the chair.
- **Lesson:** prevent what you can at construction, but when a shape is genuinely ill-posed, the
  capability increase is a *precise* diagnosis — not a silent, still-broken build.

### Issue 27 (CAPABILITY/FRICTION): `attach.to` could not name a PART, only a step
- **What happened:** step 40 → `placement error: step 11 attaches to unknown target 'backrest'`. The
  agent had built a multi-step `backrest` part (`backrest_outer` + `backrest_spine`) and attached the
  headrest to the PART name `"backrest"`; the kernel only resolved a step `name`/`sequence_id`.
- **Root cause (the class):** in an assembly the agent reasons in PARTS (which may be several steps),
  but `attach.to` spoke only STEPS — a model mismatch between agent and kernel.
- **The fix (`cad_kernel/kernel.py::build_plan/resolve`):** a `part_members` map is built; if
  `attach.to` matches no step, it is resolved against PART-group names by anchoring to the COMBINED
  bounding box of that part's resolved member steps. A step `name`/`id` keeps priority (no behavior
  change for existing plans); a genuinely unknown target still errors. The snap's `group_targets`
  now also maps a part-group name to itself.
- **Why general:** it aligns the placement API with how the agent already thinks ("mate to the
  backrest"), for any multi-step part — no chair logic.
- **Lesson:** when the agent's natural mental model (parts) doesn't match the kernel's (steps), extend
  the kernel to speak the agent's model rather than forcing the agent to track sub-steps.

---

## Phase 9 — the single_solid MONOLITHIC-FUSION path (the impeller class)

The chair is an `assembly` (parts kept separate, combined by contact — no boolean fuse), so it never
exercised the single_solid boolean-fusion path. The impeller (a hub + N fused blades) is the first
object that genuinely needs it, and it exposed a silent correctness bug plus a capability gap.

### Issue 28 (INVARIANT): a `join` silently DROPPED the largest body, and verify rubber-stamped it
- **What happened (`logs/geometry_planning_2026-06-27T12-34-17`):** hub (`revolved_profile`) + bore
  (`cylinder` cut) alone PASSED (~70,607 mm^3, hub visible). Adding ONE clean blade with
  `operation:join` → PASS but volume **1,658 mm^3** = the blade ONLY; the hub vanished. 14 blades →
  14 disconnected components, no hub.
- **Root cause:** `kernel._combined_ok(out,"union")` only checked `volume > 1e-9`. A union whose
  result shrank BELOW its largest operand (impossible for a real union → a body was dropped) was
  accepted, and `verify_solid` had no "a fuse must not lose a body" invariant — so a corrupt
  single_solid PASSed.
- **The fix (host-side, two layers):** (1) the combine is now VOLUME-MONOTONIC — `_combined_ok`
  rejects a union result smaller than max(operand volumes) − tol, and `_robust_boolean` escalates to
  a SHAPE-LEVEL `cq.Shape.fuse` on the raw solids when the Workplane union drops a body, raising a
  structured `GeometryCombineError` only if every attempt fails (cut/intersect unchanged; fail-open
  when volume can't be measured). (2) a verify BACKSTOP — the kernel records each additive (new/join)
  body's volume (`_fusion_audit`) and `verify_solid` FAILs `no_dropped_body` if the fused single_solid
  is smaller than the largest additive body minus what cuts remove (conservative; skipped on
  intersect/modifier; fail-open).
- **Lesson:** a boolean must never silently lose geometry, and the gate must catch it — fix the
  combine AND make the loss loud.

### Issue 29 (CAPABILITY): patterned fusion + a general twisted-feature technique
- The general path "N twisted blades fused to a hub" already existed (`lofted_sections`/`swept_profile`
  + radial `pattern` + `operation:join`); only the fold bug blocked it. With Issue 28 fixed, a single
  radial-patterned `join` step now fuses N copies into ONE sound connected body (proven: a 7-blade
  impeller, one component, PASS).
- Added ONE general TECHNIQUE primitive `twisted_loft` (loft a profile through stations
  `[z, radius, twist_deg, scale]`) — object-agnostic (blades/vanes/augers/flutes/twisted columns),
  host-built from numbers (low hallucination), routed through the same robust loft + the specific
  construction diagnostic. It is NOT a vane recipe — it is the same class as `swept_profile`/
  `lofted_sections`.
- **Lesson:** the cure for "the next object is a new weak case" is a reliable, composable GENERAL
  path (technique + invariant), not a per-object primitive.

## Phase 10 — the token must pin GEOMETRY, not descriptive metadata

### Issue 30 (INVARIANT): a metadata edit after verifying discarded a genuinely-verified impeller
- **What happened (`logs/geometry_planning_2026-06-27T16-51-42`):** the agent minted a token on a
  PASSing impeller, then before FINAL changed the `title` and added an `assumption` (pure descriptive
  metadata). `attestation.canonical_plan_hash` hashed those fields → hash mismatch → the orchestrator
  discarded a real PASS and shipped `besteffort_` instead of `output_`.
- **Root cause:** the hash covered the whole normalized plan minus only `verification_token` +
  `overall_dimensions`. Metadata (`title`/`assumptions`/`clarifications`/`engineering_requirements`/
  per-step `rationale`) does NOT affect the built solid, yet broke the token — acceptance depending on
  the agent's incidental edits (the forbidden dependence, one field deeper than Issue 25).
- **The fix:** `canonical_plan_hash` now projects the schema-normalized plan to its
  GEOMETRY-DETERMINING fields only — `assembly_kind` + each step's `primitive_type / parameters /
  operation / position / rotation / attach / pattern / part / name` — and hashes that. A real geometry
  change still changes the hash; the per-run secret is still required → forgery protection unchanged.
  Removes the entire "metadata edit breaks the token" class.
- **Lesson:** the token must mean "this GEOMETRY was verified," not "this exact dict including prose."

## Phase 11 — front-of-pipeline robustness: no-image parity, accessible clarifier, size gate

With the geometry spine solid, the remaining weaknesses were BEFORE the agent builds.

### Issue 31 (CAPABILITY): a no-image run was weaker than a with-image run
- With a reference image the host extracts a FORM BRIEF (structure/orientation) AND the critic does a
  strict grounded design review. Without an image there was NO brief and only a weak "recognizable?"
  critic — so no-image output was blockier with no design pressure.
- **The fix (P1+P2):** `fidelity.extract_design_brief_from_text` reasons the canonical FORM BRIEF from
  the TEXT description (the multimodal model in text mode); `run_pipeline` injects it when no image is
  given. The no-image critic now judges against that brief (structure/proportion/orientation/
  refinement) rather than just "recognizable." Still advisory; the WITH-IMAGE path is byte-for-byte
  unchanged; fail-open throughout.

### Issue 32 (UX): the clarifier was a bottleneck for non-technical users
- It asked in jargon ("IP rating", "load path") with no examples or escape.
- **The fix (P3+P4):** `CLARIFIER_ROLE` now targets only the NON-NEGOTIABLES (overall size, count of
  the main repeated feature, critical orientation/mounting, geometry-changing material), in plain
  language with concrete example answers and a "not sure / use standard defaults" escape — usable by
  technical and non-technical users alike. Vague/blank answers normalize to a recorded default
  (`_normalize_clarification_answer`) so downstream intent is deterministic.

### Issue 33 (ROBUSTNESS): an explicit user-stated dimension was not enforced
- `overall_dimensions` is advisory (emergent size, Issue 6). But an EXPLICIT user-stated size is a
  non-negotiable.
- **The fix (P5):** the orchestrator extracts an explicit numeric dimension (`_extract_size_constraint`)
  into a conservative max-envelope cap (1.15×, a gross-oversize guard) passed via
  `FORGECAD_SIZE_CONSTRAINT`; `verify_solid` adds a HARD `size_envelope` check (FAIL if the model's
  largest extent exceeds the cap). No stated dimension → no gate; emergent proportions stay advisory;
  fail-open.

All Phase 9–11 fixes are deterministic, host-side, and fail-open. The offline suite is **45/45**
(40 + 5 new front-of-pipeline tests: `test_text_brief`, `test_no_image_bar`, `test_clarifier_accessible`,
`test_clarifier_normalize`, `test_size_envelope`; plus `test_single_solid_fusion`, `test_impeller_e2e`).

---

## Phase 6 — closing summary: what these fixes guarantee, and where the honest line is

The Phase 6 changes attack one disease — *a run that builds a good model can still deliver nothing* —
from both ends: never lose a sound result, and stop the agent from getting stuck.

**Guaranteed deterministically (host-enforced; proven by the test suite, no vision/Deno needed):**
- A run NEVER yields nothing when a sound + coherent model was built at any point — the best-candidate
  checkpoint is promoted at run end even on budget-exhaustion/no-FINAL (Issue 9).
- `attach` is an UNBREAKABLE contact guarantee — a part that attaches to a target is snapped into
  contact even if the model's offset drifts it off, so a fully-attached design can't float apart and
  become undeliverable; absolute-position parts are untouched so genuine errors still surface (Issue 17).
- PARTS MATE CLEANLY, NOT JUST CONNECT: anchors are resolved from the bounding box (flush for any
  primitive/rotation), the contact snap lands parts FLUSH along the true normal without burying them,
  and a hard mating gate FAILs a part substantially BURIED in another ("dug inside") — while ALLOWING
  flush contact, small joint/convergence overlaps, and intended insertions (peg/telescope/embedded
  spine). A sound-but-interpenetrating model is still banked at a last-resort rank so delivery holds
  (Issues 22–24 / Phase 7).
- ACCEPTANCE NEVER DEPENDS ON AGENT LUCK: the token now hashes a SCHEMA-NORMALIZED form of the plan,
  so a genuinely-verified plan survives the benign edits the agent makes before FINAL (a derived
  field like `contains_freeform` appearing, int↔float, key order, a re-serialization) — yet a real
  geometry change is still rejected. The same-chair "accepted vs best-effort by luck" split is closed
  (Issue 25 / Phase 8).
- CURVED PARTS BUILD OR EXPLAIN THEMSELVES: swept construction prefers a mesh-sound candidate
  (rounded transition / light corner-round) and never regresses a good sweep; a genuinely ill-posed
  sweep/loft/revolve (a section fatter than its turn) FAILs with a SPECIFIC cause+fix, not a raw
  triangle count (Issue 26 / Phase 8).
- THE AGENT CAN MATE TO A PART, NOT JUST A STEP: `attach.to` resolves a PART-group name (a multi-step
  part) by its combined bbox, so "mate to the backrest" works without naming a sub-step (Issue 27).
- Fidelity can never *block* a sound model; it only grades the trust tier (Issue 10).
- DELIVERY IS AGENT-INDEPENDENT: every host-verified geom-PASS is banked to the run checkpoint and
  promoted at run end on any non-clean exit — including a raw post-run exception AND the engine
  RAISING when the agent never FINALs (budget exhaustion) — so a passing model is delivered even if
  the agent never FINALs or mis-reads its tools (Issues 18, 20 / B1, C4).
- CURVED MULTI-PART OBJECTS BUILD: the default path is an assembly of parts that TOUCH (no boolean
  fuse — the fragile op is avoided), and the booleans that remain go through ONE robust combine
  (heal + escalating fuzzy tolerance) that raises a structured design-level error rather than a raw
  OCC null. So fusing swept/curved geometry no longer aborts a build opaquely (Issue 19 / C1–C3).
- The agent reaches BUILDING fast: the injected context is bounded and front-loads a build-first
  START-HERE block, so the budget goes to building, not re-reading (Issue 21 / C5).
- The agent can READ the verdict/token natively: the key MCP tools return a dict-compatible
  `ToolResult`, so FastMCP emits unwrapped `structuredContent` and `mcp_call` returns a real dict —
  `result["verdict"]`/`isinstance(result, dict)` work (json.loads idiom kept as fallback) (Issue 18 / B2).
- The agent is grounded on the REAL CadQuery API (idioms skill) and invented methods are caught in
  milliseconds with a precise fix (lint), before the slow build (Issues 12–13).
- Curves are buildable by parameter-filling general technique primitives, not fragile free-code
  (Issue 14).
- The model's spatial intent renders faithfully — radial/array assemblies connect — and bad placement
  gets an instant, precise gap message (Issue 15).
- Sub-agents: spawning is the RLM's call (not prompt-scripted); the host only requires that a child
  doing geometry be granted the kernel MCP, and delivery is guaranteed by the checkpoint regardless
  (Issues 16, 18).

**Still perceptual / needs the live machine (NOT bit-repeatable — Deno + a real vision endpoint + a
valid `FORGECAD_VISION_MODEL`):** whether a given run's chosen model is *judged* "certified" vs
"needs_review", and whether the parallel strategies actually produce a refined, well-oriented form.
That is the design-taste loop and is inherently a judgment, not a formula. What Phase 6 guarantees is
that this judgment now only *grades and guides* — it can no longer turn a real, sound, buildable
result into nothing.

**Verification:** all 29 test files pass offline
(`for t in tests/test_*.py; do .venv/bin/python "$t"; done`). The fast-rlm engine was NOT modified —
every fix is host-side (kernel, geometry_server, orchestrator, schemas, skills, tools, run.yaml).
