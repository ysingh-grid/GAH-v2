def _read_progress_marker(progress_path: str) -> str | None:
    """Return "step 'X' (op: Y)" from the progress sidecar, or None if absent.

    The sidecar is written (flushed+fsynced) by the compiled script's `_mark`
    helper before each step, so it survives even a hard interpreter crash
    (SIGSEGV / -11) and names the last step that was attempted.
    """
    try:
        with open(progress_path, encoding="utf-8") as f:
            raw = f.read().strip()
    except Exception:
        return None
    if not raw:
        return None
    step_id, _sep, label = raw.partition(" :: ")
    label = label.strip()
    return f"step {step_id!r}" + (f" (op: {label})" if label else "")


def _attribute_failure(error: str, progress_path: str) -> str:
    """Prepend the exact failing step to an error string when we can identify it.

    Turns a bare traceback / "return code -11" into an actionable, attributed
    message so the replanner knows WHICH step to change, not just that it failed.
    """
    where = _read_progress_marker(progress_path)
    return f"failed at {where}: {error}" if where else error


def multi_solid_failure_detail(num_solids: int, *, op_hint: str = "") -> str:
    """Actionable error when OCCT reports != 1 solid (geometric, not product-named).

    Cause class is inferred from the failing op label when available so replan
    rewrites the right operator (cut sever vs union gap) — never a vessel sermon.
    """
    hint = (op_hint or "").lower()
    if "cut" in hint or "cavity" in hint:
        cause = (
            "CAUSE: cut_sever — a subtractive step disconnected the solid into "
            f"{num_solids} pieces. Through-cuts must leave walls continuous: shrink "
            "the cavity tool so it does not free a rim from the body, keep cavity "
            "volumes as one continuous void (compiler already fuses all cut steps "
            "into one tool), or use a single hollow primitive. Do NOT only nudge a "
            "position by 1mm."
        )
    elif "union" in hint or "base" in hint:
        cause = (
            "CAUSE: union_gap — additive solids did not fuse into one body "
            f"({num_solids} solids). Extend each union feature into its parent so "
            "volumes overlap (typically 0.5–1mm). Patterned features must sink into "
            "the hub/body they attach to."
        )
    else:
        cause = (
            f"CAUSE: multi-solid result ({num_solids} solids, need 1). If the last "
            "op was a cut, shrink/reconnect the cavity so walls stay continuous. "
            "If it was a union, increase overlap into the parent body."
        )
    return f"result has {num_solids} solids (need exactly 1). {cause}"


def multi_shell_failure_detail(num_shells: int) -> str:
    """Actionable error when 1 solid has >1 shells (enclosed void / multi-shell).

    STL tessellation of multi-shell BREP yields mesh components>1 even though
    CadQuery reports a single solid — the classic water-bottle failure mode.
    """
    return (
        f"result has 1 solid but {num_shells} shells (need exactly 1 shell). "
        "CAUSE: multi-shell topology — an enclosed internal void (balloon) or "
        "sealed cavity. Open the cavity to the outside: cup-style cut that leaves "
        "a floor and open top, or `shell` an open face LAST. Never leave a fully "
        "enclosed void. Removable caps are out of scope — model the vessel body "
        "alone (prefer ONE `revolve` / `hollow_cylinder`)."
    )


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
        - num_solids: int (optional) — OCCT TopAbs_SOLID count
        - num_shells: int (optional) — OCCT TopAbs_SHELL count
        - step_path: str (optional)
        - stl_path: str (optional)

    Topology gate: success is False when num_solids != 1 OR num_shells != 1.
    That is the host-side single-part invariant — multi-body and multi-shell
    (enclosed void) fail here with the correct CAUSE text.
    """
    import os
    import sys
    import json
    import subprocess
    import tempfile

    # Path setup — run-scoped folder owns all artifacts for this run
    from .artifacts import run_dir
    outputs_dir = str(run_dir(run_id))

    # Sidecar file the compiled script's _mark helper overwrites before each step;
    # read back on failure to attribute the crash to the exact step. Start fresh.
    os.makedirs(outputs_dir, exist_ok=True)
    progress_path = os.path.join(outputs_dir, "_progress.txt")
    if os.path.exists(progress_path):
        os.remove(progress_path)

    step_path = os.path.join(outputs_dir, "solid.step")
    stl_path = os.path.join(outputs_dir, "solid.stl")

    # Bake pure-string messages into the wrapper (subprocess cannot import host modules).
    # {n} = solid/shell count; {op} = last progress marker (step :: label) for cause class.
    multi_solid_msg_template = (
        "result has {n} solids (need exactly 1). "
        "Last op: {op}. "
        "If that op is a cut/cavity: CAUSE cut_sever — through-cut disconnected the "
        "solid; shrink the cavity so walls stay continuous (cavity tools are already "
        "fused into one cut by the compiler). If that op is a union: CAUSE union_gap — "
        "increase overlap into the parent body (0.5–1mm). Do NOT only nudge by 1mm; "
        "change the construction or cavity size."
    )
    multi_shell_msg_template = multi_shell_failure_detail(999).replace(
        "999 shells", "{n} shells", 1
    )

    # Python script wrapper to execute user code and extract measurements
    wrapper_script = f"""
import sys
import json
import traceback
import os

# Define paths
step_path = {repr(step_path)}
stl_path = {repr(stl_path)}
_MULTI_SOLID_MSG = {repr(multi_solid_msg_template)}
_MULTI_SHELL_MSG = {repr(multi_shell_msg_template)}

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

def _count_topology(shape):
    \"\"\"OCCT solid + shell counts — the truth before MeshLib tessellation.\"\"\"
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_SOLID, TopAbs_SHELL
    wrapped = shape.wrapped if hasattr(shape, "wrapped") else shape
    n_sol = 0
    exp = TopExp_Explorer(wrapped, TopAbs_SOLID)
    while exp.More():
        n_sol += 1
        exp.Next()
    n_sh = 0
    exp = TopExp_Explorer(wrapped, TopAbs_SHELL)
    while exp.More():
        n_sh += 1
        exp.Next()
    return n_sol, n_sh

try:
    # Ensure export directories exist
    os.makedirs(os.path.dirname(step_path), exist_ok=True)

    # Export to STEP and STL (even on multi-solid fail — useful for debugging)
    cq.exporters.export(result, step_path)
    cq.exporters.export(result, stl_path)

    # Calculate geometric properties
    shape = result.val() if hasattr(result, 'val') else result
    volume = shape.Volume()
    bbox = shape.BoundingBox()
    faces_count = len(shape.Faces())
    num_solids, num_shells = _count_topology(shape)

    metrics = {{
        "success": True,
        "volume": volume,
        "bbox": {{
            "xmin": bbox.xmin, "ymin": bbox.ymin, "zmin": bbox.zmin,
            "xmax": bbox.xmax, "ymax": bbox.ymax, "zmax": bbox.zmax
        }},
        "faces_count": faces_count,
        "num_solids": num_solids,
        "num_shells": num_shells,
        "step_path": step_path,
        "stl_path": stl_path
    }}
    # HARD GATE: single-part platform requires 1 solid AND 1 shell.
    # Multi-solid (severing cuts) and multi-shell (enclosed void) both used to
    # slip through as success and only fail later as mesh components=2 with a
    # wrong "touching unions" replan hint.
    if num_solids != 1:
        metrics["success"] = False
        _op = ""
        try:
            _pf = os.environ.get("DTCM_PROGRESS_FILE") or ""
            if _pf:
                with open(_pf, encoding="utf-8") as _fh:
                    _op = _fh.read().strip()
        except Exception:
            _op = ""
        metrics["error"] = _MULTI_SOLID_MSG.format(n=num_solids, op=_op or "unknown")
    elif num_shells != 1:
        metrics["success"] = False
        metrics["error"] = _MULTI_SHELL_MSG.format(n=num_shells)
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
            
        run_env = os.environ.copy()
        run_env["DTCM_PROGRESS_FILE"] = progress_path
        process_result = subprocess.run(
            [python_exe, temp_script_path],
            capture_output=True,
            text=True,
            timeout=30, # Prevent infinite loops
            env=run_env,
        )
        
        # Clean up temp script
        if os.path.exists(temp_script_path):
            os.remove(temp_script_path)
            
        if process_result.returncode != 0:
            return {
                "success": False,
                "error": _attribute_failure(
                    f"Python interpreter crashed with return code "
                    f"{process_result.returncode}. Stderr: {process_result.stderr}",
                    progress_path,
                ),
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
            if (
                isinstance(metrics, dict)
                and metrics.get("success") is False
                and metrics.get("error")
            ):
                metrics["error"] = _attribute_failure(metrics["error"], progress_path)
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
