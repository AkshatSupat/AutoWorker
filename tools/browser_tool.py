from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from tools.base import BaseTool, ToolResult
from config.settings import SCREENSHOT_DIR, BROWSER_HEADLESS

try:
    from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    async_playwright = None
    Browser = Any
    BrowserContext = Any
    Page = Any
    Playwright = Any


class BrowserTool(BaseTool):
    """Playwright-based browser automation tool for web navigation and interaction."""

    def __init__(
        self,
        headless: Optional[bool] = None,
        screenshot_dir: Optional[str | Path] = None,
    ):
        self._headless = BROWSER_HEADLESS if headless is None else headless
        self._screenshot_dir = Path(screenshot_dir) if screenshot_dir else Path(SCREENSHOT_DIR)
        self._screenshot_dir.mkdir(parents=True, exist_ok=True)

        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    @property
    def name(self) -> str:
        return "browser"

    @property
    def description(self) -> str:
        return (
            "Web browser automation tool using Playwright. Can navigate web pages, "
            "interact with elements (click, type), read text/content, wait for selectors, "
            "and take screenshots."
        )

    def get_available_actions(self) -> list[dict]:
        return [
            {
                "action": "navigate",
                "description": "Navigate to a given URL and capture a screenshot.",
                "params": {
                    "url": {"type": "string", "required": True, "description": "The destination URL"}
                },
            },
            {
                "action": "click",
                "description": "Click an element matching the given CSS or text selector.",
                "params": {
                    "selector": {"type": "string", "required": True, "description": "CSS selector or text selector (e.g. 'button#submit' or 'text=Login')"}
                },
            },
            {
                "action": "type_text",
                "description": "Type text into an input field or editable element.",
                "params": {
                    "selector": {"type": "string", "required": True, "description": "Selector for the input field"},
                    "text": {"type": "string", "required": True, "description": "Text to enter into the field"}
                },
            },
            {
                "action": "get_text",
                "description": "Extract visible inner text from an element matching the selector.",
                "params": {
                    "selector": {"type": "string", "required": True, "description": "Selector of the element to read"}
                },
            },
            {
                "action": "get_page_content",
                "description": "Extract text content or HTML structure of the current page.",
                "params": {
                    "selector": {"type": "string", "required": False, "description": "Optional CSS selector to scope content (defaults to 'body')"}
                },
            },
            {
                "action": "wait_for",
                "description": "Wait for a selector to appear on the page.",
                "params": {
                    "selector": {"type": "string", "required": True, "description": "Selector to wait for"},
                    "timeout_ms": {"type": "integer", "required": False, "description": "Timeout in milliseconds (default: 10000)"}
                },
            },
            {
                "action": "screenshot",
                "description": "Capture a screenshot of the current page state.",
                "params": {
                    "path": {"type": "string", "required": False, "description": "Optional custom path for the screenshot file"}
                },
            },
            {
                "action": "select_option",
                "description": "Select an option in a dropdown <select> element by value or text.",
                "params": {
                    "selector": {"type": "string", "required": True, "description": "Selector for the <select> element"},
                    "value": {"type": "string", "required": True, "description": "Option value or visible text to select"}
                },
            },
        ]

    async def _ensure_page(self) -> Page:
        """Lazily initialize Playwright, Browser, and Page if not already active."""
        if not PLAYWRIGHT_AVAILABLE:
            raise RuntimeError(
                "playwright is not installed. Please install it using `pip install playwright` "
                "and `playwright install`."
            )

        if self._playwright is None:
            self._playwright = await async_playwright().start()

        if self._browser is None:
            try:
                self._browser = await self._playwright.chromium.launch(
                    headless=self._headless,
                    args=["--no-sandbox", "--disable-dev-shm-usage"]
                )
            except Exception as e:
                # If browser binaries not installed, re-raise with helpful message
                raise RuntimeError(
                    f"Failed to launch browser: {e}. If browser is missing, run: `playwright install chromium`"
                ) from e

        if self._context is None:
            self._context = await self._browser.new_context(
                viewport={"width": 1280, "height": 800}
            )

        if self._page is None or self._page.is_closed():
            self._page = await self._context.new_page()

        return self._page

    def _generate_screenshot_path(self, prefix: str = "shot") -> str:
        """Generate a timestamped file path for a screenshot."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
        filename = f"{prefix}_{timestamp}.png"
        return str(self._screenshot_dir / filename)

    async def _capture_screenshot(self, page: Page, prefix: str = "shot", explicit_path: Optional[str] = None) -> str:
        """Helper to take a screenshot and return the saved path."""
        try:
            target_path = explicit_path or self._generate_screenshot_path(prefix)
            await page.screenshot(path=target_path, full_page=False)
            return target_path
        except Exception as e:
            # Don't let screenshot failure mask primary action
            return f"Screenshot failed: {e}"

    async def execute(self, action: str, params: dict) -> ToolResult:
        """Execute a browser action safely and return ToolResult."""
        action_clean = action.strip().lower()
        params = params or {}

        try:
            page = await self._ensure_page()
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Browser initialization failed: {str(e)}",
                data={"action": action, "params": params}
            )

        try:
            if action_clean in ("navigate", "goto", "open"):
                url = params.get("url") or params.get("target")
                if not url:
                    return ToolResult(
                        success=False,
                        output="",
                        error="Missing required parameter 'url' for navigate action.",
                        data={"action": action}
                    )
                # Normalize url
                if not (url.startswith("http://") or url.startswith("https://") or url.startswith("file://")):
                    url = "http://" + url

                response = await page.goto(url, wait_until="load", timeout=30000)
                status_code = response.status if response else "unknown"
                title = await page.title()
                shot_path = await self._capture_screenshot(page, prefix="nav")

                return ToolResult(
                    success=True,
                    output=f"Successfully navigated to {url} (Title: '{title}', Status: {status_code})",
                    screenshot_path=shot_path,
                    data={"url": url, "title": title, "status": status_code}
                )

            elif action_clean == "click":
                selector = params.get("selector") or params.get("target")
                if not selector:
                    return ToolResult(
                        success=False,
                        output="",
                        error="Missing required parameter 'selector' for click action.",
                        data={"action": action}
                    )

                # Wait for element and click
                await page.wait_for_selector(selector, state="visible", timeout=10000)
                await page.click(selector)
                # Brief pause for potential state change / DOM update
                await page.wait_for_timeout(500)
                shot_path = await self._capture_screenshot(page, prefix="click")

                return ToolResult(
                    success=True,
                    output=f"Successfully clicked element matching selector '{selector}'.",
                    screenshot_path=shot_path,
                    data={"selector": selector}
                )

            elif action_clean in ("type_text", "type", "input", "fill"):
                selector = params.get("selector") or params.get("target")
                text = params.get("text")
                if text is None:
                    text = params.get("value", "")

                if not selector:
                    return ToolResult(
                        success=False,
                        output="",
                        error="Missing required parameter 'selector' for type_text action.",
                        data={"action": action}
                    )

                await page.wait_for_selector(selector, state="visible", timeout=10000)
                # Check tag name: if select, use select_option instead of fill
                tag = await page.eval_on_selector(selector, "el => el.tagName.toLowerCase()")
                if tag == "select":
                    await page.select_option(selector, str(text))
                    output_msg = f"Successfully selected option '{text}' in dropdown '{selector}'."
                else:
                    await page.fill(selector, str(text))
                    output_msg = f"Successfully typed text into '{selector}'."
                shot_path = await self._capture_screenshot(page, prefix="type")

                return ToolResult(
                    success=True,
                    output=output_msg,
                    screenshot_path=shot_path,
                    data={"selector": selector, "text": str(text)}
                )

            elif action_clean in ("select_option", "select", "choose"):
                selector = params.get("selector") or params.get("target")
                value = str(params.get("value") or params.get("text") or "")
                if not selector:
                    return ToolResult(
                        success=False,
                        output="",
                        error="Missing required parameter 'selector' for select_option action.",
                        data={"action": action}
                    )

                await page.wait_for_selector(selector, state="visible", timeout=10000)
                await page.select_option(selector, value)
                shot_path = await self._capture_screenshot(page, prefix="select")

                return ToolResult(
                    success=True,
                    output=f"Successfully selected option '{value}' in '{selector}'.",
                    screenshot_path=shot_path,
                    data={"selector": selector, "value": value}
                )

            elif action_clean in ("get_text", "read_text", "extract_text"):
                selector = params.get("selector", "body")
                await page.wait_for_selector(selector, timeout=10000)
                element = await page.query_selector(selector)
                if not element:
                    return ToolResult(
                        success=False,
                        output="",
                        error=f"Element with selector '{selector}' was not found.",
                        data={"selector": selector}
                    )
                text = await element.inner_text()
                return ToolResult(
                    success=True,
                    output=text.strip(),
                    data={"selector": selector, "text_length": len(text)}
                )

            elif action_clean in ("get_page_content", "page_content", "content", "get_html"):
                selector = params.get("selector", "body")
                element = await page.query_selector(selector)
                if element:
                    content = await element.inner_text()
                else:
                    content = await page.content()

                # Truncate if very long to prevent token blowout, but preserve key data
                truncated = content[:8000] if len(content) > 8000 else content
                title = await page.title()
                current_url = page.url

                return ToolResult(
                    success=True,
                    output=truncated,
                    data={
                        "url": current_url,
                        "title": title,
                        "full_length": len(content),
                        "truncated": len(content) > 8000,
                    }
                )

            elif action_clean in ("wait_for", "wait"):
                selector = params.get("selector")
                timeout_ms = int(params.get("timeout_ms", params.get("timeout", 10000)))
                if not selector:
                    # Generic sleep if no selector
                    seconds = float(params.get("seconds", 1.0))
                    await page.wait_for_timeout(int(seconds * 1000))
                    return ToolResult(
                        success=True,
                        output=f"Waited for {seconds} seconds.",
                        data={"seconds": seconds}
                    )

                await page.wait_for_selector(selector, timeout=timeout_ms)
                shot_path = await self._capture_screenshot(page, prefix="wait")
                return ToolResult(
                    success=True,
                    output=f"Element '{selector}' is now present on the page.",
                    screenshot_path=shot_path,
                    data={"selector": selector, "timeout_ms": timeout_ms}
                )

            elif action_clean in ("screenshot", "take_screenshot"):
                custom_path = params.get("path")
                shot_path = await self._capture_screenshot(page, prefix="manual", explicit_path=custom_path)
                return ToolResult(
                    success=True,
                    output=f"Screenshot captured at: {shot_path}",
                    screenshot_path=shot_path,
                    data={"path": shot_path}
                )

            else:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Unknown browser action '{action}'. Supported actions: navigate, click, type_text, get_text, get_page_content, wait_for, screenshot.",
                    data={"action": action, "params": params}
                )

        except Exception as e:
            # Capture screenshot on error for debugging
            err_shot = ""
            try:
                err_shot = await self._capture_screenshot(page, prefix="err")
            except Exception:
                pass

            return ToolResult(
                success=False,
                output="",
                error=f"Error executing action '{action}': {str(e)}",
                screenshot_path=err_shot,
                data={"action": action, "params": params, "error_type": type(e).__name__}
            )

    async def close(self):
        """Close browser resources gracefully."""
        try:
            if self._page and not self._page.is_closed():
                await self._page.close()
        except Exception:
            pass

        try:
            if self._context:
                await self._context.close()
        except Exception:
            pass

        try:
            if self._browser:
                await self._browser.close()
        except Exception:
            pass

        try:
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass

        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
