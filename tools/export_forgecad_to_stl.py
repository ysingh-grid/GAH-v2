def export_forgecad_to_stl(js_filename: str, output_stl_filename: str) -> str:
    """Export a ForgeCAD script (.forge.js) to a binary STL mesh file.
    
    Args:
        js_filename: The path to the ForgeCAD script to compile.
        output_stl_filename: The target path where the STL file should be written.
        
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
    return f"Successfully exported STL to {workspace_relative(stl_path)}.\nLogs:\n{res.stdout}"
