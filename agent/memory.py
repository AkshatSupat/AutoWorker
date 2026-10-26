from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from config.settings import DB_PATH


class AgentMemory:
    """SQLite-backed memory for tracking agent state, execution steps, observations, and context."""

    def __init__(self, db_path: Optional[str | Path] = None):
        self.db_path = Path(db_path) if db_path else Path(DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Initialize database schema tables if they do not exist."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Tasks table
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

            # Steps table
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

            # Observations table
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

            # Context key-value table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS context (
                    task_id TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (task_id, key)
                )
            """)

            conn.commit()

    def create_task(self, goal: str, task_id: Optional[str] = None, understanding: str = "") -> str:
        """Create a new task record and return the task_id."""
        tid = task_id or f"task_{uuid.uuid4().hex[:8]}"
        now = datetime.now().isoformat()
        with self._get_connection() as conn:
            conn.cursor().execute("""
                INSERT OR REPLACE INTO tasks (task_id, goal, status, understanding, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (tid, goal, "in_progress", understanding, now, now))
            conn.commit()
        return tid

    def update_task_status(self, task_id: str, status: str, understanding: Optional[str] = None):
        """Update task status (e.g. 'in_progress', 'completed', 'failed')."""
        now = datetime.now().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if understanding is not None:
                cursor.execute("""
                    UPDATE tasks SET status = ?, understanding = ?, updated_at = ? WHERE task_id = ?
                """, (status, understanding, now, task_id))
            else:
                cursor.execute("""
                    UPDATE tasks SET status = ?, updated_at = ? WHERE task_id = ?
                """, (status, now, task_id))
            conn.commit()

    def get_task_status(self, task_id: str) -> Optional[dict[str, Any]]:
        """Retrieve task details by task_id."""
        with self._get_connection() as conn:
            row = conn.cursor().execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            if row:
                return dict(row)
        return None

    def save_step(self, step_data: dict[str, Any]) -> int:
        """Save an executed or planned step record."""
        now = datetime.now().isoformat()
        task_id = step_data.get("task_id", "default")
        step_number = int(step_data.get("step_number", 0))
        description = step_data.get("description", "")
        tool = step_data.get("tool", "")
        action = step_data.get("action", "")
        params = json.dumps(step_data.get("params", {})) if not isinstance(step_data.get("params"), str) else step_data.get("params", "{}")
        expected = step_data.get("expected_outcome", "")
        approval = 1 if step_data.get("requires_human_approval") else 0
        status = step_data.get("status", "pending")
        output = step_data.get("output", "")
        error = step_data.get("error", "")
        screenshot_path = step_data.get("screenshot_path", "")

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO steps (
                    task_id, step_number, description, tool, action, params,
                    expected_outcome, requires_human_approval, status,
                    output, error, screenshot_path, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                task_id, step_number, description, tool, action, params,
                expected, approval, status, output, error, screenshot_path, now
            ))
            step_id = cursor.lastrowid
            conn.commit()
            return step_id

    def get_history(self, task_id: Optional[str] = None) -> list[dict[str, Any]]:
        """Retrieve execution history for a task, or all tasks if None."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if task_id:
                rows = cursor.execute("""
                    SELECT * FROM steps WHERE task_id = ? ORDER BY id ASC
                """, (task_id,)).fetchall()
            else:
                rows = cursor.execute("SELECT * FROM steps ORDER BY id ASC").fetchall()

            history = []
            for row in rows:
                item = dict(row)
                try:
                    item["params"] = json.loads(item.get("params", "{}"))
                except Exception:
                    pass
                item["requires_human_approval"] = bool(item.get("requires_human_approval"))
                history.append(item)
            return history

    def save_observation(self, observation_data: dict[str, Any]) -> int:
        """Save an observation derived from tool execution."""
        now = datetime.now().isoformat()
        task_id = observation_data.get("task_id", "default")
        step_number = int(observation_data.get("step_number", 0))
        success = 1 if observation_data.get("step_succeeded", True) else 0
        obs_text = observation_data.get("observation", "")
        extracted = json.dumps(observation_data.get("extracted_data", {}))
        next_rec = observation_data.get("next_recommendation", "continue")

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO observations (
                    task_id, step_number, step_succeeded, observation,
                    extracted_data, next_recommendation, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (task_id, step_number, success, obs_text, extracted, next_rec, now))
            obs_id = cursor.lastrowid
            conn.commit()
            return obs_id

    def get_observations(self, task_id: Optional[str] = None) -> list[dict[str, Any]]:
        """Retrieve observations for a task."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if task_id:
                rows = cursor.execute("""
                    SELECT * FROM observations WHERE task_id = ? ORDER BY id ASC
                """, (task_id,)).fetchall()
            else:
                rows = cursor.execute("SELECT * FROM observations ORDER BY id ASC").fetchall()

            result = []
            for row in rows:
                item = dict(row)
                try:
                    item["extracted_data"] = json.loads(item.get("extracted_data", "{}"))
                except Exception:
                    pass
                item["step_succeeded"] = bool(item.get("step_succeeded"))
                result.append(item)
            return result

    def save_context(self, key: str, value: Any, task_id: str = "default"):
        """Save or update a key-value pair in task context."""
        now = datetime.now().isoformat()
        val_str = json.dumps(value) if not isinstance(value, str) else value
        with self._get_connection() as conn:
            conn.cursor().execute("""
                INSERT OR REPLACE INTO context (task_id, key, value, updated_at)
                VALUES (?, ?, ?, ?)
            """, (task_id, key, val_str, now))
            conn.commit()

    def get_context(self, key: Optional[str] = None, task_id: str = "default") -> Any:
        """Get context variable or entire context dictionary if key is None."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if key is not None:
                row = cursor.execute("""
                    SELECT value FROM context WHERE task_id = ? AND key = ?
                """, (task_id, key)).fetchone()
                if row:
                    try:
                        return json.loads(row["value"])
                    except Exception:
                        return row["value"]
                return None
            else:
                rows = cursor.execute("""
                    SELECT key, value FROM context WHERE task_id = ?
                """, (task_id,)).fetchall()
                ctx = {}
                for r in rows:
                    try:
                        ctx[r["key"]] = json.loads(r["value"])
                    except Exception:
                        ctx[r["key"]] = r["value"]
                return ctx

    def clear(self, task_id: Optional[str] = None):
        """Clear memory for a task or entire database."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if task_id:
                cursor.execute("DELETE FROM steps WHERE task_id = ?", (task_id,))
                cursor.execute("DELETE FROM observations WHERE task_id = ?", (task_id,))
                cursor.execute("DELETE FROM context WHERE task_id = ?", (task_id,))
                cursor.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
            else:
                cursor.execute("DELETE FROM steps")
                cursor.execute("DELETE FROM observations")
                cursor.execute("DELETE FROM context")
                cursor.execute("DELETE FROM tasks")
            conn.commit()
