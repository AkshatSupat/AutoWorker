from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Add project root to sys.path so modules import reliably
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config.settings import settings
from tools.registry import create_default_registry
from agent.memory import AgentMemory
from agent.planner import Planner
from agent.executor import StepExecutor
from agent.observer import ResultObserver
from agent.verifier import OutcomeVerifier
from agent.human_loop import HumanLoop
from agent.runtime import AgentRuntime, setup_logger


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="AutoWorker",
        description="Autonomous AI task worker powered by Google Gemini and Playwright.",
    )
    parser.add_argument(
        "task",
        nargs="?",
        default=None,
        help="The high-level goal or task to execute.",
    )
    parser.add_argument(
        "--goal",
        "-g",
        type=str,
        default=None,
        help="Alternative flag to specify the goal.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=settings.browser_headless,
        help="Run browser in headless mode (default: False for live demo).",
    )
    parser.add_argument(
        "--auto-approve",
        action="store_true",
        default=False,
        help="Automatically approve steps that require human consent (useful for testing).",
    )
    parser.add_argument(
        "--db",
        type=str,
        default=None,
        help="Custom path for SQLite database file.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=settings.gemini_model,
        help="Gemini model name to use (default: gemini-2.0-flash).",
    )
    return parser.parse_args()


async def main_async():
    args = parse_arguments()
    logger = setup_logger()

    goal = args.task or args.goal
    if not goal:
        print("\n=== AutoWorker: Autonomous AI Task Worker ===")
        try:
            goal = input("Enter the goal/task for AutoWorker: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            sys.exit(0)

    if not goal:
        logger.error("No task provided. Please supply a task description.")
        sys.exit(1)

    # Check for GEMINI_API_KEY
    api_key = settings.gemini_api_key or os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.warning(
            "GEMINI_API_KEY is not set in environment or .env file! "
            "Please ensure your .env file contains: GEMINI_API_KEY=your_key"
        )

    # Initialize components
    registry = create_default_registry(headless=args.headless)
    memory = AgentMemory(db_path=args.db)
    planner = Planner(registry=registry, api_key=api_key, model_name=args.model)
    executor = StepExecutor(registry=registry)
    observer = ResultObserver(api_key=api_key, model_name=args.model)
    verifier = OutcomeVerifier(api_key=api_key, model_name=args.model)
    human_loop = HumanLoop(auto_approve=args.auto_approve)

    runtime = AgentRuntime(
        registry=registry,
        memory=memory,
        planner=planner,
        executor=executor,
        observer=observer,
        verifier=verifier,
        human_loop=human_loop,
        max_retries=settings.max_retries,
    )

    # Run orchestrator
    result = await runtime.run(goal=goal)

    # Print summary
    print("\n" + "=" * 60)
    print(" TASK EXECUTION SUMMARY")
    print("=" * 60)
    print(f" Task ID        : {result.get('task_id')}")
    print(f" Status         : {result.get('status').upper()}")
    print(f" Verified       : {result.get('verified')}")
    print(f" Steps Executed : {result.get('steps_executed')}")
    print(f" Evidence       :\n   {result.get('evidence')}")
    print(f" Summary        :\n   {result.get('summary')}")
    if result.get("context"):
        print(f" Final Context  :\n   {result.get('context')}")
    print("=" * 60 + "\n")

    return 0 if result.get("verified") else 1


def main():
    try:
        exit_code = asyncio.run(main_async())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n[AutoWorker] Execution interrupted by user.")
        sys.exit(130)


if __name__ == "__main__":
    main()
