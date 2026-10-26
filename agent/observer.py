from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

from google import genai
from config.settings import GEMINI_API_KEY, GEMINI_MODEL
from tools.base import ToolResult

logger = logging.getLogger("AutoWorker.Observer")


class ResultObserver:
    """Uses Google Gemini to inspect tool execution output, extracted DOM/text, and screenshots."""

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

    def _heuristic_observe(self, step: dict[str, Any], result: ToolResult, goal: str) -> dict[str, Any]:
        """Extract structured entities and determine outcome using semantic heuristics."""
        succeeded = result.success and not bool(result.error)
        extracted: dict[str, Any] = {}
        if isinstance(result.data, dict):
            extracted.update(result.data)

        action = step.get("action", "")
        params = step.get("params", {}) or {}
        selector = str(params.get("selector", "")).lower()
        output_str = str(result.output or "").strip()

        # Match selector patterns to extract semantic invoice fields
        if "#invoice-company" in selector or "#submitted-company-name" in selector:
            extracted["company_name"] = output_str
        elif "#invoice-number" in selector or "#submitted-invoice-number" in selector:
            extracted["invoice_number"] = output_str
        elif "#invoice-amount" in selector or "#submitted-amount" in selector:
            clean_amt = output_str.replace("$", "").replace("₹", "").replace(",", "").strip()
            clean_amt = clean_amt.split()[0] if clean_amt else "0.00"
            extracted["amount"] = clean_amt
        elif "#invoice-due-date" in selector or "#submitted-due-date" in selector:
            extracted["due_date"] = output_str
        elif "#invoice-currency" in selector:
            extracted["currency"] = output_str
        elif "#invoice-description" in selector:
            extracted["notes"] = output_str
        elif "#submitted-id" in selector or "sub-" in output_str.lower():
            match = re.search(r'(SUB-\d+)', output_str)
            if match:
                extracted["submission_id"] = match.group(1)
            else:
                extracted["submission_id"] = output_str
        elif "#submissions-table" in selector or "submissions" in str(params.get("url", "")):
            extracted["ledger_verified"] = True

        # Parse invoice catalog table if retrieved
        if ("#invoice-table" in selector or "invoices" in selector or "INV-2026" in output_str) and output_str:
            inv_matches = list(re.finditer(r'(INV-\d{4}-\d{3})', output_str))
            if inv_matches:
                invoices = []
                for i, match in enumerate(inv_matches):
                    inv_num = match.group(1)
                    start_p = inv_matches[i-1].end() if i > 0 else 0
                    pre_text = output_str[start_p:match.start()].strip()
                    pre_lines = [line.strip() for line in pre_text.split('\n') if line.strip()]

                    company = "Unknown"
                    valid_lines = [
                        l for l in pre_lines
                        if not any(h in l.upper() for h in ["COMPANY", "INVOICE #", "ACTIONS", "DUE DATE", "STATUS", "VIEW DETAILS"])
                    ]
                    if len(valid_lines) >= 2:
                        company = valid_lines[-2]
                    elif len(valid_lines) == 1:
                        company = valid_lines[-1]

                    end_p = inv_matches[i+1].start() if i + 1 < len(inv_matches) else len(output_str)
                    post_text = output_str[match.end():end_p]

                    amt_match = re.search(r'([$₹€£]?\s*[\d,]+\.\d{2})', post_text)
                    raw_amt = amt_match.group(1) if amt_match else "0.00"
                    clean_amt = re.sub(r'[^\d.]', '', raw_amt)

                    curr_match = re.search(r'\b(USD|INR|EUR|GBP)\b', post_text)
                    currency = curr_match.group(1) if curr_match else ("INR" if "₹" in post_text else "USD")

                    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', post_text)
                    due_date = date_match.group(1) if date_match else ""

                    status_match = re.search(r'\b(Overdue|Pending|Paid)\b', post_text, re.IGNORECASE)
                    status = status_match.group(1).capitalize() if status_match else "Unknown"

                    invoices.append({
                        "company_name": company,
                        "invoice_number": inv_num,
                        "amount": clean_amt,
                        "currency": currency,
                        "due_date": due_date,
                        "status": status,
                    })

                extracted["invoices"] = invoices
                overdue = [inv for inv in invoices if inv["status"].lower() == "overdue"]
                extracted["overdue_invoices"] = overdue
                extracted["total_invoices_found"] = len(invoices)
                extracted["overdue_count"] = len(overdue)

                if len(invoices) == 1:
                    extracted["company_name"] = invoices[0]["company_name"]
                    extracted["invoice_number"] = invoices[0]["invoice_number"]
                    extracted["amount"] = invoices[0]["amount"]
                    extracted["currency"] = invoices[0]["currency"]
                    extracted["due_date"] = invoices[0]["due_date"]
                    extracted["status"] = invoices[0]["status"]

                # Detailed observation text
                if overdue and "overdue" in goal.lower():
                    overdue_lines = [
                        f"{inv['invoice_number']} | {inv['company_name']} | {inv['amount']} {inv['currency']} | Due: {inv['due_date']} | Status: {inv['status']}"
                        for inv in overdue
                    ]
                    output_str = f"Extracted {len(overdue)} Overdue Invoices:\n" + "\n".join(f"• {l}" for l in overdue_lines)
                else:
                    inv_lines = [
                        f"{inv['invoice_number']} | {inv['company_name']} | {inv['amount']} {inv['currency']} | Due: {inv['due_date']} | Status: {inv['status']}"
                        for inv in invoices
                    ]
                    output_str = f"Extracted {len(invoices)} Invoices:\n" + "\n".join(f"• {l}" for l in inv_lines)

        # Regex fallback on raw page content
        if action in ("get_page_content", "content") and output_str:
            sub_match = re.search(r'(SUB-\d+)', output_str)
            if sub_match:
                extracted["submission_id"] = sub_match.group(1)
                extracted["ledger_verified"] = True

        return {
            "step_succeeded": succeeded,
            "observation": output_str if succeeded else f"Error: {result.error}",
            "extracted_data": extracted,
            "next_recommendation": "continue" if succeeded else "retry",
            "screenshot_path": result.screenshot_path,
        }

    async def observe(
        self,
        step: dict[str, Any],
        result: ToolResult,
        goal: str = "",
    ) -> dict[str, Any]:
        """Analyze tool result and return a structured observation."""
        step_num = step.get("step_number", 0)
        tool_name = step.get("tool", "")
        action_name = step.get("action", "")
        expected_outcome = step.get("expected_outcome", "")
        step_desc = step.get("description", "")

        raw_output = result.output or ""
        trimmed_output = raw_output[:5000] + ("\n... [truncated]" if len(raw_output) > 5000 else "")

        prompt = f"""You are the result observer for AutoWorker.
Your task is to analyze the outcome of a step that was just executed by an automated tool.

### Overall Task Goal:
{goal}

### Step Being Evaluated:
- Step Number: {step_num}
- Description: {step_desc}
- Tool: {tool_name}
- Action: {action_name}
- Parameters: {json.dumps(step.get("params", {}))}
- Expected Outcome: {expected_outcome}

### Execution Result:
- Success Flag Reported by Tool: {result.success}
- Tool Error (if any): {result.error or 'None'}
- Screenshot Path: {result.screenshot_path or 'None'}
- Structured Tool Data: {json.dumps(result.data or {})}
- Raw Output / Text Content:
\"\"\"
{trimmed_output}
\"\"\"

### Instructions:
1. Determine whether the step actually succeeded in meeting its expected outcome.
2. Extract any important entities, metrics, text, numbers, or state (e.g. invoice total, status, IDs, confirmation messages) into key-value pairs in "extracted_data".
3. Recommend the next action ("continue", "retry", "replan", "abort").
4. Output ONLY a valid JSON object matching this schema:
{{
  "step_succeeded": true,
  "observation": "Clear description of what happened and what the tool output reveals",
  "extracted_data": {{}},
  "next_recommendation": "continue"
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
                    "step_succeeded": bool(parsed.get("step_succeeded", result.success)),
                    "observation": str(parsed.get("observation", result.output or result.error or "Completed")),
                    "extracted_data": parsed.get("extracted_data") or {},
                    "next_recommendation": str(parsed.get("next_recommendation", "continue" if result.success else "retry")),
                    "screenshot_path": result.screenshot_path,
                }
            except Exception as e:
                logger.warning(f"LLM observation failed: {e}. Falling back to semantic heuristic observation.")

        return self._heuristic_observe(step, result, goal)
