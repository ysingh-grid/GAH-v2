def execute_cadquery(code: str, run_id: str) -> dict:
    """
    Executes CadQuery code in a separate sandboxed Python process.
    Saves the output to STEP and STL files and retrieves geometry metrics.
    
    Args:
        code: Python script containing CadQuery commands. It must define a 
              top-level Workplane or Shape object named 'result'.
        run_id: A unique identifier for the run.
        
    Returns:
        A dictionary containing:
        - success: bool
        - error: str (optional, if success=False)
        - volume: float (optional)
        - bbox: dict with xmin, ymin, zmin, xmax, ymax, zmax (optional)
        - faces_count: int (optional)
        - step_path: str (optional)
        - stl_path: str (optional)
    """
    import os
    import sys
    import json
    import subprocess
    import tempfile
    
    # Path setup — run-scoped folder owns all artifacts for this run
    from .artifacts import run_dir
    outputs_dir = str(run_dir(run_id))

    step_path = os.path.join(outputs_dir, "solid.step")
    stl_path = os.path.join(outputs_dir, "solid.stl")
    
    # Python script wrapper to execute user code and extract measurements
    wrapper_script = f"""
import sys
import json
import traceback
import os

# Define paths
step_path = {repr(step_path)}
stl_path = {repr(stl_path)}

user_code = {repr(code)}

namespace = {{}}

try:
    # Execute user code in dynamic namespace
    exec(user_code, namespace)
except Exception as e:
    tb = traceback.format_exc()
    print(json.dumps({{"success": False, "error": tb}}))
    sys.exit(0)

# Extract result geometry
import cadquery as cq
result = namespace.get('result', None)

if result is None:
    # Fallback search for any cq.Workplane or Shape
    for val in list(namespace.values()):
        if isinstance(val, (cq.Workplane, cq.Shape)):
            result = val
            break

if result is None:
    print(json.dumps({{"success": False, "error": "No CadQuery Workplane or Shape (variable 'result') was defined in the code."}}))
    sys.exit(0)

try:
    # Ensure export directories exist
    os.makedirs(os.path.dirname(step_path), exist_ok=True)
    
    # Export to STEP and STL
    cq.exporters.export(result, step_path)
    cq.exporters.export(result, stl_path)
    
    # Calculate geometric properties
    shape = result.val() if hasattr(result, 'val') else result
    volume = shape.Volume()
    bbox = shape.BoundingBox()
    faces_count = len(shape.Faces())
    
    metrics = {{
        "success": True,
        "volume": volume,
        "bbox": {{
            "xmin": bbox.xmin, "ymin": bbox.ymin, "zmin": bbox.zmin,
            "xmax": bbox.xmax, "ymax": bbox.ymax, "zmax": bbox.zmax
        }},
        "faces_count": faces_count,
        "step_path": step_path,
        "stl_path": stl_path
    }}
    print(json.dumps(metrics))
except Exception as e:
    tb = traceback.format_exc()
    print(json.dumps({{"success": False, "error": f"Error during export/measurement: " + tb}}))
    sys.exit(0)
"""
    
    # Run the script in a subprocess using a python interpreter that has cadquery installed
    import shutil
    
    def find_cadquery_python():
        # Check if the current interpreter already has cadquery
        try:
            check = subprocess.run(
                [sys.executable, "-c", "import cadquery"],
                capture_output=True, timeout=5
            )
            if check.returncode == 0:
                return sys.executable
        except Exception:
            pass
            
        # Check common locations where conda might install cadquery
        candidates = [
            "/opt/anaconda3/bin/python3",
            "/opt/anaconda3/bin/python",
            os.path.expanduser("~/anaconda3/bin/python3"),
            os.path.expanduser("~/miniconda3/bin/python3"),
            "/opt/homebrew/anaconda3/bin/python3",
            "/opt/homebrew/bin/python3",
            shutil.which("python3"),
            shutil.which("python"),
        ]
        for candidate in candidates:
            if candidate and os.path.isfile(candidate) and candidate != sys.executable:
                try:
                    check = subprocess.run(
                        [candidate, "-c", "import cadquery"],
                        capture_output=True, timeout=5
                    )
                    if check.returncode == 0:
                        return candidate
                except Exception:
                    continue
        return sys.executable  # fallback
        
    python_exe = find_cadquery_python()

    try:
        # Use tempfile to write the wrapper script securely
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode="w", encoding="utf-8") as temp_f:
            temp_f.write(wrapper_script)
            temp_script_path = temp_f.name
            
        process_result = subprocess.run(
            [python_exe, temp_script_path],
            capture_output=True,
            text=True,
            timeout=30 # Prevent infinite loops
        )
        
        # Clean up temp script
        if os.path.exists(temp_script_path):
            os.remove(temp_script_path)
            
        if process_result.returncode != 0:
            return {
                "success": False,
                "error": f"Python interpreter crashed with return code {process_result.returncode}. Stderr: {process_result.stderr}"
            }
            
        # Parse output
        output_str = process_result.stdout.strip()
        if not output_str:
            return {
                "success": False,
                "error": f"No output returned from subprocess. Stderr: {process_result.stderr}"
            }
            
        try:
            metrics = json.loads(output_str)
            return metrics
        except json.JSONDecodeError:
            return {
                "success": False,
                "error": f"Failed to parse subprocess output as JSON. Raw output:\n{output_str}\nStderr:\n{process_result.stderr}"
            }
            
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to execute subprocess: {str(e)}"
        }
