from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from google import genai
from config.settings import GEMINI_API_KEY, GEMINI_MODEL
from tools.registry import ToolRegistry

logger = logging.getLogger("AutoWorker.Planner")


class Planner:
    """LLM-powered task planner utilizing Google Gemini (gemini-2.0-flash)."""

    def __init__(
        self,
        registry: ToolRegistry,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
    ):
        self.registry = registry
        self.api_key = api_key or GEMINI_API_KEY or os.getenv("GEMINI_API_KEY", "")
        self.model_name = model_name or GEMINI_MODEL or "gemini-2.0-flash"
        self._client: Optional[genai.Client] = None

    def _get_client(self) -> genai.Client:
        if self._client is None:
            if not self.api_key:
                raise ValueError(
                    "GEMINI_API_KEY is not set. Please set GEMINI_API_KEY in your .env file "
                    "or environment variables."
                )
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def _clean_json_response(self, text: str) -> dict:
        """Extract and parse JSON object from LLM response text."""
        text = text.strip()
        # Remove markdown fenced code blocks if present
        if "```json" in text:
            match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
            if match:
                text = match.group(1).strip()
        elif "```" in text:
            match = re.search(r"```\s*(.*?)\s*```", text, re.DOTALL)
            if match:
                text = match.group(1).strip()

        # Try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to find outermost { and }
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                substring = text[start : end + 1]
                return json.loads(substring)
            raise

    def _generate_heuristic_plan(self, goal: str, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """Dynamically decompose user goal into structured execution steps."""
        goal_lower = goal.lower()
        company_name = "Acme Corp"
        inv_id = 1

        # Check against known companies in mock app
        known_vendors = [
            ("acme", "Acme Corp", 1),
            ("techvision", "TechVision Solutions", 2),
            ("global logistics", "Global Logistics Inc", 3),
            ("apex cloud", "Apex Cloud Systems", 4),
            ("apex", "Apex Cloud Systems", 4),
            ("starlight", "Starlight Media Works", 5),
            ("biovantage", "BioVantage Labs", 6),
            ("quantum", "Quantum Dynamics", 7),
            ("zenith", "Zenith Retailers", 8),
            ("pacific", "Pacific Rim Shipping", 9),
            ("nordic", "Nordic Data Networks", 10),
        ]
        for key, name, iid in known_vendors:
            if key in goal_lower:
                company_name = name
                inv_id = iid
                break
        else:
            match = re.search(r'(?:company\s+)([A-Za-z0-9\s]+?)(?:,|\.|\s+extract|\s+and|$)', goal, re.IGNORECASE)
            if match:
                candidate = match.group(1).strip()
                if candidate and candidate.lower() not in ("x", "name", ""):
                    company_name = candidate

        # Branch A: Overdue Invoices, Select/List All Invoices, Summary Reports
        if any(k in goal_lower for k in ["overdue", "select all", "list all", "all invoice", "all overdue", "summary report", "select invoice"]):
            is_overdue = "overdue" in goal_lower
            steps = [
                {
                    "step_number": 1,
                    "description": "Navigate to CorpFlow Invoices catalog",
                    "tool": "browser",
                    "action": "navigate",
                    "params": {"url": "http://localhost:5001/invoices"},
                    "expected_outcome": "Invoices catalog loads showing accounts payable table and filters",
                    "requires_human_approval": False,
                },
                {
                    "step_number": 2,
                    "description": "Filter invoices by OVERDUE status" if is_overdue else "Select ALL invoices in status filter",
                    "tool": "browser",
                    "action": "select_option",
                    "params": {
                        "selector": "#invoice-status-filter",
                        "value": "OVERDUE" if is_overdue else "ALL",
                    },
                    "expected_outcome": "Catalog filters to display overdue invoices" if is_overdue else "Catalog displays all active invoices",
                    "requires_human_approval": False,
                },
                {
                    "step_number": 3,
                    "description": "Extract invoice catalog table line items including Company, Invoice #, Amount, Due Date, and Status",
                    "tool": "browser",
                    "action": "get_page_content",
                    "params": {"selector": "#invoice-table"},
                    "expected_outcome": "Complete structured table extracted with amounts, due dates, and statuses",
                    "requires_human_approval": False,
                },
                {
                    "step_number": 4,
                    "description": "Capture visual audit record screenshot of the filtered invoice ledger",
                    "tool": "browser",
                    "action": "screenshot",
                    "params": {},
                    "expected_outcome": "Visual screenshot audit captured verifying all invoice records and due dates",
                    "requires_human_approval": False,
                },
            ]
            understanding = (
                f"Autonomous Task: Navigate to CorpFlow Invoices catalog, "
                f"{'apply OVERDUE status filter' if is_overdue else 'select ALL invoice statuses'}, "
                f"extract all line items with explicit payment due dates, amounts, and vendor names, "
                f"and generate a verified summary report."
            )
            return {
                "understanding": understanding,
                "steps": steps,
            }

        # Branch B: Verification of Processing in Submissions Ledger
        if "verify" in goal_lower and any(k in goal_lower for k in ["process", "submission", "ledger", "entered", "recorded"]):
            steps = [
                {
                    "step_number": 1,
                    "description": f"Navigate to CorpFlow Invoices catalog to check {company_name} invoice",
                    "tool": "browser",
                    "action": "navigate",
                    "params": {"url": "http://localhost:5001/invoices"},
                    "expected_outcome": "Invoices catalog renders",
                    "requires_human_approval": False,
                },
                {
                    "step_number": 2,
                    "description": f"Extract invoice information and due date for {company_name}",
                    "tool": "browser",
                    "action": "get_page_content",
                    "params": {"selector": "#invoice-table"},
                    "expected_outcome": f"Locate invoice line item and due date for {company_name}",
                    "requires_human_approval": False,
                },
                {
                    "step_number": 3,
                    "description": "Navigate to CorpFlow Internal Submissions Ledger",
                    "tool": "browser",
                    "action": "navigate",
                    "params": {"url": "http://localhost:5001/internal/submissions"},
                    "expected_outcome": "Internal Submissions page loads",
                    "requires_human_approval": False,
                },
                {
                    "step_number": 4,
                    "description": f"Verify whether transaction for {company_name} is recorded in Submissions Ledger",
                    "tool": "browser",
                    "action": "get_page_content",
                    "params": {"selector": "#submissions-table"},
                    "expected_outcome": "Verified transaction record in the ledger table",
                    "requires_human_approval": False,
                },
            ]
            return {
                "understanding": f"Audit verification task: Check {company_name} invoice status in catalog and verify its presence in the Internal Submissions Ledger.",
                "steps": steps,
            }

        # Branch C: Single Invoice Data Entry Workflow (e.g. Acme Corp)
        steps = [
            {
                "step_number": 1,
                "description": "Navigate to CorpFlow Invoices catalog",
                "tool": "browser",
                "action": "navigate",
                "params": {"url": "http://localhost:5001/invoices"},
                "expected_outcome": "Invoices page loads showing invoice catalog",
                "requires_human_approval": False,
            },
            {
                "step_number": 2,
                "description": f"Open details page for {company_name} invoice",
                "tool": "browser",
                "action": "click",
                "params": {"selector": f"#invoice-view-btn-{inv_id}"},
                "expected_outcome": "Invoice detail page displays full invoice data",
                "requires_human_approval": False,
            },
            {
                "step_number": 3,
                "description": "Extract vendor company name",
                "tool": "browser",
                "action": "get_text",
                "params": {"selector": "#invoice-company"},
                "expected_outcome": "Vendor company name extracted",
                "requires_human_approval": False,
            },
            {
                "step_number": 4,
                "description": "Extract invoice identifier number",
                "tool": "browser",
                "action": "get_text",
                "params": {"selector": "#invoice-number"},
                "expected_outcome": "Invoice number extracted",
                "requires_human_approval": False,
            },
            {
                "step_number": 5,
                "description": "Extract invoice total amount",
                "tool": "browser",
                "action": "get_text",
                "params": {"selector": "#invoice-amount"},
                "expected_outcome": "Invoice amount extracted",
                "requires_human_approval": False,
            },
            {
                "step_number": 6,
                "description": "Extract payment due date",
                "tool": "browser",
                "action": "get_text",
                "params": {"selector": "#invoice-due-date"},
                "expected_outcome": "Payment due date extracted",
                "requires_human_approval": False,
            },
            {
                "step_number": 7,
                "description": "Transfer details and navigate to CorpFlow Internal Data Entry form",
                "tool": "browser",
                "action": "click",
                "params": {"selector": "#copy-to-internal-btn"},
                "expected_outcome": "Internal Data Entry form loads with pre-filled details",
                "requires_human_approval": False,
            },
            {
                "step_number": 8,
                "description": "Submit invoice transaction record into Internal ERP Ledger",
                "tool": "browser",
                "action": "click",
                "params": {"selector": "#submit-btn"},
                "expected_outcome": "Transaction submitted and confirmation screen rendered",
                "requires_human_approval": True,
            },
            {
                "step_number": 9,
                "description": "Extract generated confirmation record ID (SUB-ID)",
                "tool": "browser",
                "action": "get_text",
                "params": {"selector": "#submitted-id"},
                "expected_outcome": "Confirmation SUB-ID recorded into memory",
                "requires_human_approval": False,
            },
            {
                "step_number": 10,
                "description": "Navigate to Internal Submissions ledger to verify record persistence",
                "tool": "browser",
                "action": "navigate",
                "params": {"url": "http://localhost:5001/internal/submissions"},
                "expected_outcome": "Submissions ledger page renders showing verified entry",
                "requires_human_approval": False,
            },
            {
                "step_number": 11,
                "description": "Validate recorded transaction in submissions ledger table",
                "tool": "browser",
                "action": "get_page_content",
                "params": {"selector": "#submissions-table"},
                "expected_outcome": "Submission record verified in the ledger",
                "requires_human_approval": False,
            },
        ]

        return {
            "understanding": (
                f"Autonomous Task Execution: Locate latest invoice for '{company_name}', "
                f"extract critical line items (invoice number, amount, payment due date), "
                f"evaluate compliance policies (requiring human supervisor sign-off on transactions), "
                f"enter the transaction into the CorpFlow Internal ERP Ledger, and verify outcome."
            ),
            "steps": steps,
        }

    def _generate_heuristic_replan(
        self,
        goal: str,
        failed_step: dict[str, Any],
        observation: dict[str, Any],
        history: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Generate recovery steps if a step fails."""
        step_num = failed_step.get("step_number", 1)
        action = failed_step.get("action", "")
        if "#copy-to-internal-btn" in str(failed_step.get("params", {})):
            return {
                "understanding": "Copy button was not available. Falling back to direct URL navigation and form filling.",
                "steps": [
                    {
                        "step_number": step_num,
                        "description": "Navigate directly to Internal Data Entry form",
                        "tool": "browser",
                        "action": "navigate",
                        "params": {"url": "http://localhost:5001/internal/data-entry"},
                        "expected_outcome": "Data entry form loaded",
                        "requires_human_approval": False,
                    },
                    {
                        "step_number": step_num + 1,
                        "description": "Enter company name",
                        "tool": "browser",
                        "action": "type_text",
                        "params": {"selector": "#company_name", "text": "{company_name}"},
                        "expected_outcome": "Company name typed",
                        "requires_human_approval": False,
                    },
                    {
                        "step_number": step_num + 2,
                        "description": "Enter invoice number",
                        "tool": "browser",
                        "action": "type_text",
                        "params": {"selector": "#invoice_number", "text": "{invoice_number}"},
                        "expected_outcome": "Invoice number typed",
                        "requires_human_approval": False,
                    },
                    {
                        "step_number": step_num + 3,
                        "description": "Enter amount",
                        "tool": "browser",
                        "action": "type_text",
                        "params": {"selector": "#amount", "text": "{amount}"},
                        "expected_outcome": "Amount typed",
                        "requires_human_approval": False,
                    },
                    {
                        "step_number": step_num + 4,
                        "description": "Enter due date",
                        "tool": "browser",
                        "action": "type_text",
                        "params": {"selector": "#due_date", "text": "{due_date}"},
                        "expected_outcome": "Due date typed",
                        "requires_human_approval": False,
                    },
                    {
                        "step_number": step_num + 5,
                        "description": "Submit invoice transaction record",
                        "tool": "browser",
                        "action": "click",
                        "params": {"selector": "#submit-btn"},
                        "expected_outcome": "Form submitted",
                        "requires_human_approval": True,
                    },
                ],
            }

        return {
            "understanding": f"Attempting recovery after failed {action} action.",
            "steps": [
                {
                    "step_number": step_num,
                    "description": f"Retry step {step_num} after brief pause",
                    "tool": failed_step.get("tool", "browser"),
                    "action": failed_step.get("action", "wait_for"),
                    "params": failed_step.get("params", {}),
                    "expected_outcome": failed_step.get("expected_outcome", "Step completes"),
                    "requires_human_approval": False,
                }
            ],
        }

    async def create_plan(
        self,
        goal: str,
        context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Generate a structured plan for the given user goal."""
        tools_description = self.registry.get_tools_prompt_text()
        context_str = json.dumps(context or {}, indent=2)

        prompt = f"""You are the master planner for an autonomous AI task worker called AutoWorker.
Your goal is to break down the user's high-level goal into an efficient, robust sequence of actionable steps using the available tools.

### Available Tools:
{tools_description}

### Current Context:
{context_str}

### User Goal:
{goal}

### Instructions:
1. Carefully analyze what the user wants to achieve.
2. Formulate a step-by-step execution plan using ONLY the registered tools and their available actions.
3. Steps should be logical, concise, and each have a clear expected outcome.
4. Set "requires_human_approval": true ONLY for destructive or critical operations (e.g. deleting files, submitting irreversible transactions).
5. Output ONLY a valid JSON object matching the following structure:
{{
  "understanding": "Detailed explanation of what the user wants to achieve",
  "steps": [
    {{
      "step_number": 1,
      "description": "What this step does",
      "tool": "browser",
      "action": "navigate",
      "params": {{"url": "http://localhost:5001/invoices"}},
      "expected_outcome": "Invoice listing page loads",
      "requires_human_approval": false
    }}
  ]
}}
Do not include any commentary outside the JSON block.
"""
        # Attempt Gemini 2.0 Flash call if configured
        if self.api_key and not self.api_key.startswith("your_") and not self.api_key.startswith("AQ."):
            try:
                client = self._get_client()
                response = client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                )
                plan_text = response.text or ""
                return self._clean_json_response(plan_text)
            except Exception as e:
                logger.warning(f"Gemini API planning failed: {e}. Falling back to Autonomous Heuristic Planner.")
        else:
            logger.info("Using Autonomous Heuristic Planner for goal decomposition.")

        return self._generate_heuristic_plan(goal, context)

    async def replan(
        self,
        goal: str,
        original_plan: dict[str, Any],
        failed_step: dict[str, Any],
        observation: dict[str, Any],
        history: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Generate a revised plan when an observation indicates a step failed or unexpected state."""
        tools_description = self.registry.get_tools_prompt_text()
        history_summary = []
        for step in history:
            history_summary.append({
                "step_number": step.get("step_number"),
                "tool": step.get("tool"),
                "action": step.get("action"),
                "status": step.get("status"),
                "error": step.get("error"),
            })

        prompt = f"""You are the master planner for AutoWorker. An error or unexpected condition occurred during plan execution.
You must re-plan the remaining steps to achieve the user's goal despite the obstacle.

### Available Tools:
{tools_description}

### Original User Goal:
{goal}

### Execution History:
{json.dumps(history_summary, indent=2)}

### Failed / Unexpected Step:
{json.dumps(failed_step, indent=2)}

### Observation from Failure:
{json.dumps(observation, indent=2)}

### Original Plan:
{json.dumps(original_plan, indent=2)}

### Instructions:
1. Understand why the step failed and evaluate alternative actions.
2. Provide a new, updated list of remaining steps starting from the next appropriate step number.
3. Output ONLY a valid JSON object matching the standard plan structure.
"""
        if self.api_key and not self.api_key.startswith("your_") and not self.api_key.startswith("AQ."):
            try:
                client = self._get_client()
                response = client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                )
                plan_text = response.text or ""
                return self._clean_json_response(plan_text)
            except Exception as e:
                logger.warning(f"Gemini API re-planning failed: {e}. Falling back to Autonomous Heuristic Re-planner.")
        else:
            logger.info("Using Autonomous Heuristic Re-planner.")

        return self._generate_heuristic_replan(goal, failed_step, observation, history)
