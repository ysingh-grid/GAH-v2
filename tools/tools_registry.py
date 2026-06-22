"""
Load and manage RLM tools (functions)
"""

from tools.execute_cadquery import execute_cadquery
from tools.inspect_mesh import inspect_mesh
from tools.load_trace import list_traces, load_trace
from tools.primitive_lookup import get_primitives
from tools.read_skill import list_skills, read_skill
from tools.render_views import render_views
from tools.verify_geometry import verify_geometry
from tools.write_trace import write_trace


class ToolsRegistry:
    """Manages available tools (functions) for RLM agents"""

    def __init__(self):
        self.tools = {
            "read_skill": read_skill,
            "list_skills": list_skills,
            "get_primitives": get_primitives,
            "execute_cadquery": execute_cadquery,
            "inspect_mesh": inspect_mesh,
            "render_views": render_views,
            "verify_geometry": verify_geometry,
            "write_trace": write_trace,
            "load_trace": load_trace,
            "list_traces": list_traces,
        }


    def get_all(self) -> list:
        """Return all tools as a list for fast_rlm.run()"""
        tools_list = list(self.tools.values())
        print(f"[DEBUG] Returning {len(tools_list)} tools: {[t.__name__ for t in tools_list]}")
        return tools_list

    def get(self, name: str):
        """Get a specific tool by name"""
        return self.tools.get(name)

    def list_tools(self) -> dict:
        """List all tools with docstrings"""
        return {name: func.__doc__ for name, func in self.tools.items()}


registry = ToolsRegistry()

# Debug: Test on import
print(f"[INIT] Registry initialized with {len(registry.tools)} tools")
