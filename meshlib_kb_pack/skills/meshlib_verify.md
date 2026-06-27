# SKILL: verifying built geometry (load only at the verify stage)

The VERDICT comes from a FIXED battery you do not control: positive volume,
watertight (closed mesh), expected component count, no self-intersections, and
measured bounding box vs declared. You cannot skip or weaken these.

What you MAY do:
- Read the fixed report from `verify_solid` and, on failure, use `localized_fix`
  to repair the offending step, then rebuild and re-verify.
- PROPOSE an advisory, shape-specific check (e.g. tooth count, hole count) by
  finding the right MeshLib function via `meshlib_search` / `meshlib_doc` and
  calling `run_advisory`. Advisory results FLAG concerns; they never certify a
  pass and never override the fixed verdict.

Never claim CERTIFIED for a freeform (`custom`) result — a passing battery means
SOUND and RIGHT-SIZED, not "the right object". It stays needs_review.
