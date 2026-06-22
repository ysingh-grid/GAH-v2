# GAH Tools Pipeline — Session Summary

**Date:** 2026-06-19 | **Branch:** `lite-backend-integration`

---

## What's Built (tools/)

| File | Function | Done? |
|---|---|---|
| `execute_cadquery.py` | `execute_cadquery(code, run_id)` | ✅ |
| `inspect_mesh.py` | `inspect_mesh(stl_path)` | ✅ |
| `render_views.py` | `render_views(stl_path, run_id)` | ✅ |
| `verify_geometry.py` | `verify_geometry(prompt, code, metrics, render_png, prior_feedback)` | ✅ |
| `write_trace.py` | `write_trace(run_id, prompt, plan, code, exec_result, mesh_report, renders, verdict)` | ✅ |
| `load_trace.py` | `load_trace(run_id)`, `list_traces()` | ✅ |
| `read_skill.py` | `read_skill(name)`, `list_skills()` | ✅ |
| `primitive_lookup.py` | `lookup_primitive(key)`, `list_primitives()` | ✅ |

---

## Tool 1 — execute_cadquery

```python
execute_cadquery(code: str, run_id: str) -> dict
```

**What it takes:**
- `code` — full CadQuery Python script. Must define `result = cq.Workplane(...)` or similar.
- `run_id` — unique string, used to name output files.

**What it does:**
Spawns a subprocess, runs the CadQuery code inside it (because CadQuery needs OCCT/conda Python), exports the geometry as both `.stl` and `.step`, reads back basic metrics.

**Returns (success):**
```python
{
    "success": True,
    "volume": 24457.6,                           # mm³ from OCCT
    "bbox": {
        "xmin": -35.0, "xmax": 35.0,
        "ymin": -25.0, "ymax": 25.0,
        "zmin": 0.0,   "zmax": 30.0
    },
    "faces_count": 31,
    "step_path": "outputs/myrun.step",
    "stl_path":  "outputs/myrun.stl"
}
```

**Returns (failure):**
```python
{"success": False, "error": "CadQuery error message..."}
```

**Deps:** `cadquery` in a discoverable Python (searches conda paths automatically).

---

## Tool 2 — inspect_mesh

```python
inspect_mesh(stl_path: str) -> dict
```

**What it takes:**
- `stl_path` — from `execute_cadquery["stl_path"]`

**What it does:**
Loads STL with `MeshLib`, checks mesh quality: is it closed (watertight)? Are there holes (open edges)? Is it manifold (every edge shared by exactly 2 faces)?

**Returns (success):**
```python
{
    "success": True,
    "is_watertight": True,      # no holes in mesh
    "open_edges": 0,            # boundary edges (bad if > 0)
    "singular_edges": 0,        # zero-length edges (cone apex is OK = 1)
    "volume_mm3": 24457.6,
    "is_manifold": True,        # passes checkValidity()
    "face_count": 31,
    "vertex_count": 48,
    "passes": True              # True if open_edges==0 AND volume>0
}
```

**Returns (failure):**
```python
{"success": False, "error": "...", "traceback": "..."}
```

**Deps:** `meshlib`
> Note: Standard MeshLib implementation is active.

---

## Tool 3 — render_views

```python
render_views(stl_path: str, run_id: str) -> dict
```

**What it takes:**
- `stl_path` — from `execute_cadquery["stl_path"]`
- `run_id` — unique string for the output PNG filename.

**What it does:**
Renders 3 VTK views of the mesh into a single 4800×1600 composite PNG (offscreen, no GUI, Phong shading):

| View | Position | Purpose |
|---|---|---|
| Left — Isometric | elev=35°, azim=45° | Overall 3D shape |
| Center — High-rear | elev=65°, azim=220° | Top face, holes, cavities |
| Right — Front profile | elev=10°, azim=0° | Wall heights, vertical features |

**Returns (success):**
```python
{
    "success": True,
    "png_path": "outputs/myrun_threeview.png",
    "width": 4800,
    "height": 1600,
    "views": ["iso", "high_rear", "front"],
    "renders": {"composite": "outputs/myrun_threeview.png"}
}
```

**Returns (failure):**
```python
{"success": False, "error": "VTK render failed: ...", "traceback": "..."}
```

**Deps:** `vtk>=9.3`, `numpy>=1.26`

---

## Tool 4 — verify_geometry

```python
verify_geometry(
    prompt: str,
    code: str,
    metrics: dict,
    render_png: str,
    prior_feedback: list | None = None
) -> dict
```

**What it takes:**
- `prompt` — original user request ("design a box 70×50×30mm...")
- `code` — the CadQuery Python code that generated the STL
- `metrics` — **merged dict** from execute_cadquery + inspect_mesh (see merge below)
- `render_png` — path from `render_views["png_path"]`
- `prior_feedback` — list of previous feedback strings (oldest first). If the same failure repeats, Gemini escalates.

**What it does:**
Calls Gemini 3.1 Pro Preview with:
1. A text block: prompt + code + metrics JSON
2. The PNG image attached (vision/multimodal call)

Gemini reads both the image AND the numbers. Returns a structured verdict.

**Returns (always — never raises):**
```python
{"passed": bool, "feedback": str, "render_png": str}
```

**Mock fallback:** If `GEMINI_API_KEY` is missing → returns `{"passed": True, "feedback": "mock...", ...}` instantly, no network call.

**Deps:** `google-genai>=2.9.0`, `GEMINI_API_KEY` in env or `.env` file.

---

## Tool 5 — write_trace

```python
write_trace(
    run_id: str,
    prompt: str,
    plan: dict,
    code: str,
    execution_result: dict,
    mesh_report: dict,
    renders: dict,
    verdict: dict
) -> dict
```

**What it takes:** All outputs from every prior tool + the plan dict + original prompt.

**What it does:** Writes a complete JSON snapshot of the run to `outputs/traces/{run_id}/trace.json`.

**Returns:** `{"success": True, "trace_path": "outputs/traces/myrun/trace.json"}`

**Deps:** stdlib only.

---

## Critical: The metrics Merge

`verify_geometry` takes one `metrics` dict but needs data from **two** tools:

```python
# After execute_cadquery AND inspect_mesh, merge before calling verify:
metrics = {
    # ← from execute_cadquery
    "volume_mm3":   execution_result["volume"],
    "bounding_box": execution_result["bbox"],
    "num_faces":    execution_result["faces_count"],
    # ← from inspect_mesh
    "is_watertight":       mesh_report["is_watertight"],
    "is_valid":            mesh_report["passes"],
    "num_edges":           mesh_report["open_edges"],
    "normals_consistent":  mesh_report["is_manifold"],
    "mesh_defect_count":   mesh_report["open_edges"],
}
```

See `tests/fixtures/case_01_enclosure/metrics.json` for the exact shape the Gemini prompt expects.

---

## Full Data Flow Diagram

```
prompt (str)  +  code (str)  +  run_id (str)
                    │
                    ▼
         execute_cadquery(code, run_id)
                    │
        ┌───────────┴────────────┐
        ▼                        ▼
  inspect_mesh(stl_path)   render_views(stl_path, run_id)
        │                        │
        │ mesh_report             │ png_path
        └─────────┬──────────────┘
                  ▼
         MERGE → metrics dict
                  │
                  ▼
  verify_geometry(prompt, code, metrics, png_path, prior_feedback?)
                  │
                  ▼
         {passed, feedback}
                  │
                  ▼
  write_trace(run_id, prompt, plan, code,
              execution_result, mesh_report, renders, verdict)
                  │
                  ▼
     outputs/traces/{run_id}/trace.json
```

---

## PRD §06 → Tools Mapping

| PRD Primitive | Tool Built | Status |
|---|---|---|
| `solid_generate` | `execute_cadquery` | ✅ Done |
| `measure_geometry` | `execute_cadquery` | ✅ Done (partial — OCCT metrics) |
| `mesh_inspect` | `inspect_mesh` | ✅ Done (MeshLib) |
| `render_views` | `render_views` | ✅ Done (VTK 3-view) |
| `visual_verify` | `verify_geometry` | ✅ Done (Gemini multimodal) |
| `trace_capture` | `write_trace` | ✅ Done |
| `primitive_plan` | `runtime/schema.py` | ❌ NOT BUILT |
| `mesh_repair` | — | ❌ NOT BUILT |
| `forgecad_emit` | — | ❌ NOT BUILT (post-MVP) |
| `approval_gate` | — | ❌ NOT BUILT (Temporal, post-MVP) |

**6/10 PRD primitives done. The 4 verification tools form a complete working chain.**

---

## What's Needed to Run End-to-End RIGHT NOW (no RLM)

Tools work today with hardcoded CadQuery code:

```python
run_id = "test_001"
code = "import cadquery as cq\nresult = cq.Workplane('XY').box(70,50,30)"
prompt = "design a 70x50x30mm box"

r1 = execute_cadquery(code, run_id)
r2 = inspect_mesh(r1["stl_path"])
r3 = render_views(r1["stl_path"], run_id)
metrics = merge(r1, r2)   # see merge section above
r4 = verify_geometry(prompt, code, metrics, r3["png_path"])
write_trace(run_id, prompt, {}, code, r1, r2, r3, r4)
```

---

## What's Needed for Full RLM-Driven Pipeline

The `runtime/` layer (none of these exist yet):

| File | Purpose |
|---|---|
| `runtime/schema.py` | `PrimitivePlan` Pydantic model + `validate()` — defines structured output the RLM produces |
| `runtime/compile.py` | `plan → code` — template-based from `primitives/library.json` |
| `runtime/planner.py` | RLM call: prompt → `PrimitivePlan` |
| `runtime/trace.py` | Normalise trace + tag the 6 PRD failure categories |

No changes needed to any existing tool to connect them.

---

## Repair Loop Pattern

`verify_geometry` is already wired for multi-iteration repair via `prior_feedback`:

```python
prior_feedback = []
for attempt in range(MAX_ATTEMPTS):
    r4 = verify_geometry(prompt, code, metrics, png_path, prior_feedback)
    if r4["passed"]:
        break
    prior_feedback.append(r4["feedback"])  # Gemini escalates on repeat failures
    code = replanner(prompt, prior_feedback)  # regenerate code (needs runtime/planner)
    # re-run: execute → inspect → render → verify
```

---

## pyproject.toml Dependencies (current state)

```toml
"cadquery>=2.7.0",        # execute_cadquery (subprocess)
"meshlib>=3.1.2.192",      # inspect_mesh
"numpy>=1.26",            # render_views
"vtk>=9.3",               # render_views
"google-genai>=2.9.0",    # verify_geometry (Gemini SDK)
"fast-rlm>=0.1.18",       # RLM planner (runtime/planner.py — not built yet)
"fastapi>=0.137.2",       # backend/ services
"uvicorn[standard]>=0.49.0",
"pydantic>=2.0",
"requests>=2.34.2",
"python-dotenv>=1.2.2",
```

---

## Uncommitted Git Changes

```
M  pyproject.toml        ← added vtk, numpy deps
M  tools/render_views.py ← replaced with VTK 3-view renderer
M  tools/verify_geometry.py ← replaced with Gemini SDK judge
M  uv.lock
?? tests/fixtures/       ← case_01_enclosure fixture (preserved from deleted vlm_kit/)
```

Branch: `lite-backend-integration`. Not yet committed.
