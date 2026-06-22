"""Manual + visual test of the heavy geometry chain (Layer B — Temporal-side path).

Runs the full deterministic pipeline WITHOUT RLM/backend:
  execute_cadquery -> inspect_mesh -> render_views -> verify_geometry -> write_trace

ONLY inputs read: prompt.txt + code.py. The STL, metrics, render, verdict and
trace are all GENERATED fresh into outputs/ — the premade input.stl/metrics.json/
prior_feedback.json in the fixture dir are deliberately NOT touched.

Each stage prints a labelled block. Chain stops at first hard failure so you see
exactly which hop broke. Render PNG auto-opens (macOS `open`).

Prereqs:
  - CadQuery reachable (execute_cadquery finds its conda python)
  - GEMINI_API_KEY in .env  (else verify_geometry returns mock pass)

Run:
  uv run python tools_chain_test.py
"""

import pathlib
import subprocess
import sys

from tools import (
    execute_cadquery,
    inspect_mesh,
    render_views,
    verify_geometry,
    write_trace,
)
from tools.artifacts import new_run_id

RUN_ID = new_run_id("manual")  # e.g. manual_20260619-153012_a1b2 — fresh folder each run
FIX = pathlib.Path("tests/fixtures/case_01_enclosure")


def banner(n, name):
    print(f"\n{'=' * 60}\n[{n}] {name}\n{'=' * 60}")


def die(stage, result):
    print(f"\n❌ {stage} FAILED:")
    print("   error:", result.get("error"))
    if result.get("traceback"):
        print(result["traceback"])
    sys.exit(1)


# --- load the ONLY two inputs: prompt + code.py --------------------------
prompt = (FIX / "prompt.txt").read_text().strip()
code = (FIX / "code.py").read_text()
print(f"Inputs (prompt.txt + code.py only): {FIX}\nPrompt: {prompt[:90]}...")

# --- 1. execute_cadquery: code -> STL + STEP + OCCT metrics --------------
banner(1, "execute_cadquery (CadQuery solid)")
ex = execute_cadquery(code, RUN_ID)
if not ex.get("success"):
    die("execute_cadquery", ex)
print("  volume mm3 :", ex["volume"])
print("  bbox       :", ex["bbox"])
print("  faces      :", ex["faces_count"])
print("  stl        :", ex["stl_path"])
stl_path = ex["stl_path"]

# --- 2. inspect_mesh: MeshLib quality gate ------------------------------
banner(2, "inspect_mesh (mesh validity)")
mesh = inspect_mesh(stl_path)
if not mesh.get("success"):
    die("inspect_mesh", mesh)
print("  watertight :", mesh["is_watertight"])
print("  open_edges :", mesh["open_edges"], "(must be 0)")
print("  manifold   :", mesh["is_manifold"])
print("  passes     :", mesh["passes"])

# --- 3. render_views: 3-view composite PNG ------------------------------
banner(3, "render_views (VTK 3-view)")
rend = render_views(stl_path, RUN_ID)
if not rend.get("success"):
    die("render_views", rend)
png = rend["png_path"]
print("  png        :", png, f"({rend['width']}x{rend['height']})")
# visual: open the composite so you can eyeball the geometry
if sys.platform == "darwin":
    subprocess.run(["open", png])
    print("  -> opened in Preview")

# --- merge metrics for the verifier (two tools -> one dict) -------------
metrics = {
    "volume_mm3": ex["volume"],
    "bounding_box": ex["bbox"],
    "num_faces": ex["faces_count"],
    "is_watertight": mesh["is_watertight"],
    "is_valid": mesh["passes"],
    "num_edges": mesh["open_edges"],
    "normals_consistent": mesh["is_manifold"],
    "mesh_defect_count": mesh["open_edges"],
}

# --- 4. verify_geometry: Gemini multimodal judge ------------------------
banner(4, "verify_geometry (Gemini render+metrics judge)")
verdict = verify_geometry(prompt, code, metrics, png)
print("  passed     :", verdict["passed"])
print("  feedback   :", verdict["feedback"])

# --- 5. write_trace: persist everything ---------------------------------
banner(5, "write_trace (JSON artifact)")
tr = write_trace(
    run_id=RUN_ID,
    prompt=prompt,
    plan={
        "note": "no PrimitivePlan yet; code.py is the direct input (runtime/schema.py not built)"
    },
    code=code,
    execution_result=ex,
    mesh_report=mesh,
    renders=rend,
    verdict=verdict,
)
if not tr.get("success"):
    die("write_trace", tr)
print("  trace      :", tr["trace_path"])

print(f"\n✅ Chain complete. Verdict passed={verdict['passed']}")
print(f"   Inspect: {png}  and  {tr['trace_path']}")
