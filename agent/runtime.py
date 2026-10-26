from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from config.settings import (
    MAX_RETRIES,
    LOG_FILE,
    settings,
)
from tools.registry import ToolRegistry, create_default_registry
from agent.memory import AgentMemory
from agent.planner import Planner
from agent.executor import StepExecutor
from agent.observer import ResultObserver
from agent.verifier import OutcomeVerifier
from agent.human_loop import HumanLoop


def setup_logger(log_level: int = logging.INFO) -> logging.Logger:
    """Configure console logger with clear timestamped output and UTF-8 safe encoding."""
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    logger = logging.getLogger("AutoWorker")
    logger.setLevel(log_level)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(log_level)
        formatter = logging.Formatter(
            fmt="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger


class AgentRuntime:
    """The central orchestrator driving AutoWorker: Goal -> Plan -> Execute -> Observe -> Adapt -> Verify."""

    def __init__(
        self,
        registry: Optional[ToolRegistry] = None,
        memory: Optional[AgentMemory] = None,
        planner: Optional[Planner] = None,
        executor: Optional[StepExecutor] = None,
        observer: Optional[ResultObserver] = None,
        verifier: Optional[OutcomeVerifier] = None,
        human_loop: Optional[HumanLoop] = None,
        max_retries: int = MAX_RETRIES,
        log_file: Optional[str | Path] = None,
    ):
        self.logger = setup_logger()
        self.registry = registry or create_default_registry()
        self.memory = memory or AgentMemory()
        self.planner = planner or Planner(registry=self.registry)
        self.executor = executor or StepExecutor(registry=self.registry)
        self.observer = observer or ResultObserver()
        self.verifier = verifier or OutcomeVerifier()
        self.human_loop = human_loop or HumanLoop()
        self.max_retries = max_retries
        self.log_file = Path(log_file) if log_file else Path(LOG_FILE)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

        self._current_run: dict[str, Any] = {
            "status": "idle",
            "goal": "",
            "task_id": "",
            "events": [],
            "plan": None,
            "steps": [],
            "verification": None,
            "updated_at": datetime.now().isoformat(),
        }

    def _emit_event(self, event_type: str, data: dict[str, Any]):
        """Emit run event and persist to shared JSON log for UI consumption."""
        event = {
            "type": event_type,
            "timestamp": datetime.now().isoformat(),
            "data": data,
        }
        self._current_run["events"].append(event)
        self._current_run["updated_at"] = datetime.now().isoformat()
        try:
            self.log_file.write_text(
                json.dumps(self._current_run, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as e:
            self.logger.warning(f"Could not write log file {self.log_file}: {e}")

    async def run(self, goal: str, task_id: Optional[str] = None) -> dict[str, Any]:
        """Execute the full autonomous agent loop for a given user goal."""
        self.logger.info("=" * 60)
        self.logger.info(f"Starting AutoWorker Run: '{goal}'")
        self.logger.info("=" * 60)

        tid = self.memory.create_task(goal=goal, task_id=task_id)
        self._current_run = {
            "status": "in_progress",
            "goal": goal,
            "task_id": tid,
            "events": [],
            "plan": None,
            "steps": [],
            "context": {},
            "verification": None,
            "updated_at": datetime.now().isoformat(),
        }
        self._emit_event("task_started", {"task_id": tid, "goal": goal})

        try:
            # 1. Plan Generation
            self.logger.info("Generating execution plan via Gemini...")
            plan = await self.planner.create_plan(goal=goal, context=self.memory.get_context(task_id=tid))
            understanding = plan.get("understanding", "")
            steps = plan.get("steps", [])

            self.memory.update_task_status(tid, "in_progress", understanding=understanding)
            self._current_run["plan"] = plan
            self._emit_event("plan_created", {"understanding": understanding, "total_steps": len(steps)})

            self.logger.info(f"Goal Understanding: {understanding}")
            self.logger.info(f"Initial Plan generated: {len(steps)} steps.")
            for s in steps:
                self.logger.info(
                    f"  Step {s.get('step_number')}: [{s.get('tool')}.{s.get('action')}] {s.get('description')}"
                )

            # 2. Step Execution Loop
            step_index = 0
            all_executed_steps: list[dict[str, Any]] = []
            all_observations: list[dict[str, Any]] = []

            while step_index < len(steps):
                current_step = steps[step_index]
                step_num = current_step.get("step_number", step_index + 1)
                desc = current_step.get("description", "")
                requires_approval = bool(current_step.get("requires_human_approval", False))

                self.logger.info("-" * 50)
                self.logger.info(f"Processing Step {step_num}: {desc}")

                # a. Human-in-the-loop approval if required
                if requires_approval:
                    self.logger.info(f"Step {step_num} requires human approval.")
                    self._emit_event("approval_requested", {"step": current_step})
                    approved = await self.human_loop.request_approval(current_step)
                    if not approved:
                        self.logger.warning(f"Step {step_num} was rejected by human operator.")
                        step_record = {
                            "task_id": tid,
                            "step_number": step_num,
                            "description": desc,
                            "tool": current_step.get("tool"),
                            "action": current_step.get("action"),
                            "params": current_step.get("params"),
                            "expected_outcome": current_step.get("expected_outcome"),
                            "requires_human_approval": True,
                            "status": "rejected",
                            "output": "",
                            "error": "Step execution rejected by human.",
                        }
                        self.memory.save_step(step_record)
                        all_executed_steps.append(step_record)
                        self._emit_event("step_rejected", {"step_number": step_num})
                        break

                # b. Execute with retries
                retries_left = self.max_retries
                step_succeeded = False
                last_result = None
                last_obs = None

                while retries_left >= 0:
                    current_context = self.memory.get_context(task_id=tid)
                    self._emit_event("step_started", {"step": current_step, "retries_left": retries_left})

                    last_result = await self.executor.execute_step(current_step, context=current_context)
                    self.logger.info(
                        f"Step {step_num} output ({'SUCCESS' if last_result.success else 'FAILED'}): "
                        f"{(last_result.output or last_result.error)[:120]}"
                    )

                    # c. Observe result with Gemini
                    self.logger.info(f"Observing outcome of Step {step_num} with Gemini...")
                    last_obs = await self.observer.observe(
                        step=current_step,
                        result=last_result,
                        goal=goal,
                    )
                    last_obs["task_id"] = tid
                    last_obs["step_number"] = step_num
                    self.memory.save_observation(last_obs)
                    all_observations.append(last_obs)

                    self.logger.info(f"Observation: {last_obs.get('observation')}")
                    if last_obs.get("extracted_data"):
                        self.logger.info(f"Extracted data: {last_obs.get('extracted_data')}")
                        for k, v in last_obs.get("extracted_data").items():
                            self.memory.save_context(k, v, task_id=tid)

                    if last_obs.get("step_succeeded") and last_obs.get("next_recommendation") != "retry":
                        step_succeeded = True
                        break

                    retries_left -= 1
                    if retries_left >= 0 and last_obs.get("next_recommendation") == "retry":
                        self.logger.warning(
                            f"Step {step_num} failed or requested retry. Retries remaining: {retries_left}. Retrying in 2s..."
                        )
                        self._emit_event("step_retrying", {"step_number": step_num, "retries_left": retries_left})
                        await asyncio.sleep(2.0)

                # Record step in memory
                step_record = {
                    "task_id": tid,
                    "step_number": step_num,
                    "description": desc,
                    "tool": current_step.get("tool", ""),
                    "action": current_step.get("action", ""),
                    "params": current_step.get("params", {}),
                    "expected_outcome": current_step.get("expected_outcome", ""),
                    "requires_human_approval": requires_approval,
                    "status": "success" if step_succeeded else "failed",
                    "output": last_result.output if last_result else "",
                    "error": last_result.error if last_result else "",
                    "screenshot_path": last_result.screenshot_path if last_result else "",
                }
                self.memory.save_step(step_record)
                all_executed_steps.append(step_record)
                self._current_run["steps"].append(step_record)
                self._emit_event("step_finished", {"step": step_record, "observation": last_obs})

                # Handle failure / re-planning
                if not step_succeeded:
                    self.logger.warning(f"Step {step_num} failed after retries. Attempting re-plan...")
                    self._emit_event("replanning_started", {"failed_step": current_step})
                    try:
                        revised_plan = await self.planner.replan(
                            goal=goal,
                            original_plan=plan,
                            failed_step=current_step,
                            observation=last_obs or {},
                            history=all_executed_steps,
                        )
                        new_steps = revised_plan.get("steps", [])
                        if new_steps:
                            self.logger.info(f"Re-plan succeeded with {len(new_steps)} new steps.")
                            self._emit_event("replan_created", {"new_steps": new_steps})
                            steps = steps[:step_index] + new_steps
                            # do not increment step_index; execute first replacement step
                            continue
                        else:
                            self.logger.error("Re-plan returned empty steps. Aborting execution.")
                            break
                    except Exception as e:
                        self.logger.exception(f"Re-planning failed: {e}")
                        break

                step_index += 1

            # 3. Verification
            self.logger.info("=" * 60)
            self.logger.info("Executing final outcome verification...")
            final_context = self.memory.get_context(task_id=tid)
            verification = await self.verifier.verify(
                goal=goal,
                steps=all_executed_steps,
                observations=all_observations,
                context=final_context,
            )

            is_verified = bool(verification.get("verified", False))
            final_status = "completed" if is_verified else "failed"
            self.memory.update_task_status(tid, final_status)

            self._current_run["status"] = final_status
            self._current_run["verification"] = verification
            self._current_run["context"] = final_context
            self._emit_event("task_completed", {
                "verified": is_verified,
                "summary": verification.get("summary"),
                "evidence": verification.get("evidence"),
            })

            self.logger.info(f"Verification Result: {'VERIFIED' if is_verified else 'NOT VERIFIED'}")
            self.logger.info(f"Evidence: {verification.get('evidence')}")
            self.logger.info(f"Summary: {verification.get('summary')}")
            self.logger.info("=" * 60)

            return {
                "task_id": tid,
                "status": final_status,
                "verified": is_verified,
                "summary": verification.get("summary", ""),
                "evidence": verification.get("evidence", ""),
                "context": final_context,
                "steps_executed": len(all_executed_steps),
                "history": all_executed_steps,
            }

        except Exception as e:
            self.logger.exception(f"Fatal error during agent run: {e}")
            self.memory.update_task_status(tid, "failed")
            self._current_run["status"] = "failed"
            self._current_run["error"] = str(e)
            self._emit_event("task_failed", {"error": str(e)})
            return {
                "task_id": tid,
                "status": "failed",
                "verified": False,
                "summary": f"Task execution failed: {str(e)}",
                "evidence": "",
                "context": {},
                "steps_executed": 0,
                "history": [],
            }

        finally:
            # Clean up browser and other resources
            try:
                await self.registry.close_all()
            except Exception:
                pass
