def write_trace(
    run_id: str, 
    prompt: str, 
    plan: dict, 
    code: str, 
    execution_result: dict, 
    mesh_report: dict, 
    renders: dict, 
    verdict: dict
) -> dict:
    """
    Writes a complete run execution trace as a JSON file under outputs/traces/{run_id}/trace.json.
    
    Args:
        run_id: Unique run identifier.
        prompt: User's original query.
        plan: Primitive plan dictionary.
        code: Compiled CadQuery code string.
        execution_result: Metric dictionary returned by execute_cadquery.
        mesh_report: Metric dictionary returned by inspect_mesh.
        renders: Render paths dictionary returned by render_views.
        verdict: Verification verdict dictionary returned by verify_geometry.
        
    Returns:
        A dictionary indicating success and the path to the trace file.
    """
    import os
    import json
    from datetime import datetime, timezone
    
    # Path setup
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    trace_dir = os.path.join(base_dir, "outputs", "traces", run_id)
    os.makedirs(trace_dir, exist_ok=True)
    
    trace_path = os.path.join(trace_dir, "trace.json")
    
    trace_data = {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "prompt": prompt,
        "plan": plan,
        "code": code,
        "execution_result": execution_result,
        "mesh_report": mesh_report,
        "renders": renders,
        "verdict": verdict
    }
    
    try:
        with open(trace_path, "w", encoding="utf-8") as f:
            json.dump(trace_data, f, indent=2)
            
        return {
            "success": True,
            "trace_path": trace_path
        }
    except Exception as e:
        import traceback
        return {
            "success": False,
            "error": f"Failed to write trace file: {str(e)}",
            "traceback": traceback.format_exc()
        }
