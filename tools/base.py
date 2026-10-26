from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional


@dataclass
class ToolResult:
    success: bool
    output: str
    error: str = ""
    screenshot_path: str = ""
    data: dict = None

    def __post_init__(self):
        if self.data is None:
            self.data = {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "screenshot_path": self.screenshot_path,
            "data": self.data,
        }


class BaseTool(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the tool."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Description of what the tool does."""
        ...

    @abstractmethod
    async def execute(self, action: str, params: dict) -> ToolResult:
        """Execute a specific action with the given parameters."""
        ...

    @abstractmethod
    def get_available_actions(self) -> list[dict]:
        """Return a list of available actions and their parameter descriptions."""
        ...
