# Available Skills

Use `read_skill(name)` to load any skill file.

**Start here:** read `playbook` FIRST — it gives your role, tools, the skill read-order, and the full program flow.

## Core Reasoning Skills (portable — use in any CAD geometry system)

- `playbook`               ← read first, every run (system-specific bridge)
- `decompose_and_select`   ← Phase 1: extract intent, build CSG tree, match shapes to vocabulary
- `compute_dimensions`     ← Phase 2: compute positions, clearances, half-height stacking, volumes
- `predict_and_verify`     ← Phase 3: predict volume/bbox/face-count, set pass/fail thresholds

## On-Demand Skills (loaded only when triggered)

- `debug_cadquery`         ← load when CadQuery code fails (traceback → error category → fix)
- `refine_from_feedback`   ← load when replanning after verifier feedback (feedback → parameter fix)
