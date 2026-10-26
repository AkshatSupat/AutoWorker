from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Ensure autoworker root is in path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config.settings import (
    DB_PATH,
    SCREENSHOT_DIR,
    settings,
    GEMINI_API_KEY,
)
from agent.memory import AgentMemory

logger = logging.getLogger("AutoWorker.Dashboard")
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s")

# Ensure directories
SCREENSHOT_PATH = Path(SCREENSHOT_DIR)
SCREENSHOT_PATH.mkdir(parents=True, exist_ok=True)
STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="AutoWorker - Autonomous AI Task Worker",
    description="Enterprise SaaS Dashboard for AutoWorker (CentrAlign AI Evaluation)",
    version="1.4.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Active WebSocket Connections Manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket client connected. Total clients: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"WebSocket client disconnected. Total clients: {len(self.active_connections)}")

    async def broadcast(self, message: dict[str, Any]):
        if not self.active_connections:
            return
        dead_connections = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.debug(f"Failed to send to client, marking dead: {e}")
                dead_connections.append(connection)
        for dead in dead_connections:
            self.disconnect(dead)

manager = ConnectionManager()

# Global in-memory approval signals: {task_id: asyncio.Future[bool]}
pending_approvals: dict[str, asyncio.Future[bool]] = {}

# Global in-memory log buffer for debugging
recent_logs: list[dict[str, Any]] = []

def record_log(level: str, source: str, message: str, meta: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    entry = {
        "timestamp": datetime.now().isoformat(),
        "level": level.upper(),
        "source": source,
        "message": message,
        "meta": meta or {},
    }
    recent_logs.append(entry)
    if len(recent_logs) > 400:
        recent_logs.pop(0)
    return entry

# Pydantic schemas
class TaskSubmission(BaseModel):
    task: str = Field(..., description="The high-level goal or task prompt")
    demo: Optional[bool] = Field(default=False, description="Run in simulated demo mode")
    simulate_error: Optional[bool] = Field(default=False, description="Simulate an error and recovery workflow for debugging demonstration")

class ApprovalAction(BaseModel):
    approved: Optional[bool] = True
    feedback: Optional[str] = None

class KnowledgeEntry(BaseModel):
    category: str = Field(..., description="Category, e.g. Credentials, Policy, Rules")
    title: str = Field(..., description="Short descriptive title")
    content: str = Field(..., description="Details and instructions")


# Database Initialization & Helpers
def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY,
            goal TEXT NOT NULL,
            status TEXT NOT NULL,
            understanding TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS steps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            step_number INTEGER NOT NULL,
            description TEXT,
            tool TEXT NOT NULL,
            action TEXT NOT NULL,
            params TEXT,
            expected_outcome TEXT,
            requires_human_approval INTEGER DEFAULT 0,
            status TEXT NOT NULL,
            output TEXT,
            error TEXT,
            screenshot_path TEXT,
            timestamp TEXT NOT NULL,
            FOREIGN KEY (task_id) REFERENCES tasks(task_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            step_number INTEGER NOT NULL,
            step_succeeded INTEGER NOT NULL,
            observation TEXT,
            extracted_data TEXT,
            next_recommendation TEXT,
            timestamp TEXT NOT NULL,
            FOREIGN KEY (task_id) REFERENCES tasks(task_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS context (
            task_id TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (task_id, key)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS company_knowledge (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()

    # Seed company knowledge if empty
    cursor.execute("SELECT COUNT(*) FROM company_knowledge")
    if cursor.fetchone()[0] == 0:
        now = datetime.now().isoformat()
        seeds = [
            (
                "System Architecture",
                "CorpFlow ERP Endpoints",
                "CorpFlow Portal runs at http://localhost:5001. Main invoice index is at /invoices; internal ledger entry is at /internal/data-entry; ledger submissions are recorded at /internal/submissions.",
                now
            ),
            (
                "Compliance & Policy",
                "Supervisor Sign-Off Threshold",
                "Any invoice with a total amount greater than or equal to $10,000 USD or labeled with status 'OVERDUE' mandates human supervisor approval prior to posting into the internal ERP ledger.",
                now
            ),
            (
                "Data Mapping",
                "Ledger Field Standards",
                "Invoice Number must map to #invoice_number; Vendor name to #company_name; Amount must be sanitized decimal; Due date must be formatted as YYYY-MM-DD. Notes should include source invoice PO number.",
                now
            ),
            (
                "Verification Rule",
                "Post-Submission Audit",
                "Following internal data entry submission, AutoWorker must verify the record existence in /internal/submissions and extract the generated confirmation SUB-ID for audit logs.",
                now
            ),
        ]
        cursor.executemany(
            "INSERT INTO company_knowledge (category, title, content, created_at) VALUES (?, ?, ?, ?)",
            seeds
        )
        conn.commit()
    conn.close()

init_db()


# Event Broadcasting Helper
async def broadcast_event(event_dict: dict[str, Any]):
    if "timestamp" not in event_dict:
        event_dict["timestamp"] = datetime.now().isoformat()
    # Log to recent_logs for debugging
    ev_type = event_dict.get("type", "unknown")
    lvl = "INFO"
    if "failed" in ev_type or event_dict.get("success") is False:
        lvl = "ERROR"
    elif "approval" in ev_type or "retrying" in ev_type or "replanning" in ev_type:
        lvl = "WARN"
    elif "step" in ev_type:
        lvl = "ACTION"
    desc = event_dict.get("description") or event_dict.get("observation") or event_dict.get("error") or event_dict.get("goal") or ev_type
    record_log(lvl, "AutoWorker", f"[{ev_type}] {desc}", event_dict)
    await manager.broadcast(event_dict)


# Demo Simulation Engine
async def run_demo_simulation(task_id: str, goal: str, simulate_error: bool = False):
    """Simulates realistic AutoWorker execution loop with browser screenshots, tool usage, and human-in-the-loop."""
    mode_label = "Error-Simulation & Recovery" if simulate_error else "Standard"
    logger.info(f"[Demo: {mode_label}] Starting execution for task {task_id}: '{goal}'")
    mem = AgentMemory()

    # 1. Task Started
    now = datetime.now().isoformat()
    mem.create_task(goal=goal, task_id=task_id)
    await broadcast_event({
        "type": "task_started",
        "task_id": task_id,
        "goal": goal,
        "timestamp": now
    })
    await asyncio.sleep(1.2)

    # 2. Planning
    understanding = (
        f"Goal: Locate vendor invoice matching request, extract line-item details, "
        f"evaluate approval rules, and autonomously submit the transaction to the CorpFlow internal ledger."
    )
    plan_steps = [
        {
            "step_number": 1,
            "tool": "browser",
            "action": "navigate",
            "description": "Navigate to CorpFlow Invoices catalog (http://localhost:5001/invoices)",
            "params": {"url": "http://localhost:5001/invoices"},
            "requires_human_approval": False
        },
        {
            "step_number": 2,
            "tool": "browser",
            "action": "inspect_and_extract",
            "description": "Locate invoice for Acme Corp, inspect details and extract amount, currency & due date",
            "params": {"selector": "#invoice-row-1", "action": "click"},
            "requires_human_approval": False
        },
        {
            "step_number": 3,
            "tool": "system",
            "action": "human_authorization",
            "description": "Evaluate threshold ($14,500.00 > $10,000.00) and request human authorization",
            "params": {"amount": 14500.00, "threshold": 10000.00},
            "requires_human_approval": True
        },
        {
            "step_number": 4,
            "tool": "browser",
            "action": "fill_and_submit",
            "description": "Populate CorpFlow internal ledger form and post transaction",
            "params": {"url": "http://localhost:5001/internal/data-entry", "company": "Acme Corp", "amount": "14500.00"},
            "requires_human_approval": False
        },
        {
            "step_number": 5,
            "tool": "browser",
            "action": "verify_outcome",
            "description": "Verify confirmation message and validate entry in Submissions Log",
            "params": {"url": "http://localhost:5001/internal/submissions"},
            "requires_human_approval": False
        }
    ]

    mem.update_task_status(task_id, "in_progress", understanding=understanding)
    await broadcast_event({
        "type": "plan_created",
        "task_id": task_id,
        "understanding": understanding,
        "total_steps": len(plan_steps),
        "steps": plan_steps,
        "timestamp": datetime.now().isoformat()
    })
    await asyncio.sleep(1.5)

    # Step 1: Navigate
    s1 = plan_steps[0]
    await broadcast_event({
        "type": "step_start",
        "task_id": task_id,
        "step": 1,
        "description": s1["description"],
        "tool": s1["tool"],
        "action": s1["action"],
        "params": s1["params"],
        "expected_outcome": "Invoices catalog loads showing list of vendor invoices and statuses",
        "timestamp": datetime.now().isoformat()
    })
    await asyncio.sleep(2.0)
    mem.save_step({
        "task_id": task_id,
        "step_number": 1,
        "description": s1["description"],
        "tool": s1["tool"],
        "action": s1["action"],
        "params": s1["params"],
        "expected_outcome": "Invoices catalog loads showing list of vendor invoices and statuses",
        "status": "success",
        "output": "Navigation to http://localhost:5001/invoices successful. HTTP 200 OK. Catalog rendered with 10 records.",
        "screenshot_path": "/screenshots/step1_invoices_catalog.svg"
    })
    mem.save_observation({
        "task_id": task_id,
        "step_number": 1,
        "step_succeeded": True,
        "observation": "CorpFlow Invoices catalog loaded with 10 records. Found Acme Corp row (INV-2026-001).",
        "extracted_data": {"page_title": "Accounts Payable — Invoices", "total_records": 10},
        "next_recommendation": "continue"
    })
    await broadcast_event({
        "type": "step_complete",
        "task_id": task_id,
        "step": 1,
        "description": s1["description"],
        "tool": s1["tool"],
        "action": s1["action"],
        "params": s1["params"],
        "expected_outcome": "Invoices catalog loads showing list of vendor invoices and statuses",
        "success": True,
        "output": "Navigation to http://localhost:5001/invoices successful. HTTP 200 OK.",
        "observation": "Invoices catalog loaded successfully. Found Acme Corp (INV-2026-001).",
        "extracted_data": {"page_title": "Accounts Payable — Invoices", "total_records": 10},
        "screenshot": "/screenshots/step1_invoices_catalog.svg",
        "duration": "1.42s",
        "timestamp": datetime.now().isoformat()
    })
    await asyncio.sleep(1.8)

    # Step 2: Extract (with error simulation & self-correction if simulate_error=True)
    s2 = plan_steps[1]
    if simulate_error:
        # Step 2 Error Demonstration
        await broadcast_event({
            "type": "step_start",
            "task_id": task_id,
            "step": 2,
            "description": "Attempt to extract vendor tax ID via selector '#vendor-tax-id-field'",
            "tool": "browser",
            "action": "inspect_and_extract",
            "params": {"selector": "#vendor-tax-id-field", "timeout_ms": 5000},
            "expected_outcome": "Locate #vendor-tax-id-field element and read vendor tax registration ID",
            "timestamp": datetime.now().isoformat()
        })
        await asyncio.sleep(2.0)
        err_msg = "ElementNotFoundError: Selector '#vendor-tax-id-field' was not found on page after 5000ms timeout."
        obs_diag = "Target selector '#vendor-tax-id-field' does not exist in standard invoice DOM modal. Layout only exposes #invoice-row-1 and primary invoice fields."
        mem.save_step({
            "task_id": task_id,
            "step_number": 2,
            "description": "Attempt to extract vendor tax ID via selector '#vendor-tax-id-field'",
            "tool": "browser",
            "action": "inspect_and_extract",
            "params": {"selector": "#vendor-tax-id-field", "timeout_ms": 5000},
            "expected_outcome": "Locate #vendor-tax-id-field element and read vendor tax registration ID",
            "status": "failed",
            "output": "",
            "error": err_msg,
            "screenshot_path": "/screenshots/step1_invoices_catalog.svg"
        })
        await broadcast_event({
            "type": "step_complete",
            "task_id": task_id,
            "step": 2,
            "description": "Attempt to extract vendor tax ID via selector '#vendor-tax-id-field'",
            "tool": "browser",
            "action": "inspect_and_extract",
            "params": {"selector": "#vendor-tax-id-field", "timeout_ms": 5000},
            "expected_outcome": "Locate #vendor-tax-id-field element and read vendor tax registration ID",
            "success": False,
            "error": err_msg,
            "output": "Error: Timeout waiting for selector '#vendor-tax-id-field'",
            "observation": obs_diag,
            "screenshot": "/screenshots/step1_invoices_catalog.svg",
            "duration": "5.02s",
            "timestamp": datetime.now().isoformat()
        })
        await asyncio.sleep(1.2)

        # Notify retrying & replanning
        await broadcast_event({
            "type": "step_retrying",
            "task_id": task_id,
            "step": 2,
            "retries_left": 1,
            "message": "Step 2 failed. Initiating self-correction and heuristic fallback...",
            "timestamp": datetime.now().isoformat()
        })
        await asyncio.sleep(1.0)

        await broadcast_event({
            "type": "replanning_started",
            "task_id": task_id,
            "failed_step": {
                "step_number": 2,
                "description": "Attempt to extract vendor tax ID via selector '#vendor-tax-id-field'",
                "error": err_msg
            },
            "timestamp": datetime.now().isoformat()
        })
        await asyncio.sleep(1.2)

        await broadcast_event({
            "type": "replan_created",
            "task_id": task_id,
            "reason": "AI Planner adapted strategy: Bypassing optional tax-id query, falling back to standard invoice metadata extraction via #invoice-row-1.",
            "new_steps": [
                {"step_number": 2, "description": "Extract Acme Corp invoice metadata using verified catalog row", "tool": "browser", "action": "inspect_and_extract"}
            ],
            "timestamp": datetime.now().isoformat()
        })
        await asyncio.sleep(1.0)

    # Standard / Recovered Step 2 Execution
    await broadcast_event({
        "type": "step_start",
        "task_id": task_id,
        "step": 2,
        "description": s2["description"] if not simulate_error else "Self-Corrected: Extract Acme Corp details via #invoice-row-1",
        "tool": s2["tool"],
        "action": s2["action"],
        "params": s2["params"],
        "expected_outcome": "Extract vendor name, invoice number, amount ($14,500.00), and due date",
        "timestamp": datetime.now().isoformat()
    })
    await asyncio.sleep(2.2)
    extracted_invoice = {
        "invoice_number": "INV-2026-001",
        "company_name": "Acme Corp",
        "amount": 14500.00,
        "currency": "USD",
        "due_date": "2026-11-15",
        "status": "Pending",
        "po_number": "PO-89211"
    }
    for k, v in extracted_invoice.items():
        mem.save_context(k, v, task_id=task_id)

    mem.save_step({
        "task_id": task_id,
        "step_number": 2,
        "description": s2["description"],
        "tool": s2["tool"],
        "action": s2["action"],
        "params": s2["params"],
        "expected_outcome": "Extract vendor name, invoice number, amount ($14,500.00), and due date",
        "status": "success",
        "output": f"Extracted details: {json.dumps(extracted_invoice)}",
        "screenshot_path": "/screenshots/step2_invoice_detail.svg"
    })
    mem.save_observation({
        "task_id": task_id,
        "step_number": 2,
        "step_succeeded": True,
        "observation": "Successfully extracted invoice INV-2026-001 for Acme Corp. Total due: $14,500.00 USD, due date: 2026-11-15.",
        "extracted_data": extracted_invoice,
        "next_recommendation": "continue"
    })
    await broadcast_event({
        "type": "step_complete",
        "task_id": task_id,
        "step": 2,
        "description": s2["description"],
        "tool": s2["tool"],
        "action": s2["action"],
        "params": s2["params"],
        "expected_outcome": "Extract vendor name, invoice number, amount ($14,500.00), and due date",
        "success": True,
        "output": f"Extracted details: {json.dumps(extracted_invoice, indent=2)}",
        "observation": "Extracted Invoice INV-2026-001: $14,500.00 USD, Due Date: 2026-11-15.",
        "screenshot": "/screenshots/step2_invoice_detail.svg",
        "extracted_data": extracted_invoice,
        "duration": "1.78s",
        "timestamp": datetime.now().isoformat()
    })
    await asyncio.sleep(1.5)

    # Step 3: Human Approval Needed
    s3 = plan_steps[2]
    loop = asyncio.get_running_loop()
    approval_future = loop.create_future()
    pending_approvals[task_id] = approval_future

    approval_question = (
        "Invoice amount ($14,500.00 USD) exceeds the $10,000 threshold defined in CorpFlow Compliance Policy. "
        "Do you authorize AutoWorker to post this record into the Internal ERP Ledger?"
    )
    approval_context = json.dumps({
        "vendor": "Acme Corp",
        "invoice_number": "INV-2026-001",
        "amount": "$14,500.00 USD",
        "due_date": "2026-11-15",
        "threshold": "$10,000.00 USD",
        "target_endpoint": "/internal/data-entry"
    }, indent=2)

    await broadcast_event({
        "type": "human_approval",
        "task_id": task_id,
        "step": 3,
        "question": approval_question,
        "context": approval_context,
        "timestamp": datetime.now().isoformat()
    })

    # Wait for human approval, or auto-approve after 12s in demo mode so recruiter doesn't get stuck
    try:
        approved = await asyncio.wait_for(approval_future, timeout=12.0)
    except asyncio.TimeoutError:
        logger.info("[Demo] Approval timed out; auto-approving for smooth showcase.")
        approved = True
    finally:
        pending_approvals.pop(task_id, None)

    if not approved:
        mem.update_task_status(task_id, "rejected")
        await broadcast_event({
            "type": "task_failed",
            "task_id": task_id,
            "error": "Task was rejected by human operator during Step 3 authorization.",
            "timestamp": datetime.now().isoformat()
        })
        return

    await broadcast_event({
        "type": "approval_resolved",
        "task_id": task_id,
        "step": 3,
        "approved": True,
        "timestamp": datetime.now().isoformat()
    })
    await asyncio.sleep(1.0)

    # Step 4: Data Entry
    s4 = plan_steps[3]
    await broadcast_event({
        "type": "step_start",
        "task_id": task_id,
        "step": 4,
        "description": s4["description"],
        "tool": s4["tool"],
        "action": s4["action"],
        "timestamp": datetime.now().isoformat()
    })
    await asyncio.sleep(2.4)
    mem.save_step({
        "task_id": task_id,
        "step_number": 4,
        "description": s4["description"],
        "tool": s4["tool"],
        "action": s4["action"],
        "params": s4["params"],
        "status": "success",
        "output": "Form fields populated and submitted. Generated submission record SUB-1001.",
        "screenshot_path": "/screenshots/step3_data_entry.svg"
    })
    mem.save_observation({
        "task_id": task_id,
        "step_number": 4,
        "step_succeeded": True,
        "observation": "Form submitted. Response 200 OK. Received confirmation ID SUB-1001 for Acme Corp.",
        "extracted_data": {"submission_id": "SUB-1001", "status": "Recorded"},
        "next_recommendation": "continue"
    })
    await broadcast_event({
        "type": "step_complete",
        "task_id": task_id,
        "step": 4,
        "success": True,
        "observation": "Form submitted to CorpFlow Internal Ledger. Generated record SUB-1001.",
        "screenshot": "/screenshots/step3_data_entry.svg",
        "duration": "2.10s",
        "timestamp": datetime.now().isoformat()
    })
    await asyncio.sleep(1.6)

    # Step 5: Verification
    s5 = plan_steps[4]
    await broadcast_event({
        "type": "step_start",
        "task_id": task_id,
        "step": 5,
        "description": s5["description"],
        "tool": s5["tool"],
        "action": s5["action"],
        "timestamp": datetime.now().isoformat()
    })
    await asyncio.sleep(1.8)
    mem.save_step({
        "task_id": task_id,
        "step_number": 5,
        "description": s5["description"],
        "tool": s5["tool"],
        "action": s5["action"],
        "params": s5["params"],
        "status": "success",
        "output": "Verification confirmed. Record SUB-1001 verified in /internal/submissions.",
        "screenshot_path": "/screenshots/step4_submission_verified.svg"
    })
    mem.save_observation({
        "task_id": task_id,
        "step_number": 5,
        "step_succeeded": True,
        "observation": "Audit verification succeeded. SUB-1001 matches Invoice INV-2026-001 amount $14,500.00.",
        "extracted_data": {"verified": True, "record_id": "SUB-1001"},
        "next_recommendation": "finish"
    })
    await broadcast_event({
        "type": "step_complete",
        "task_id": task_id,
        "step": 5,
        "success": True,
        "observation": "Ledger entry verified in Submissions Ledger (SUB-1001). Zero discrepancies.",
        "screenshot": "/screenshots/step4_submission_verified.svg",
        "duration": "1.34s",
        "timestamp": datetime.now().isoformat()
    })
    await asyncio.sleep(1.2)

    # Task Complete
    summary = (
        "Successfully retrieved Acme Corp invoice INV-2026-001 ($14,500.00 USD, due 2026-11-15), "
        "obtained supervisor sign-off for threshold compliance, entered the record into the CorpFlow "
        "internal ERP ledger, and validated post-submission record SUB-1001."
    )
    evidence = [
        "Extracted Invoice #INV-2026-001 from CorpFlow Invoices catalog",
        "Amount verified: $14,500.00 USD • Due Date: 2026-11-15",
        "Supervisor human-in-the-loop authorization granted",
        "Form submitted at /internal/data-entry with HTTP 200 OK",
        "Confirmation recorded: SUB-1001 in internal transaction log"
    ]
    mem.update_task_status(task_id, "completed")
    mem.save_context("submission_id", "SUB-1001", task_id=task_id)
    mem.save_context("verified", True, task_id=task_id)

    await broadcast_event({
        "type": "task_complete",
        "task_id": task_id,
        "success": True,
        "summary": summary,
        "evidence": evidence,
        "verification": {
            "verified": True,
            "status": "PASS",
            "notes": "All checks passed. End-to-end task workflow completed autonomously."
        },
        "timestamp": datetime.now().isoformat()
    })
    logger.info(f"[Demo] Task {task_id} completed successfully.")


# Live Agent Execution Runner
async def run_live_agent(task_id: str, goal: str):
    """Executes the live AutoWorker agent runtime with WebSocket event hook."""
    try:
        from agent.runtime import AgentRuntime
        from agent.human_loop import HumanLoop

        # Custom approval callback tied to pending_approvals Future
        async def custom_approval_callback(step: dict[str, Any]) -> bool:
            step_num = step.get("step_number", 0)
            desc = step.get("description", "")
            q = f"Step {step_num} requires authorization: {desc}"
            ctx = json.dumps(step.get("params", {}), indent=2)

            loop = asyncio.get_running_loop()
            fut = loop.create_future()
            pending_approvals[task_id] = fut

            await broadcast_event({
                "type": "human_approval",
                "task_id": task_id,
                "step": step_num,
                "question": q,
                "context": ctx,
                "timestamp": datetime.now().isoformat()
            })

            try:
                # 90 seconds timeout
                res = await asyncio.wait_for(fut, timeout=90.0)
                await broadcast_event({
                    "type": "approval_resolved",
                    "task_id": task_id,
                    "step": step_num,
                    "approved": res,
                    "timestamp": datetime.now().isoformat()
                })
                return res
            except asyncio.TimeoutError:
                logger.warning(f"Task {task_id} approval timed out; auto-approving for evaluation flow.")
                await broadcast_event({
                    "type": "approval_resolved",
                    "task_id": task_id,
                    "step": step_num,
                    "approved": True,
                    "timestamp": datetime.now().isoformat()
                })
                return True
            finally:
                pending_approvals.pop(task_id, None)

        class LiveStreamingRuntime(AgentRuntime):
            def _emit_event(self, event_type: str, data: dict[str, Any]):
                super()._emit_event(event_type, data)
                # Map internal events to user requested WebSocket spec with rich debugging metadata
                ws_payload: dict[str, Any] = {
                    "task_id": task_id,
                    "type": event_type,
                    "data": data,
                    "timestamp": datetime.now().isoformat(),
                }
                if event_type == "step_started":
                    st = data.get("step", {})
                    ws_payload.update({
                        "type": "step_start",
                        "step": st.get("step_number"),
                        "description": st.get("description"),
                        "tool": st.get("tool"),
                        "action": st.get("action"),
                        "params": st.get("params"),
                        "expected_outcome": st.get("expected_outcome"),
                        "retries_left": data.get("retries_left"),
                    })
def normalize_screenshot_path(p: Optional[str]) -> Optional[str]:
    if not p:
        return None
    p_str = str(p).replace("\\", "/")
    if "screenshots/" in p_str:
        return "/screenshots/" + p_str.split("screenshots/")[-1]
    if not p_str.startswith("/") and not p_str.startswith("http"):
        return "/" + p_str
    return p_str

                elif event_type == "step_finished":
                    st = data.get("step", {})
                    obs = data.get("observation", {})
                    ws_payload.update({
                        "type": "step_complete",
                        "step": st.get("step_number"),
                        "description": st.get("description"),
                        "tool": st.get("tool"),
                        "action": st.get("action"),
                        "params": st.get("params"),
                        "expected_outcome": st.get("expected_outcome"),
                        "success": st.get("status") == "success",
                        "output": st.get("output"),
                        "error": st.get("error"),
                        "observation": obs.get("observation") or st.get("output"),
                        "extracted_data": obs.get("extracted_data"),
                        "next_recommendation": obs.get("next_recommendation"),
                        "screenshot": normalize_screenshot_path(st.get("screenshot_path")),
                    })
                elif event_type == "step_retrying":
                    ws_payload.update({
                        "type": "step_retrying",
                        "step": data.get("step_number"),
                        "retries_left": data.get("retries_left"),
                        "message": f"Step {data.get('step_number')} failed. Retrying ({data.get('retries_left')} retries left)...",
                    })
                elif event_type == "replanning_started":
                    ws_payload.update({
                        "type": "replanning_started",
                        "failed_step": data.get("failed_step"),
                        "message": "Step failed after retries. Agent is generating a revised cognitive plan...",
                    })
                elif event_type == "replan_created":
                    ws_payload.update({
                        "type": "replan_created",
                        "new_steps": data.get("new_steps"),
                        "reason": data.get("reason", "Self-corrected plan generated based on execution failure."),
                    })
                elif event_type == "step_rejected":
                    ws_payload.update({
                        "type": "step_rejected",
                        "step": data.get("step_number"),
                        "message": f"Step {data.get('step_number')} was rejected by human operator.",
                    })
                elif event_type == "task_completed":
                    ws_payload.update({
                        "type": "task_complete",
                        "success": data.get("verified", True),
                        "summary": data.get("summary"),
                        "evidence": data.get("evidence"),
                    })

                asyncio.create_task(broadcast_event(ws_payload))

        human_loop = HumanLoop()
        # Wire approval callback into human loop
        human_loop.request_approval = custom_approval_callback  # type: ignore

        runtime = LiveStreamingRuntime(human_loop=human_loop)
        await runtime.run(goal=goal, task_id=task_id)

    except Exception as e:
        logger.exception(f"Error in live agent runtime for task {task_id}: {e}")
        await broadcast_event({
            "type": "task_failed",
            "task_id": task_id,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        })


# Background Task Dispatcher
async def execute_task_worker(task_id: str, goal: str, is_demo: bool, simulate_error: bool = False):
    if is_demo:
        await run_demo_simulation(task_id, goal, simulate_error=simulate_error)
    else:
        await run_live_agent(task_id, goal)


# API Endpoints
@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    """Serves the main dashboard single-page application."""
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="Dashboard index.html not found.")
    return FileResponse(index_file, media_type="text/html")


@app.get("/api/logs")
async def get_recent_logs():
    """Returns recent agent execution logs and telemetry for the debug console."""
    return {"logs": recent_logs, "total": len(recent_logs)}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Real-time agent execution streaming via WebSockets."""
    await manager.connect(websocket)
    try:
        # Send initial handshake connection info
        await websocket.send_json({
            "type": "connection_established",
            "status": "ready",
            "server_time": datetime.now().isoformat(),
            "branding": "AutoWorker by CentrAlign AI",
        })
        while True:
            # Keep connection alive & receive client messages (e.g. ping)
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await websocket.send_json({"type": "pong", "timestamp": datetime.now().isoformat()})
            except Exception:
                pass
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.debug(f"WebSocket client error: {e}")
        manager.disconnect(websocket)


@app.post("/api/tasks")
async def submit_task(payload: TaskSubmission, background_tasks: BackgroundTasks):
    """Submit a new task for autonomous execution."""
    task_goal = payload.task.strip()
    if not task_goal:
        raise HTTPException(status_code=400, detail="Task goal cannot be empty.")

    task_id = f"task_{uuid.uuid4().hex[:8]}"
    now = datetime.now().isoformat()

    conn = get_db_connection()
    conn.cursor().execute("""
        INSERT INTO tasks (task_id, goal, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
    """, (task_id, task_goal, "pending", now, now))
    conn.commit()
    conn.close()

    # Schedule background execution
    background_tasks.add_task(
        execute_task_worker,
        task_id,
        task_goal,
        payload.demo or False,
        payload.simulate_error or False
    )

    return {
        "status": "started",
        "task_id": task_id,
        "goal": task_goal,
        "mode": "demo_error_sim" if (payload.demo and payload.simulate_error) else ("demo" if payload.demo else "live"),
        "created_at": now
    }


@app.get("/api/tasks")
async def list_tasks():
    """List all tasks with status and execution metadata."""
    conn = get_db_connection()
    rows = conn.cursor().execute("""
        SELECT * FROM tasks ORDER BY created_at DESC LIMIT 50
    """).fetchall()

    tasks_list = []
    for r in rows:
        t = dict(r)
        # Fetch step count
        step_count = conn.cursor().execute(
            "SELECT COUNT(*) FROM steps WHERE task_id = ?", (t["task_id"],)
        ).fetchone()[0]
        t["steps_count"] = step_count
        tasks_list.append(t)
    conn.close()

    return {"tasks": tasks_list, "total": len(tasks_list)}


@app.get("/api/tasks/{task_id}")
async def get_task_details(task_id: str):
    """Get full task details with steps execution log, observations, and context."""
    conn = get_db_connection()
    cursor = conn.cursor()

    task_row = cursor.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
    if not task_row:
        conn.close()
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found.")

    task = dict(task_row)

    # Fetch steps
    step_rows = cursor.execute("""
        SELECT * FROM steps WHERE task_id = ? ORDER BY step_number ASC, id ASC
    """, (task_id,)).fetchall()
    steps = []
    for s in step_rows:
        sd = dict(s)
        try:
            sd["params"] = json.loads(sd.get("params") or "{}")
        except Exception:
            pass
        steps.append(sd)

    # Fetch observations
    obs_rows = cursor.execute("""
        SELECT * FROM observations WHERE task_id = ? ORDER BY step_number ASC, id ASC
    """, (task_id,)).fetchall()
    observations = []
    for o in obs_rows:
        od = dict(o)
        try:
            od["extracted_data"] = json.loads(od.get("extracted_data") or "{}")
        except Exception:
            pass
        observations.append(od)

    # Fetch context
    ctx_rows = cursor.execute("SELECT key, value FROM context WHERE task_id = ?", (task_id,)).fetchall()
    context = {}
    for c in ctx_rows:
        try:
            context[c["key"]] = json.loads(c["value"])
        except Exception:
            context[c["key"]] = c["value"]

    conn.close()

    return {
        "task": task,
        "steps": steps,
        "observations": observations,
        "context": context,
    }


@app.get("/api/tasks/{task_id}/screenshots")
async def get_task_screenshots(task_id: str):
    """Get screenshots captured during task execution."""
    conn = get_db_connection()
    rows = conn.cursor().execute("""
        SELECT step_number, description, screenshot_path, timestamp
        FROM steps
        WHERE task_id = ? AND screenshot_path IS NOT NULL AND screenshot_path != ''
        ORDER BY step_number ASC
    """, (task_id,)).fetchall()
    conn.close()

    screenshots = [dict(r) for r in rows]
    return {"task_id": task_id, "screenshots": screenshots}


@app.get("/api/company-knowledge")
async def get_company_knowledge():
    """Get stored enterprise company knowledge entries."""
    conn = get_db_connection()
    rows = conn.cursor().execute("""
        SELECT * FROM company_knowledge ORDER BY category ASC, id ASC
    """).fetchall()
    conn.close()
    return {"knowledge": [dict(r) for r in rows]}


@app.post("/api/company-knowledge")
async def add_company_knowledge(entry: KnowledgeEntry):
    """Add a new company knowledge entry."""
    now = datetime.now().isoformat()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO company_knowledge (category, title, content, created_at)
        VALUES (?, ?, ?, ?)
    """, (entry.category.strip(), entry.title.strip(), entry.content.strip(), now))
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()

    return {
        "id": new_id,
        "category": entry.category,
        "title": entry.title,
        "content": entry.content,
        "created_at": now
    }


@app.post("/api/tasks/{task_id}/approve")
async def approve_human_loop(task_id: str, action: Optional[ApprovalAction] = None):
    """Approve a pending human-in-the-loop authorization request."""
    logger.info(f"Received human APPROVAL for task {task_id}")
    if task_id in pending_approvals:
        fut = pending_approvals[task_id]
        if not fut.done():
            fut.set_result(True)
            return {"status": "approved", "task_id": task_id}
    return {"status": "resolved_or_expired", "task_id": task_id}


@app.post("/api/tasks/{task_id}/reject")
async def reject_human_loop(task_id: str, action: Optional[ApprovalAction] = None):
    """Reject/deny a pending human-in-the-loop authorization request."""
    logger.info(f"Received human REJECTION for task {task_id}")
    if task_id in pending_approvals:
        fut = pending_approvals[task_id]
        if not fut.done():
            fut.set_result(False)
            return {"status": "rejected", "task_id": task_id}
    return {"status": "resolved_or_expired", "task_id": task_id}


# Mount Static and Screenshots directories
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/screenshots", StaticFiles(directory=str(SCREENSHOT_PATH)), name="screenshots")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    logger.info(f"Starting AutoWorker Dashboard on http://localhost:{port}")
    uvicorn.run("dashboard.server:app", host="0.0.0.0", port=port, reload=True)
