#!/usr/bin/env python3
"""
AutoWorker Master Launcher
CentrAlign AI — Engineering Evaluation Edition
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR))


def is_port_in_use(port: int) -> bool:
    """Check if local port is active."""
    try:
        req = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1.0)
        return True
    except Exception:
        return False


def start_mock_server() -> subprocess.Popen:
    """Start CorpFlow Mock Company Portal in background if not already running."""
    if is_port_in_use(5001):
        print("[AutoWorker] CorpFlow Mock Portal is already active on http://localhost:5001")
        return None

    print("[AutoWorker] Starting CorpFlow Mock Enterprise Portal on http://localhost:5001 ...")
    python_exe = sys.executable
    proc = subprocess.Popen(
        [python_exe, "-m", "mock_company_app.app"],
        cwd=str(ROOT_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Wait up to 5 seconds for health check
    for _ in range(10):
        time.sleep(0.5)
        if is_port_in_use(5001):
            print("[AutoWorker] CorpFlow Mock Enterprise Portal is READY.")
            break
    else:
        print("[AutoWorker] Warning: CorpFlow Portal did not respond immediately, continuing...")

    return proc


def run_dashboard():
    """Start AutoWorker Web Dashboard on port 8000."""
    import uvicorn
    from dashboard.server import app

    port = int(os.getenv("PORT", "8000"))
    url = f"http://localhost:{port}"

    print("\n" + "=" * 65)
    print("  AUTOWORKER — AUTONOMOUS AI TASK WORKER")
    print("  CentrAlign AI Engineering Hiring Showcase")
    print("=" * 65)
    print(f"  * Enterprise Dashboard : {url}")
    print(f"  * CorpFlow Mock Portal : http://localhost:5001")
    print(f"  * Documentation        : {url}/#docs")
    print("=" * 65)
    print("  Press Ctrl+C to terminate services.\n")

    # Try opening browser after 1 second
    async def open_browser():
        await asyncio.sleep(1.0)
        try:
            webbrowser.open(url)
        except Exception:
            pass

    # Schedule browser opening
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(open_browser())

    uvicorn.run("dashboard.server:app", host="0.0.0.0", port=port, reload=False)


def run_cli_task(goal: str, headless: bool = False, auto_approve: bool = True):
    """Run AutoWorker in CLI mode."""
    from main import main_async
    sys.argv = [sys.argv[0], goal]
    if headless:
        sys.argv.append("--headless")
    if auto_approve:
        sys.argv.append("--auto-approve")
    asyncio.run(main_async())


def main():
    parser = argparse.ArgumentParser(
        prog="AutoWorker Launcher",
        description="Unified launcher for AutoWorker Dashboard, Mock Enterprise Portal, and CLI Agent.",
    )
    parser.add_argument(
        "--cli",
        "-c",
        type=str,
        default=None,
        help="Run task directly in CLI mode instead of starting dashboard.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run Playwright browser in headless mode (default: visible for live demo).",
    )
    parser.add_argument(
        "--auto-approve",
        action="store_true",
        default=True,
        help="Auto-approve supervisor threshold operations.",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Run end-to-end automated test suite.",
    )
    args = parser.parse_args()

    # Ensure mock company server is running
    mock_proc = start_mock_server()

    try:
        if args.test:
            print("\n[AutoWorker] Running Automated Test Suite...")
            subprocess.run([sys.executable, "test_autoworker.py"], cwd=str(ROOT_DIR), check=True)
        elif args.cli:
            print(f"\n[AutoWorker] Running CLI Task: '{args.cli}'")
            run_cli_task(args.cli, headless=args.headless, auto_approve=args.auto_approve)
        else:
            run_dashboard()
    finally:
        if mock_proc:
            try:
                mock_proc.terminate()
            except Exception:
                pass


if __name__ == "__main__":
    main()
