"""
Smoke test: Uses the modular runtime planner (Phase 2) with a less detailed prompt
to design a 2x4 Lego Brick, compiles the plan (Phase 1), executes the CadQuery script,
and verifies geometry properties (volume and watertightness).

Prereqs:
  - backend up:  uv run python -m backend.server
  - GEMINI_API_KEY set in .env
"""

from rlm.rlm_config import config
from runtime.planner import plan_geometry
from runtime.compile import compile_plan_to_cadquery
from tools.execute_cadquery import execute_cadquery
from tools.inspect_mesh import inspect_mesh
from tools.render_views import render_views
from tools.verify_geometry import verify_geometry
from tools.write_trace import write_trace

# 1. Configure token-saving & rate-limiting limits for the agent
config.max_depth = 1
config.max_calls_per_subagent = 8  # Limit calls to prevent rate-limiting

# 2. High-level prompt with only design specifications
task = """
Design a standard 2x4 Lego Brick.
The brick has:
- A base block of size 32.0 x 16.0 x 9.6 mm.
- A hollow bottom cavity of size 28.8 x 12.8 x 8.0 mm cut from the bottom.
- 8 top studs of radius 2.4 mm and height 1.8 mm, arranged in a 2x4 grid centered on the top face.
"""

print("🚀 Running GAH-v2 geometry reasoning pipeline with high-level prompt...")

try:
    # 1. Plan using modular planner (enforces restricted toolset and self-repair loop)
    plan_data = plan_geometry(
        design_intent=task,
        config=config,
        max_attempts=3,
        backend_url="http://127.0.0.1:8001",
        run_prefix="lego_brick_high_level",
    )
    
    print("\n=== PLANNER GENERATED VALID PLAN ===")
    import pprint
    pprint.pprint(plan_data.model_dump())
    
    # 2. Compile plan to CadQuery using runtime compiler
    print("\n=== COMPILING PLAN TO CADQUERY ===")
    compiled_code = compile_plan_to_cadquery(plan_data)
    print(compiled_code)
    
    # 3. Execute compiled CadQuery code via sandboxed subprocess
    print("\n=== EXECUTING CADQUERY & EXTRACTING METRICS ===")
    cad_result = execute_cadquery(compiled_code, "lego_brick_output")
    print("Execution Result:", cad_result)
    
    if cad_result["success"]:
        actual_vol = cad_result["volume"]
        print(f"\nMeasured Volume: {actual_vol:.2f} mm3 (Theoretical: 2226.66 mm3)")
        
        # 4. Inspect mesh via MeshLib
        print("\n=== INSPECTING MESH (MeshLib) ===")
        mesh_result = inspect_mesh(cad_result["stl_path"])
        print("Mesh Report:", mesh_result)
        assert mesh_result["is_watertight"] is True
        
        # 5. Render Views (VTK 3-view)
        print("\n=== RENDERING 3-VIEW COMPOSITE PNG ===")
        render_result = render_views(cad_result["stl_path"], "lego_brick_output")
        print("Render Result:", render_result)
        
        # 6. Verify Geometry (Gemini Multimodal Judge)
        print("\n=== RUNNING GEMINI MULTIMODAL JUDGE ===")
        metrics = {
            "volume_mm3": cad_result["volume"],
            "bounding_box": cad_result["bbox"],
            "num_faces": cad_result["faces_count"],
            "is_watertight": mesh_result["is_watertight"],
            "is_valid": mesh_result["passes"],
            "num_edges": mesh_result["open_edges"],
            "normals_consistent": mesh_result["is_manifold"],
            "mesh_defect_count": mesh_result["open_edges"],
        }
        verdict = verify_geometry(task, compiled_code, metrics, render_result["png_path"])
        print("Gemini Verdict passed:", verdict["passed"])
        print("Gemini Feedback:", verdict["feedback"])
        
        # 7. Write Trace JSON
        print("\n=== WRITING RUN TRACE ===")
        trace_result = write_trace(
            run_id="lego_brick_output",
            prompt=task,
            plan=plan_data.model_dump(),
            code=compiled_code,
            execution_result=cad_result,
            mesh_report=mesh_result,
            renders=render_result,
            verdict=verdict,
        )
        print("Trace Path:", trace_result.get("trace_path"))
        
        print(f"\n✅ CAD file saved to: {cad_result['step_path']}")
        print("✅ End-to-end geometry reasoning pipeline completed successfully!")
    else:
        print(f"\n❌ CAD execution failed: {cad_result['error']}")

except Exception as e:
    print(f"\n❌ Error during execution phase: {e}")
    import traceback
    traceback.print_exc()