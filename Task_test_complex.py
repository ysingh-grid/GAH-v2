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


def run_pipeline_for_task(task_prompt: str, run_id: str, run_prefix: str) -> None:
    print(f"\n============================================================")
    print(f"🎬 Running pipeline for task: {run_prefix}")
    print(f"============================================================")

    # 1. Plan using modular planner (enforces restricted toolset and self-repair loop)
    plan_data = plan_geometry(
        design_intent=task_prompt,
        config=config,
        max_attempts=3,
        backend_url="http://127.0.0.1:8001",
        run_prefix=run_prefix,
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
    cad_result = execute_cadquery(compiled_code, run_id)
    print("Execution Result:", cad_result)
    
    if not cad_result["success"]:
        print(f"\n❌ CAD execution failed: {cad_result['error']}")
        return

    actual_vol = cad_result["volume"]
    print(f"\nMeasured Volume: {actual_vol:.2f} mm3")
    
    # 4. Inspect mesh via MeshLib
    print("\n=== INSPECTING MESH (MeshLib) ===")
    mesh_result = inspect_mesh(cad_result["stl_path"])
    print("Mesh Report:", mesh_result)
    assert mesh_result["is_watertight"] is True
    
    # 5. Render Views (VTK 3-view)
    print("\n=== RENDERING 3-VIEW COMPOSITE PNG ===")
    render_result = render_views(cad_result["stl_path"], run_id)
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
    verdict = verify_geometry(task_prompt, metrics, render_result["png_path"])
    print("Gemini Verdict passed:", verdict["passed"])
    print("Gemini Feedback:", verdict["feedback"])
    
    # 7. Write Trace JSON
    print("\n=== WRITING RUN TRACE ===")
    trace_result = write_trace(
        run_id=run_id,
        prompt=task_prompt,
        plan=plan_data.model_dump(),
        code=compiled_code,
        execution_result=cad_result,
        mesh_report=mesh_result,
        renders=render_result,
        verdict=verdict,
    )
    print("Trace Path:", trace_result.get("trace_path"))
    print(f"\n✅ CAD file saved to: {cad_result['step_path']}")


if __name__ == "__main__":
    task1 = """
Design a Hexagonal Adapter Plate.
The plate consists of:
- A base hexagon_prism with flat_to_flat distance 40.0 mm and height 8.0 mm (centered at [0, 0, 4]).
- A hollow_cylinder standing vertically on the top face of the base, centered at [0, 0, 15.5] with outer_radius 12.0 mm, inner_radius 8.0 mm, and height 15.0 mm (unioned to the base).
- Four cylinder cuts of radius 2.0 mm and height 10.0 mm for mounting screws, placed at [12.0, 12.0, 4.0], [-12.0, 12.0, 4.0], [12.0, -12.0, 4.0], and [-12.0, -12.0, 4.0] (cut from the assembly).
"""

    task2 = """
Design a Flanged Mounting Bracket.
The bracket consists of:
- A base block (box) of length 50.0 mm, width 50.0 mm, and height 6.0 mm (centered at [0, 0, 3]).
- A hollow_cylinder standing vertically on the top face of the base, centered at [0, 0, 16.0] with outer_radius 15.0 mm, inner_radius 10.0 mm, and height 20.0 mm (unioned to the base).
- Two cylinder cuts of radius 3.0 mm and height 8.0 mm for mounting bolts, placed at [18.0, 0.0, 3.0] and [-18.0, 0.0, 3.0] (cut from the base).
"""

    print("🚀 Running GAH-v2 geometry reasoning pipeline with two test prompts...")
    try:
        # Run test 1
        run_pipeline_for_task(task1, "hexagonal_adapter_output", "hexagonal_adapter")
        
        # Run test 2
        run_pipeline_for_task(task2, "flanged_bracket_output", "flanged_bracket")
        
        print("\n🎉 Both test pipelines completed successfully!")
    except Exception as e:
        print(f"\n❌ Error during execution phase: {e}")
        import traceback
        traceback.print_exc()