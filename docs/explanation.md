# explanation.md — How the ForgeCAD platform works (for a teammate)

This is a plain-language tour. No deep CAD or AI background needed. We'll use one running example
the whole way: **"design an office chair."**

---

## 1. What it does
You type a plain-English request — *"design an office chair"* — and the platform produces a **real,
verified 3D model** you can export (STL/STEP files), plus a step-by-step record of how the AI got
there. It's not a picture; it's an actual buildable solid that has passed a battery of checks.

## 2. The big idea (the analogy)
Most "AI makes CAD" demos do this: the AI writes a design once and hopes it's right. Ours does
something stronger. Think of an **AI craftsman who, in one continuous sitting:**
1. sketches a plan,
2. builds a real prototype,
3. inspects it against fixed quality checks,
4. fixes whatever fails,
5. and only hands it over when it genuinely passes.

The whole point is that last part: **the AI must prove its design is sound by building and checking
it itself — before it's allowed to say "done."**

## 3. "One AI call does everything" and "stateful" — what that means
The AI works inside a sandbox that behaves like a **Jupyter notebook**: it writes a little bit of code,
runs it, sees the result, and continues — **remembering everything as it goes.** It does *not* restart
for each step.

Example, in one session:
- It drafts the chair plan (a list of parts).
- It builds it and the result says *"the left armrest is floating 150 mm from the seat."*
- It fixes *just that part* and rebuilds — keeping all its other work.
- It repeats until everything passes, then finalizes.

That "remembers everything and iterates without starting over" property is what we mean by
**stateful**, and doing the entire job — plan, build, check, fix, finalize — in that single ongoing
session is what we mean by **one AI call does everything**. For very large jobs it can also spawn
**helper sub-AIs** (e.g. "you design just the base") and combine their results.

## 4. The deterministic spine — who is trusted to do what
This is the most important design decision:

- **The AI proposes.** It writes the *plan* (which shapes, what sizes, how they connect).
- **The trusted host code builds and grades.** Turning the plan into a solid, and checking it, is done
  by fixed, human-written code — never by the AI.
- **The AI is never allowed to grade its own work.**

Analogy: a **student proposes an answer; a fixed exam grades it.** If the student also wrote the exam,
the grade would be meaningless. Because grading lives in trusted code, the output can be trusted.

## 5. The tamper-proof stamp (why "done" can't be faked)
"Done" is impossible unless the inspection step issues a **stamp** (we call it a verification token).
Only a *genuine* pass produces a valid stamp, and the stamp is signed with a secret the AI never sees,
so it **can't forge one.** Early on, the AI tried to finish by writing a fake stamp ("I am unable to
obtain a verification token") — the host rejected it instantly. No real pass, no stamp, no finish.

## 6. The pieces — what each file does (plain English)

A few unavoidable terms, defined once:
- **RLM** = the recursive AI runtime (the package `fast-rlm`) — the "brain runtime" that runs the AI.
- **MCP** = a standard way for the AI to *call host tools* (like the AI phoning a service desk).
- **WASM sandbox** = a safe mini-Python the AI writes its thinking-code in, with no direct access to
  your machine (so it can't run the real CAD engine itself — it must ask the host).

| File / folder | Plain-English job |
|---|---|
| `orchestrator.py` | **The conductor.** Asks the clarifying questions, starts the AI session, runs the final authoritative inspection, then saves and exports the result. |
| `fast-rlm` (in `.venv`, we don't change it) | **The brain runtime.** Runs the AI in its notebook-sandbox and lets it spawn helper sub-AIs. |
| `schemas/primitives.json` | **The catalog of building blocks** (box, cylinder, I-beam, flange, pipe, dome … plus shaping verbs like fillet/loft/shell) — each with its exact recipe and what to measure. The single source of truth. |
| `schemas/geometry_plan.py` | **The contract / form.** Defines exactly what a valid design must look like, so a half-baked plan is caught early. |
| `cad_kernel/kernel.py` | **The builder.** Turns a plan into a real 3D solid — the same way every time. |
| `cad_kernel/verify.py` | **The inspector.** The fixed checks: positive volume, watertight (no holes in the surface), one coherent connected object, no parts passing through each other. |
| `cad_kernel/fidelity.py` | **The design reviewer.** Looks at a rendered picture and judges whether it actually looks like what was asked. |
| `cad_kernel/attestation.py` | **The stamp machine.** Creates and checks the unforgeable verification token. |
| `cad_kernel/geometry_server.py` | **The workshop the AI calls.** One request does build + verify + render + review and hands back a verdict, a picture path, and (on a pass) the stamp. |
| `tools/host_mcp.py` | **The help desk the AI calls.** "Check my plan," "ask the user a question," "look something up in the CadQuery manual." |
| `tools/clarify_io.py` | **How a question reaches you** (a popup, or the terminal). |
| `skills/core.md` (+ `freeform.md`, `assembly.md`) | **The AI's rulebook / playbook** — how to plan, connect parts, and finish. |
| `cadquery_kb_pack/`, `meshlib_kb_pack/` | **The reference manuals** for the CAD library (CadQuery) and the mesh-measuring library (MeshLib). |
| `plan_store.py` | **Memory across runs** — so next time you can say "make it taller" and it reuses the last accepted design. |
| `trace_view.py` | **A replay viewer** — shows, step by step, what the AI did. |

## 7. A single run, end to end (the chair)
1. **Clarify.** Before planning, the conductor asks up to ~3 critical questions (e.g. "casters or
   stationary?") and feeds your answers in as fixed facts.
2. **AI session starts.** The AI looks at the catalog of building blocks and the rulebook.
3. **Draft.** It writes a plan: a hub, 5 legs, casters, a column, a seat, a backrest, armrests.
4. **Validate.** It asks the help desk "is my plan well-formed?" and fixes any structural errors.
5. **Build + verify + review.** It calls the workshop. The host builds the solid, runs the fixed
   checks (sound? one connected object?), renders a picture, and has the reviewer judge it.
6. **Fix and repeat.** If something fails — "the casters are floating," "the seat is a flat slab" — it
   gets a specific message (including, on connectivity problems, a description of the rendered picture)
   and fixes just that, then rebuilds. It keeps iterating in the same session.
7. **Get the stamp and finalize.** Once everything passes, the workshop returns the stamp; the AI puts
   it in the plan and finalizes.
8. **Host re-inspects (authoritatively).** The conductor independently rebuilds and re-checks the final
   plan and verifies the stamp — no trust in the AI's say-so.
9. **Render + export.** On a pass, it saves a picture and exports **STL** and **STEP** files.
10. **Save to memory + show the trace.** The accepted plan is stored for future edits, and you can
    replay exactly what the AI did.

## 8. Trust tiers
- **Certified** — built entirely from the exact catalog recipes (numbers only). Fully trusted.
- **Needs review** — the design used a "custom" freehand-code step for a shape no recipe covers. It's
  verified to be a *sound* solid, but a human should glance at it, because freehand code can't be
  certified as "the right object."

## 9. The honest note: facts vs opinions
Two different kinds of "correct" matter here, and the platform treats them differently:
- **Facts (deterministic):** Is it a sound solid? Is it one connected object? Is it the right size? Are
  the requested features present? These are measured by fixed host code and are exactly repeatable.
- **Opinion (a judgment):** Does it *look* like a well-designed chair? There is no formula for this —
  the only honest judge is a vision model, whose verdict can vary slightly run-to-run. We make that
  judgment as stable as possible by grounding it against a confirmed reference image, but it is, by
  nature, a judgment and not a guarantee.

Both are needed: the facts make the output **trustworthy**; the judgment makes it **good**.
