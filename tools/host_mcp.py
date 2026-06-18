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

@mcp.tool()
def ask_user(question: str) -> str:
    """Ask a question to the user to clarify requirements or get additional context.
    
    Args:
        question: The question to ask the user.
        
    Returns:
        The response typed by the user.
    """
    safe_question = question.replace('"', '\\"').replace("'", "\\'")
    apple_script = f'display dialog "{safe_question}" default answer "" buttons {{"OK"}} default button "OK" with title "Geometry Agent Harness: Clarification"'
    try:
        res = subprocess.run(
            ["osascript", "-e", apple_script],
            capture_output=True,
            text=True,
            check=True
        )
        output = res.stdout.strip()
        if "text returned:" in output:
            return output.split("text returned:", 1)[1]
        return ""
    except Exception as e:
        return f"Error prompting user: {e}"

if __name__ == "__main__":
    mcp.run()
