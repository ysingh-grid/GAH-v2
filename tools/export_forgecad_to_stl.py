def export_forgecad_to_stl(js_filename: str, output_stl_filename: str, output_step_filename: str = None) -> str:
    """Export a ForgeCAD script (.forge.js) to a binary STL mesh file and optionally a STEP file.
    
    Args:
        js_filename: The path to the ForgeCAD script to compile.
        output_stl_filename: The target path where the STL file should be written.
        output_step_filename: The optional target path where the STEP file should be written.
        
    Returns:
        The standard output or compilation logs from the ForgeCAD exporter.
    """
    import subprocess
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    try:
        from .write_workspace_file import resolve_workspace_path, workspace_relative
    except ImportError:
        from write_workspace_file import resolve_workspace_path, workspace_relative

    js_path = resolve_workspace_path(js_filename)
    stl_path = resolve_workspace_path(output_stl_filename)

    if not js_path.name.endswith(".forge.js"):
        raise ValueError(f"ForgeCAD script must be a .forge.js file: {js_filename}")
    if stl_path.suffix != ".stl":
        raise ValueError(f"STL output path must end in .stl: {output_stl_filename}")
    if not js_path.exists():
        raise FileNotFoundError(f"ForgeCAD script not found: {workspace_relative(js_path)}")

    stl_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = ["forgecad", "export", "stl", str(js_path), "--output", str(stl_path)]
    res = subprocess.run(cmd, capture_output=True, text=True)

    if res.returncode != 0:
        raise RuntimeError(f"Error exporting to STL (exit code {res.returncode}):\nStdout: {res.stdout}\nStderr: {res.stderr}")
    
    logs = f"Successfully exported STL to {workspace_relative(stl_path)}.\nLogs:\n{res.stdout}"

    if output_step_filename:
        step_path = resolve_workspace_path(output_step_filename)
        if step_path.suffix != ".step" and step_path.suffix != ".stp":
            raise ValueError(f"STEP output path must end in .step or .stp: {output_step_filename}")
        
        cmd_step = ["forgecad", "export", "step", str(js_path), "--output", str(step_path)]
        res_step = subprocess.run(cmd_step, capture_output=True, text=True)
        if res_step.returncode != 0:
            raise RuntimeError(f"Error exporting to STEP (exit code {res_step.returncode}):\nStdout: {res_step.stdout}\nStderr: {res_step.stderr}")
        logs += f"\nSuccessfully exported STEP to {workspace_relative(step_path)}.\nLogs:\n{res_step.stdout}"

    return logs
