# CAD RLM — Skills Overview

Welcome to the CAD Recursive Language Model (RLM) reasoning framework. This system utilizes a set of 8 structured reasoning guidelines (skills) stored in `skills/*.md` to guide planning, compilation, verification, and error recovery.

## The Multi-Phase Pipeline

```
  Phase 1: Planning (Root RLM)
    ├── intent_extraction.md       → Parse requirements, constraints, tolerances
    ├── part_decomposition.md      → Split complex request into solid parts
    ├── primitive_planning.md      → Select library primitives (18 schemas)
    ├── dimension_reasoning.md     → Calculate sizes, offsets, clearances
    └── verification_planning.md   → Define volume, bbox, face checks
    
  Phase 2: Code Gen (Root RLM)     → Compile to clean CadQuery script ('result')
  
  Phase 3: Execution (Root RLM)    → execute_cadquery() subprocess compiles STEP/STL
    └── [Retry Loop]               → repair_guidance.md (Repair Sub-Agent, max 3)
    
  Phase 4: Mesh Quality (Root RLM) → inspect_mesh() checks watertight/manifoldness
  
  Phase 5: Vision Verification    → verify_geometry() Gemini Vision Judge
    └── [Refinement Loop]          → refinement_guidance.md (Refine Sub-Agent, max 5)
    
  Phase 6: Trace & Export         → write_trace() trace.json & ForgeCAD export
```

## How to use Skills

- The **Root RLM** reads these skill files during initial planning to systematically formulate a structural plan.
- The **Sub-Agents** (Repair and Refinement) are spawned in isolated REPL environments with access to the relevant guidance files via `read_skill()` to isolate and fix specific issues.
