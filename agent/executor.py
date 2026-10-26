from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional

from tools.base import ToolResult
from tools.registry import ToolRegistry

logger = logging.getLogger("AutoWorker.Executor")


class StepExecutor:
    """Executes planned individual steps using registered tools with timeout and exception safety."""

    def __init__(
        self,
        registry: ToolRegistry,
        default_timeout_seconds: float = 45.0,
    ):
        self.registry = registry
        self.default_timeout_seconds = default_timeout_seconds

    async def execute_step(
        self,
        step: dict[str, Any],
        context: Optional[dict[str, Any]] = None,
    ) -> ToolResult:
        """Execute a single planned step and return the ToolResult."""
        tool_name = step.get("tool", "").strip()
        action_name = step.get("action", "").strip()
        raw_params = step.get("params") or {}
        step_num = step.get("step_number", 0)

        # Lookup tool
        tool = self.registry.get_tool(tool_name)
        if not tool:
            # Fallback: check if any tool handles this action
            tool = self.registry.find_tool_for_action(action_name)
            if tool:
                logger.info(f"[Step {step_num}] Auto-resolved tool '{tool.name}' for action '{action_name}'")

        if not tool:
            error_msg = f"Tool '{tool_name}' not found in registry. Available tools: {self.registry.list_tools()}"
            logger.error(f"[Step {step_num}] {error_msg}")
            return ToolResult(
                success=False,
                output="",
                error=error_msg,
                data={"step_number": step_num, "tool": tool_name, "action": action_name}
            )

        # Substitute any context variables in params if strings like "{extracted_key}" exist
        resolved_params = self._resolve_params(raw_params, context or {})

        logger.info(f"[Step {step_num}] Executing {tool.name}.{action_name} with params: {resolved_params}")
        start_time = time.time()

        try:
            # Execute with timeout
            result = await asyncio.wait_for(
                tool.execute(action_name, resolved_params),
                timeout=self.default_timeout_seconds,
            )
            duration = round(time.time() - start_time, 2)
            if result.data is None:
                result.data = {}
            result.data["duration_seconds"] = duration
            result.data["step_number"] = step_num
            return result

        except asyncio.TimeoutError:
            err = f"Step {step_num} execution timed out after {self.default_timeout_seconds}s for {tool_name}.{action_name}"
            logger.error(err)
            return ToolResult(
                success=False,
                output="",
                error=err,
                data={"step_number": step_num, "timeout": True}
            )

        except Exception as e:
            err = f"Unexpected exception in step {step_num} ({tool_name}.{action_name}): {str(e)}"
            logger.exception(err)
            return ToolResult(
                success=False,
                output="",
                error=err,
                data={"step_number": step_num, "exception_type": type(e).__name__}
            )

    def _resolve_params(self, params: Any, context: dict[str, Any]) -> Any:
        """Recursively substitute placeholder variables like {key} from context."""
        if not context:
            return params

        if isinstance(params, str):
            res = params
            for k, v in context.items():
                if isinstance(v, (str, int, float, bool)):
                    res = res.replace(f"{{{k}}}", str(v))
            return res
        elif isinstance(params, dict):
            return {k: self._resolve_params(v, context) for k, v in params.items()}
        elif isinstance(params, list):
            return [self._resolve_params(item, context) for item in params]
        return params
