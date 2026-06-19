from mcp.server.fastmcp import FastMCP
import subprocess
from dotenv import load_dotenv

# Import modular tools
from write_workspace_file import (
    resolve_workspace_path,
    write_workspace_file as _write_workspace_file,
)
from export_forgecad_to_stl import export_forgecad_to_stl as _export_forgecad_to_stl
from write_and_export_forgecad_model import (
    write_and_export_forgecad_model as _write_and_export_forgecad_model,
)
from forgecad_docs import (
    forgecad_api_lookup as _forgecad_api_lookup,
    forgecad_code_lint as _forgecad_code_lint,
    forgecad_decompose_prompt as _forgecad_decompose_prompt,
    forgecad_doc_topics as _forgecad_doc_topics,
    forgecad_web_doc_lookup as _forgecad_web_doc_lookup,
)

# Load environment variables
load_dotenv()

# Create the MCP server
mcp = FastMCP("HostTools")

@mcp.tool()
def read_workspace_file(filename: str) -> str:
    """Read a file from the host workspace filesystem.
    
    Args:
        filename: The relative or absolute path of the file to read.
        
    Returns:
        The text content of the file.
    """
    path = resolve_workspace_path(filename)

    with open(path, "r", encoding="utf-8") as f:
        return f.read()

@mcp.tool()
def write_workspace_file(filename: str, content: str) -> str:
    """Write a file to the host workspace filesystem.
    
    Args:
        filename: The relative or absolute path of the file to write.
        content: The text content to write into the file.
        
    Returns:
        A success message or status.
    """
    return _write_workspace_file(filename, content)

@mcp.tool()
def export_forgecad_to_stl(js_filename: str, output_stl_filename: str) -> str:
    """Export a ForgeCAD script (.forge.js) to a binary STL mesh file.
    
    Args:
        js_filename: The path to the ForgeCAD script to compile.
        output_stl_filename: The target path where the STL file should be written.
        
    Returns:
        The standard output or compilation logs from the ForgeCAD exporter.
    """
    return _export_forgecad_to_stl(js_filename, output_stl_filename)

@mcp.tool()
def write_and_export_forgecad_model(design_name: str, js_content: str) -> dict:
    """Write and compile a ForgeCAD model in one schema-ready operation.

    Args:
        design_name: Kebab-case folder name under outputs/.
        js_content: Complete ForgeCAD JavaScript source for model.forge.js.

    Returns:
        A dict matching the CAD generation result schema.
    """
    return _write_and_export_forgecad_model(design_name, js_content)

@mcp.tool()
def forgecad_doc_topics(prompt: str) -> list[str]:
    """Choose compact ForgeCAD documentation topics for a CAD prompt."""
    return _forgecad_doc_topics(prompt)

@mcp.tool()
def forgecad_api_lookup(topic: str) -> dict:
    """Return compact local ForgeCAD API snippets for a topic or symbol."""
    return _forgecad_api_lookup(topic)

@mcp.tool()
def forgecad_web_doc_lookup(topic: str) -> dict:
    """Fetch compact official ForgeCAD docs as a local-miss fallback.

    Only https://forgecad.io/docs/* is allowed.
    """
    return _forgecad_web_doc_lookup(topic)

@mcp.tool()
def forgecad_decompose_prompt(prompt: str) -> dict:
    """Create a deterministic CAD decomposition scaffold from a prompt."""
    return _forgecad_decompose_prompt(prompt)

@mcp.tool()
def forgecad_code_lint(js_content: str) -> dict:
    """Lint ForgeCAD JavaScript for forbidden APIs and common generation errors."""
    return _forgecad_code_lint(js_content)

@mcp.tool()
def execute_python_package_check() -> str:
    """Run a quick CLI command on the host (e.g., check pip version or running environment info).
    
    Returns:
        The standard output of the command run on the host.
    """
    res = subprocess.run(["pip", "--version"], capture_output=True, text=True)
    return res.stdout.strip()

if __name__ == "__main__":
    mcp.run()
