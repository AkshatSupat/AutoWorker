"""
AutoWorker End-to-End Automated Test Suite
CentrAlign AI Evaluation Edition
"""

import asyncio
import os
import sys
import unittest
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent.runtime import AgentRuntime
from agent.memory import AgentMemory
from tools.registry import create_default_registry
from mock_company_app.app import load_invoices, load_submissions


class TestAutoWorkerEndToEnd(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Create fresh memory test db
        self.test_db = "test_autoworker.db"
        if os.path.exists(self.test_db):
            os.remove(self.test_db)
        self.memory = AgentMemory(db_path=self.test_db)
        self.registry = create_default_registry(headless=True)
        self.runtime = AgentRuntime(
            registry=self.registry,
            memory=self.memory,
            max_retries=1,
        )
        # Enable auto-approval for test execution
        self.runtime.human_loop.auto_approve = True

    async def asyncTearDown(self):
        await self.registry.close_all()
        if os.path.exists(self.test_db):
            try:
                os.remove(self.test_db)
            except Exception:
                pass

    async def test_full_invoice_extraction_and_submission(self):
        """Test full loop: goal -> plan -> execute -> observe -> verify -> completion."""
        goal = "Find the latest invoice from Acme Corp, extract the amount and due date, enter it into our internal system, and tell me once it is done."
        
        result = await self.runtime.run(goal=goal)

        # Assertions
        self.assertEqual(result.get("status"), "completed", "Task should complete successfully")
        self.assertTrue(result.get("verified"), "Outcome verification must pass")
        self.assertGreaterEqual(result.get("steps_executed", 0), 5, "Expected multiple executed steps")
        
        # Verify extracted context
        ctx = result.get("context", {})
        self.assertIn("Acme Corp", str(ctx.get("company_name", "")))
        self.assertIn("INV-2026-001", str(ctx.get("invoice_number", "")))
        self.assertTrue(bool(ctx.get("submission_id")), "Must capture generated SUB-ID")

        # Verify task is recorded in SQLite
        task_record = self.memory.get_task_status(result["task_id"])
        self.assertIsNotNone(task_record)
        self.assertEqual(task_record["status"], "completed")

    async def test_techvision_invoice_processing(self):
        """Test generalizability across different vendors (TechVision Solutions)."""
        goal = "Find the latest invoice from TechVision Solutions, extract the amount and due date, enter it into our internal system, and tell me once it is done."
        
        result = await self.runtime.run(goal=goal)
        self.assertEqual(result.get("status"), "completed")
        self.assertTrue(result.get("verified"))
        ctx = result.get("context", {})
        self.assertIn("TechVision", str(ctx.get("company_name", "")))
        self.assertIn("INV-2026-002", str(ctx.get("invoice_number", "")))


if __name__ == "__main__":
    unittest.main()
