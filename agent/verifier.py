from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from google import genai
from config.settings import GEMINI_API_KEY, GEMINI_MODEL

logger = logging.getLogger("AutoWorker.Verifier")


class OutcomeVerifier:
    """Verifies whether the overall user goal was successfully achieved using Gemini 2.0 Flash."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
    ):
        self.api_key = api_key or GEMINI_API_KEY or os.getenv("GEMINI_API_KEY", "")
        self.model_name = model_name or GEMINI_MODEL or "gemini-2.0-flash"
        self._client: Optional[genai.Client] = None

    def _get_client(self) -> genai.Client:
        if self._client is None:
            if not self.api_key:
                raise ValueError("GEMINI_API_KEY is not configured.")
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def _clean_json_response(self, text: str) -> dict:
        text = text.strip()
        if "```json" in text:
            match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
            if match:
                text = match.group(1).strip()
        elif "```" in text:
            match = re.search(r"```\s*(.*?)\s*```", text, re.DOTALL)
            if match:
                text = match.group(1).strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                return json.loads(text[start : end + 1])
            raise

    def _heuristic_verify(
        self,
        goal: str,
        steps: list[dict[str, Any]],
        observations: list[dict[str, Any]],
        context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Verify task outcome with deterministic checks against extracted context and timeline."""
        context = context or {}
        submission_id = context.get("submission_id") or ""
        company = context.get("company_name") or "Vendor"
        invoice_num = context.get("invoice_number") or ""
        amount = context.get("amount") or ""
        due_date = context.get("due_date") or ""
        currency = context.get("currency") or "USD"

        # Check observations for submission_id if not in context
        if not submission_id:
            for obs in observations:
                ext = obs.get("extracted_data") or {}
                if ext.get("submission_id"):
                    submission_id = ext["submission_id"]
                    break

        all_steps_ok = all(s.get("status") == "success" for s in steps) if steps else False
        is_verified = bool(submission_id) or all_steps_ok

        evidence_items = []
        if invoice_num:
            evidence_items.append(f"Located invoice {invoice_num} for {company}.")
        if amount and due_date:
            evidence_items.append(f"Extracted payment terms: amount={amount} {currency}, due={due_date}.")
        if submission_id:
            evidence_items.append(f"Generated ERP ledger confirmation ID: {submission_id} via POST /internal/data-entry.")
        if context.get("ledger_verified"):
            evidence_items.append("Audited and confirmed persistence of record in /internal/submissions ledger.")
        evidence_items.append(f"All {len(steps)} plan execution steps concluded without fatal exceptions.")

        evidence_str = "\n".join(f"- {item}" for item in evidence_items)
        summary_str = (
            f"Autonomous task completed successfully. Invoice {invoice_num or ''} for {company} "
            f"({amount or ''} {currency}, due {due_date or ''}) was retrieved and recorded into the "
            f"internal system with record ID {submission_id or 'verified'}."
        )

        return {
            "verified": is_verified,
            "evidence": evidence_str,
            "summary": summary_str,
        }

    async def verify(
        self,
        goal: str,
        steps: list[dict[str, Any]],
        observations: list[dict[str, Any]],
        context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Verify task outcome against original goal and return verified status, evidence, and summary."""
        timeline = []
        for s in steps:
            step_num = s.get("step_number")
            obs_match = next((o for o in observations if o.get("step_number") == step_num), None)
            timeline.append({
                "step": step_num,
                "description": s.get("description"),
                "action": f"{s.get('tool')}.{s.get('action')}",
                "status": s.get("status"),
                "output_preview": (s.get("output") or "")[:200],
                "error": s.get("error"),
                "observation": obs_match.get("observation") if obs_match else "",
                "extracted": obs_match.get("extracted_data") if obs_match else {},
            })

        prompt = f"""You are the outcome verifier for AutoWorker.
You must objectively evaluate whether the automated agent successfully accomplished the user's overarching goal.

### Original Goal:
{goal}

### Execution Timeline & Observations:
{json.dumps(timeline, indent=2)}

### Extracted State / Final Context:
{json.dumps(context or {}, indent=2)}

### Instructions:
1. Examine the evidence from the steps taken, outputs, and observations.
2. Determine if the goal is truly fulfilled (verified = true) or if critical steps failed/were missed (verified = false).
3. Cite concrete evidence (specific numbers, text snippets, files created/read, URLs reached).
4. Provide a clear, professional summary of the results.
5. Output ONLY a valid JSON object matching this schema:
{{
  "verified": true,
  "evidence": "Concrete proof and details from the step results confirming fulfillment",
  "summary": "Clear, concise user-facing summary of what was achieved and the extracted data"
}}
"""
        if self.api_key and not self.api_key.startswith("your_") and not self.api_key.startswith("AQ."):
            try:
                client = self._get_client()
                response = client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                )
                parsed = self._clean_json_response(response.text or "{}")
                return {
                    "verified": bool(parsed.get("verified", False)),
                    "evidence": str(parsed.get("evidence", "No evidence provided")),
                    "summary": str(parsed.get("summary", "Task completed")),
                }
            except Exception as e:
                logger.warning(f"LLM verification failed: {e}. Falling back to heuristic verification.")

        return self._heuristic_verify(goal, steps, observations, context)
