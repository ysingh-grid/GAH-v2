# 300s — Temporal's own execute_activity timeout is 6 minutes, dedicated solely
# to this step. Raised from a previous 30s, which was an arbitrary ceiling
# nobody profiled against real geometry. Complex-but-VALID OCCT operations
# (fillet on a smooth loft's spline rim, multi-step boolean chains) measured
# taking well over 30s; the old ceiling produced FALSE "timed out" failures on
# geometry that would have succeeded given more time, burning replan budget on
# nothing fixable by re-planning. Module-level (not buried in the function) so
# tests can monkeypatch it to exercise the timeout path without a real 5min wait.
_SUBPROCESS_TIMEOUT_S = 300


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
    
    # Export to STEP (exact B-rep, tolerance is irrelevant) and STL (tessellated
    # — CadQuery's default tolerance=0.1/angularTolerance=0.1 is coarse enough to
    # visibly facet curved BSpline surfaces in render/VLM views even when the
    # underlying geometry is genuinely smooth. Tighter values here only add
    # triangles along real curvature; they cannot manufacture curvature that
    # isn't there, so this is safe on flat/prismatic parts too (near-identity
    # triangle count). tolerance=0.05/angularTolerance=0.07 measured ~2x
    # triangle count on a test sphere (8,002 -> 16,628) — picked over the
    # tighter 0.01/0.05 pair (4x, 32,204) to keep STL file size/render time
    # from scaling as steeply.
    cq.exporters.export(result, step_path)
    cq.exporters.export(result, stl_path, tolerance=0.05, angularTolerance=0.07)
    
    # Calculate geometric properties
    shape = result.val() if hasattr(result, 'val') else result
    volume = shape.Volume()
    bbox = shape.BoundingBox()
    faces_count = len(shape.Faces())
    # Ground truth for how many connected components the exported MESH should
    # have. One closed B-rep shell tessellates to exactly one mesh component:
    # a plain solid = 1, a compound of N disjoint bodies = N, a closed hollow
    # part = 2 (outer + cavity) — all verified against MeshLib's component
    # count. Downstream mesh inspection compares against THIS instead of a
    # hardcoded 1, which wrongly failed every legal multi-body plan.
    shells_count = len(shape.Shells())

    # STRUCTURAL ground-truth signals (viewpoint-independent) so the verifier
    # reasons from geometry, not eyeballed pixels:
    #   solid_fraction  = volume / bbox-volume — how solid vs hollow the part is.
    #   section_profile = filled-area fraction at 5 cross-sections along each of
    #                     X/Y/Z. Reveals hollowness, internal gaps, discrete
    #                     missing chunks and taper — none of which a single
    #                     projected render shows unambiguously. Computed by
    #                     rotating each target axis onto Z (the only orientation
    #                     Workplane.section honours) then planar-sectioning.
    bbox_vol = (bbox.xmax - bbox.xmin) * (bbox.ymax - bbox.ymin) * (bbox.zmax - bbox.zmin)
    solid_fraction = round(volume / bbox_vol, 3) if bbox_vol > 0 else None
    section_profile = None
    try:
        from OCP.BRepGProp import BRepGProp
        from OCP.GProp import GProp_GProps

        def _face_area(f):
            g = GProp_GProps()
            BRepGProp.SurfaceProperties_s(f.wrapped, g)
            return g.Mass()

        _ROT = {{"Z": None, "X": ((0, 1, 0), -90.0), "Y": ((1, 0, 0), 90.0)}}
        _prof = {{}}
        for _ax in ("X", "Y", "Z"):
            _s = shape
            if _ROT[_ax] is not None:
                _d, _a = _ROT[_ax]
                _s = _s.rotate(cq.Vector(0, 0, 0), cq.Vector(*_d), _a)
            _bb = _s.BoundingBox()
            _cross = _bb.xlen * _bb.ylen
            _vals = []
            for _i in range(5):
                _t = _bb.zmin + (_bb.zmax - _bb.zmin) * (_i + 0.5) / 5
                try:
                    _sec = cq.Workplane(obj=_s).section(_t)
                    _area = sum(_face_area(_f) for _f in _sec.faces().vals())
                    _vals.append(round(_area / _cross, 2) if _cross > 0 else None)
                except Exception:
                    _vals.append(None)
            _prof[_ax] = _vals
        section_profile = _prof
    except Exception:
        section_profile = None  # enrichment only — never fail the run over it

    metrics = {{
        "success": True,
        "volume": volume,
        "bbox": {{
            "xmin": bbox.xmin, "ymin": bbox.ymin, "zmin": bbox.zmin,
            "xmax": bbox.xmax, "ymax": bbox.ymax, "zmax": bbox.zmax
        }},
        "faces_count": faces_count,
        "shells_count": shells_count,
        "solid_fraction": solid_fraction,
        "section_profile": section_profile,
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

        try:
            process_result = subprocess.run(
                [python_exe, temp_script_path],
                capture_output=True,
                text=True,
                timeout=_SUBPROCESS_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired as e:
            # e.stdout/e.stderr ARE populated with whatever the subprocess had
            # flushed before being killed (verified empirically) — the compiler
            # emits a flushed "[STAGE n/m] step_id (op)" print before every
            # step's real geometry call specifically so this is diagnosable:
            # instead of a bare "timed out", the replanner sees exactly which
            # step never returned, e.g. stuck inside a fillet on a spline rim.
            # NOTE: TimeoutExpired.stdout is BYTES even though this call passes
            # text=True — that flag only decodes the NORMAL-completion path;
            # the timeout-exception path does not apply it (measured; a naive
            # `.strip()`/`.startswith()` on it raises TypeError). Decode first.
            raw_stdout = e.stdout or b""
            partial = (
                raw_stdout.decode("utf-8", errors="replace")
                if isinstance(raw_stdout, bytes)
                else raw_stdout
            ).strip()
            last_stage = ""
            for line in reversed(partial.splitlines()):
                if line.strip().startswith("[STAGE"):
                    last_stage = line.strip()
                    break
            hint = (
                f" Last step to start (never finished): {last_stage}."
                if last_stage
                else " No step reached even its first print — hang was in import/setup, not a plan step."
            )
            return {
                "success": False,
                "error": (
                    f"CadQuery subprocess did not finish within {_SUBPROCESS_TIMEOUT_S}s."
                    f"{hint} This is a genuinely slow or hung OCCT operation, not a syntax"
                    f" error — consider simplifying that step (smaller fillet/chamfer radius,"
                    f" fewer profile points, or a coarser pattern count) rather than retrying"
                    f" the same parameters unchanged."
                ),
            }

        # Clean up temp script
        if os.path.exists(temp_script_path):
            os.remove(temp_script_path)

        if process_result.returncode != 0:
            return {
                "success": False,
                "error": f"Python interpreter crashed with return code {process_result.returncode}. Stderr: {process_result.stderr}"
            }

        # Parse output. The script may have printed "[STAGE n/m] ..." progress
        # markers before its final JSON result (see the compiler) — the JSON
        # payload is always the LAST non-empty line, not the whole of stdout.
        output_str = process_result.stdout.strip()
        if not output_str:
            return {
                "success": False,
                "error": f"No output returned from subprocess. Stderr: {process_result.stderr}"
            }

        lines = [ln for ln in output_str.splitlines() if ln.strip()]
        json_line = lines[-1] if lines else ""
        try:
            metrics = json.loads(json_line)
        except json.JSONDecodeError:
            return {
                "success": False,
                "error": f"Failed to parse subprocess output as JSON. Raw output:\n{output_str}\nStderr:\n{process_result.stderr}"
            }

        # A raw exception traceback ("line 268 of the generated script") isn't a
        # useful breadcrumb for the replanner — it can't count codegen lines.
        # Fold in the last "[STAGE n/m] step_id (op)" marker that printed before
        # the crash so the failure names the actual step/op, same diagnostic
        # this feature already gives the timeout path above.
        if metrics.get("success") is False:
            last_stage = next(
                (ln for ln in reversed(lines[:-1]) if ln.startswith("[STAGE")), None
            )
            if last_stage:
                metrics["error"] = f"{last_stage}: {metrics.get('error', '')}"
        return metrics

    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to execute subprocess: {str(e)}"
        }
