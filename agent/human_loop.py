from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from config.settings import PROJECT_ROOT

logger = logging.getLogger("AutoWorker.HumanLoop")


class HumanLoop:
    """Handles human-in-the-loop approval when steps require explicit user consent."""

    def __init__(
        self,
        approval_file: Optional[str | Path] = None,
        auto_approve: bool = False,
        approval_callback: Optional[Callable[[dict[str, Any]], bool]] = None,
    ):
        self.approval_file = Path(approval_file) if approval_file else PROJECT_ROOT / "approval_request.json"
        self.auto_approve = auto_approve or os.getenv("AUTOWORKER_AUTO_APPROVE", "false").lower() in ("1", "true", "yes")
        self.approval_callback = approval_callback

    def format_step_prompt(self, step: dict[str, Any]) -> str:
        """Format step details for human review."""
        step_num = step.get("step_number", "?")
        desc = step.get("description", "No description provided")
        tool = step.get("tool", "unknown")
        action = step.get("action", "unknown")
        params = json.dumps(step.get("params", {}), indent=2)

        return (
            f"\n=======================================================\n"
            f" [HUMAN APPROVAL REQUIRED] Step {step_num}\n"
            f"=======================================================\n"
            f" Description : {desc}\n"
            f" Tool / Action: {tool}.{action}\n"
            f" Parameters  :\n{params}\n"
            f" Expected    : {step.get('expected_outcome', 'None')}\n"
            f"=======================================================\n"
        )

    async def request_approval(self, step: dict[str, Any]) -> bool:
        """Request human approval. Returns True if approved, False otherwise."""
        if self.auto_approve:
            logger.info(f"[Step {step.get('step_number')}] Auto-approved by configuration.")
            return True

        if self.approval_callback:
            try:
                return bool(self.approval_callback(step))
            except Exception as e:
                logger.error(f"Approval callback failed: {e}")
                return False

        # Write request to approval file for UI or external process polling
        req_data = {
            "status": "pending",
            "step": step,
            "timestamp": str(asyncio.get_event_loop().time()),
        }
        try:
            self.approval_file.write_text(json.dumps(req_data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to write approval file: {e}")

        # Check if stdin is interactive (terminal)
        if sys.stdin.isatty():
            prompt_text = self.format_step_prompt(step)
            print(prompt_text, flush=True)

            loop = asyncio.get_event_loop()
            try:
                # Prompt user via async wrapper around standard input
                response = await loop.run_in_executor(
                    None, lambda: input("Do you approve this step? [y/N]: ").strip().lower()
                )
                approved = response in ("y", "yes")

                # Update file state
                req_data["status"] = "approved" if approved else "rejected"
                try:
                    self.approval_file.write_text(json.dumps(req_data, indent=2), encoding="utf-8")
                except Exception:
                    pass

                if approved:
                    logger.info(f"[Step {step.get('step_number')}] Approved by user.")
                else:
                    logger.warning(f"[Step {step.get('step_number')}] Rejected by user.")
                return approved

            except (EOFError, KeyboardInterrupt):
                logger.warning(f"[Step {step.get('step_number')}] Prompt interrupted; rejecting step.")
                return False
        else:
            # Non-interactive fallback: poll approval file for up to 60 seconds
            logger.info(f"Non-interactive session. Polling {self.approval_file} for approval...")
            for _ in range(60):
                await asyncio.sleep(1.0)
                if self.approval_file.exists():
                    try:
                        content = json.loads(self.approval_file.read_text(encoding="utf-8"))
                        status = content.get("status", "").lower()
                        if status == "approved":
                            return True
                        elif status == "rejected":
                            return False
                    except Exception:
                        pass

            logger.warning("Approval request timed out after 60 seconds. Defaulting to rejected.")
            return False
