# Phase 3 — rich certified vocabulary: nouns (rich primitives) + verbs (composable shaping ops)

## The problem
Runs passed (sound, coherent, recognizable) but the OUTPUT was CRUDE — a blocky chair of plain
boxes/cylinders. Root cause: the vocabulary was only basic shapes, the skill said "prefer a
primitive whenever one fits," and the smart CadQuery operations (fillet, loft, revolve, shell)
were locked behind risky freehand `custom` code (non-deterministic — the model writes different,
often-broken code each run). The fix: give the agent CadQuery's power as DETERMINISTIC, certified,
numbers-only operations — the host owns the CadQuery wiring; the model supplies only numbers/points.

## The noun/verb framing
- **Nouns = builder primitives** (a frozen CadQuery template + numbers). The model picks one and
  fills in dimensions; the geometry logic is authored/tested once and cannot be altered by the
  model. Certified, deterministic.
- **Verbs = composable operations** that act on what was built. Same determinism (host owns the
  calls). This is the layer nouns can't provide: refine/round/hollow/contour ANY shape.
- The freehand `custom` + CadQuery KB path remains only for the genuine long tail (and feeds the
  promotion flywheel). The KB is the manual we read to author nouns/verbs — not something the model
  should improvise from live each run.

## Part 1 — adopted the rich primitives (VALIDATED)
`schemas/primitives.json` expanded from ~18 to **39** certified, numbers-only templates: structural
sections (`i_beam`, `c_channel`, `l_prism`, `t_prism`, `triangular_prism`, `trapezoidal_prism`,
`cross_prism`), fasteners/mechanical (`hex_nut_blank`, `hex_bolt_blank`, `shaft_with_keyway`,
`circular_flange`, `pipe`, counterbore/countersink blocks), and rounded/organic shapes
(`dome`, `capsule`, `slot_prism`, `elliptical_cylinder`, `elliptical_ring`). The dynamic schema,
the native tool, the host MCP tool, and the orchestrator all read this single file (Phase-0 single
source of truth), so wiring is automatic.

Critically (this is what makes it a fix, not a bandage): **every template was build-validated in
real CadQuery before being trusted.** Two were fixed during validation:
`shaft_with_keyway` (`extrude(..., combine="cut")` → `cutBlind(-key_length)`) and
`revolved_profile` (close the profile back to the axis with `.hLineTo(0).close()`). All 39 build
with defaults AND non-default params (verified). Added sanity validators (pipe wall<½OD,
elliptical_ring inner<outer, flange bolt-circle<OD and num_bolt_holes≥1).

## Part 2 — added the composable VERBS
- **Builder primitives for curved/contoured forms** (pure templates; list-valued params now
  supported in the schema via a `profile`/`path` type → `List[List[float]]`):
  `lofted_box` (contoured/tapered slab, e.g. a seat pan), `revolved_profile` (turned forms from a
  `[[r,z],...]` profile), `swept_circle` (a tube/handle along a `[[x,y,z],...]` path).
- **Modifier verbs** `fillet` / `chamfer` / `shell` (NOT in primitives.json — a small explicit
  registry so the template/eval path stays clean). They REFINE the running solid at their position
  in the sequence: the kernel skips raw-building them, and `_fold_seq` applies `_apply_modifier`
  (host-owned `.edges(sel).fillet(r)` / `.chamfer(d)` / `.faces(sel).shell(-t)`) in place. Edge/face
  keywords are from a fixed allowed set (`all|vertical|top|bottom`, faces). A modifier with no prior
  solid, or a too-large radius, returns a clean actionable error (verified).

## Part 3 — flipped the skill
`orchestrator.generate_primitives_summary()`, `skills/core.md`, and the task instructions now say:
*build like a real manufactured part — choose the operation that matches the FORM; ROUND / CONTOUR
/ HOLLOW with fillet/chamfer/shell and lofted_box/revolved_profile; do NOT leave sharp blocky
boxes; use `custom` only for a genuinely unique shape no primitive or verb can express.* Removed the
old "prefer a primitive whenever one fits" bias; fixed the stale `pipe`→hollow_cylinder confusable
(`pipe` is now a real primitive).

## Why this is the complete, non-bandage answer
Nouns + verbs together mirror what CadQuery itself is — a small composable set that builds anything
— but DETERMINISTIC and certified, with the model only ever supplying numbers/points, never
freehand code. That is "providing the mathematical intelligence in the host": the agent composes;
the kernel does the loft/revolve/fillet/shell math, identically every run.

## Verified here — tests/test_rich_primitives_and_verbs.py (8/8)
All 39 primitives build (defaults + non-defaults); fillet rounds (64000→61592 mm³); shell hollows
(64000→21228); revolved_profile/list-params validate + build; too-large and no-prior modifiers
fail cleanly; sanity validators reject bad pipe/flange; a refined mini-assembly (lofted seat +
filleted backrest, mated) is coherent + sound. Full regression: all 18 test files pass
(`test_host_mcp` updated off the hardcoded count). Phase 0/1/1b/2 guarantees intact. fast_rlm
engine untouched.

## Needs the live machine
Whether the agent now REACHES FOR the richer vocabulary (it's skill-driven, so a live run confirms
behavior). The substrate — every primitive and verb building correctly, deterministically — is
proven here.
