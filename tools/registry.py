from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from tools.base import BaseTool
from tools.browser_tool import BrowserTool
from tools.file_tool import FileTool


class ToolRegistry:
    """Registry managing available tools and providing tool descriptions for LLMs."""

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a new tool instance."""
        self._tools[tool.name.lower()] = tool

    def get_tool(self, name: str) -> Optional[BaseTool]:
        """Retrieve a registered tool by name."""
        return self._tools.get(name.lower().strip())

    def list_tools(self) -> list[str]:
        """Return names of all registered tools."""
        return list(self._tools.keys())

    def find_tool_for_action(self, action_name: str) -> Optional[BaseTool]:
        """Find a tool that supports the given action name."""
        action_clean = action_name.lower().strip()
        for tool in self._tools.values():
            for action_info in tool.get_available_actions():
                if action_info.get("action", "").lower() == action_clean:
                    return tool
        return None

    def get_tools_description_for_llm(self) -> str:
        """Generate a formatted markdown/JSON summary of available tools for LLM prompts."""
        tools_spec = []
        for name, tool in self._tools.items():
            tool_spec = {
                "name": name,
                "description": tool.description,
                "actions": tool.get_available_actions()
            }
            tools_spec.append(tool_spec)
        return json.dumps(tools_spec, indent=2)

    def get_tools_prompt_text(self) -> str:
        """Human-readable description of tools and actions for system instructions."""
        lines = []
        for name, tool in self._tools.items():
            lines.append(f"### Tool: `{name}`")
            lines.append(f"Description: {tool.description}")
            lines.append("Actions:")
            for action in tool.get_available_actions():
                act_name = action.get("action")
                act_desc = action.get("description")
                act_params = json.dumps(action.get("params", {}))
                lines.append(f"  - `{act_name}`: {act_desc} | params: {act_params}")
            lines.append("")
        return "\n".join(lines)

    async def close_all(self):
        """Close/cleanup any tool that supports closing (e.g. BrowserTool)."""
        for tool in self._tools.values():
            if hasattr(tool, "close") and callable(tool.close):
                try:
                    await tool.close()
                except Exception:
                    pass


def create_default_registry(headless: Optional[bool] = None) -> ToolRegistry:
    """Create and populate a ToolRegistry with default tools."""
    registry = ToolRegistry()
    registry.register(BrowserTool(headless=headless))
    registry.register(FileTool())
    return registry
