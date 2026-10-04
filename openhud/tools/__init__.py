from .base import Tool, ToolContext, ToolResult, ToolRegistry
from .filesystem import build_filesystem_tools
from .execution import build_execution_tools
from .web import build_web_tools
from .memory_tools import build_memory_tools
from .data import build_data_tools
from .pc import build_pc_tools

__all__ = [
    "Tool",
    "ToolContext",
    "ToolResult",
    "ToolRegistry",
    "build_default_registry",
]


def build_default_registry() -> "ToolRegistry":
    """Assemble the full tool set available to the agent."""
    registry = ToolRegistry()
    for tool in (
        build_filesystem_tools()
        + build_execution_tools()
        + build_web_tools()
        + build_memory_tools()
        + build_data_tools()
        + build_pc_tools()
    ):
        registry.register(tool)
    return registry
