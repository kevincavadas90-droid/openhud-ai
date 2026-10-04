from .base import Tool, ToolContext, ToolResult, ToolRegistry
from .filesystem import build_filesystem_tools
from .execution import build_execution_tools
from .web import build_web_tools
from .memory_tools import build_memory_tools
from .data import build_data_tools
from .pc import build_pc_tools
from .assistant import build_assistant_tools, CONTROL_TOOLS
from .trading import build_trading_tools
from .media import build_media_tools
from .codex import build_codex_tools
from .system import build_system_tools

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
        + build_assistant_tools()
        + build_trading_tools()
        + build_media_tools()
        + build_codex_tools()
        + build_system_tools()
    ):
        registry.register(tool)
    return registry
