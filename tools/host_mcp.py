from mcp.server.fastmcp import FastMCP
import os
import subprocess
from pathlib import Path

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
    path = Path(filename)
    # Securely resolve path relative to current workspace if relative
    if not path.is_absolute():
        workspace_root = Path(__file__).parent.parent
        path = workspace_root / path
    
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

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
