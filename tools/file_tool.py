from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from tools.base import BaseTool, ToolResult
from config.settings import PROJECT_ROOT


class FileTool(BaseTool):
    """File operations tool for reading, writing, listing, and searching files."""

    def __init__(self, base_dir: Optional[str | Path] = None):
        self._base_dir = Path(base_dir).resolve() if base_dir else PROJECT_ROOT.resolve()

    @property
    def name(self) -> str:
        return "file"

    @property
    def description(self) -> str:
        return (
            "File operations tool for local file management. Can read files, write or append "
            "to files, list directory contents, and search for specific text within files."
        )

    def get_available_actions(self) -> list[dict]:
        return [
            {
                "action": "read_file",
                "description": "Read the contents of a file.",
                "params": {
                    "path": {"type": "string", "required": True, "description": "Path to the file to read"}
                },
            },
            {
                "action": "write_file",
                "description": "Write or append text content to a file. Automatically creates parent directories.",
                "params": {
                    "path": {"type": "string", "required": True, "description": "Target file path"},
                    "content": {"type": "string", "required": True, "description": "Text content to write"},
                    "append": {"type": "boolean", "required": False, "description": "Whether to append instead of overwrite (default: False)"}
                },
            },
            {
                "action": "list_files",
                "description": "List files and directories inside a given directory path.",
                "params": {
                    "directory": {"type": "string", "required": False, "description": "Directory path to list (default: project root)"},
                    "pattern": {"type": "string", "required": False, "description": "Optional glob pattern, e.g. '*.json'"}
                },
            },
            {
                "action": "search_in_file",
                "description": "Search for a query string in a file and return matching lines.",
                "params": {
                    "path": {"type": "string", "required": True, "description": "Path to the file to search in"},
                    "query": {"type": "string", "required": True, "description": "Text query or keyword to find"}
                },
            },
        ]

    def _resolve_path(self, target_path: str) -> Path:
        """Resolve a relative or absolute path."""
        p = Path(target_path)
        if not p.is_absolute():
            p = (self._base_dir / p).resolve()
        return p

    async def execute(self, action: str, params: dict) -> ToolResult:
        """Execute a file action asynchronously."""
        action_clean = action.strip().lower()
        params = params or {}

        try:
            if action_clean in ("read_file", "read", "cat"):
                raw_path = params.get("path") or params.get("filepath")
                if not raw_path:
                    return ToolResult(
                        success=False,
                        output="",
                        error="Missing required parameter 'path' for read_file action.",
                        data={"action": action}
                    )

                path = self._resolve_path(raw_path)
                if not path.exists():
                    return ToolResult(
                        success=False,
                        output="",
                        error=f"File not found: {path}",
                        data={"path": str(path)}
                    )

                if not path.is_file():
                    return ToolResult(
                        success=False,
                        output="",
                        error=f"Path is not a regular file: {path}",
                        data={"path": str(path)}
                    )

                content = path.read_text(encoding="utf-8", errors="replace")
                return ToolResult(
                    success=True,
                    output=content,
                    data={"path": str(path), "size_bytes": path.stat().st_size}
                )

            elif action_clean in ("write_file", "write", "save"):
                raw_path = params.get("path") or params.get("filepath")
                content = params.get("content", "")
                append = bool(params.get("append", False))

                if not raw_path:
                    return ToolResult(
                        success=False,
                        output="",
                        error="Missing required parameter 'path' for write_file action.",
                        data={"action": action}
                    )

                path = self._resolve_path(raw_path)
                path.parent.mkdir(parents=True, exist_ok=True)

                mode = "a" if append else "w"
                with open(path, mode, encoding="utf-8") as f:
                    f.write(str(content))

                return ToolResult(
                    success=True,
                    output=f"Successfully {'appended to' if append else 'wrote'} file: {path} ({len(str(content))} chars)",
                    data={"path": str(path), "appended": append, "bytes_written": len(str(content))}
                )

            elif action_clean in ("list_files", "list", "ls", "dir"):
                raw_dir = params.get("directory", ".")
                pattern = params.get("pattern", "*")
                dir_path = self._resolve_path(raw_dir)

                if not dir_path.exists():
                    return ToolResult(
                        success=False,
                        output="",
                        error=f"Directory not found: {dir_path}",
                        data={"directory": str(dir_path)}
                    )

                if not dir_path.is_dir():
                    return ToolResult(
                        success=False,
                        output="",
                        error=f"Path is not a directory: {dir_path}",
                        data={"directory": str(dir_path)}
                    )

                items = []
                for p in sorted(dir_path.glob(pattern)):
                    items.append({
                        "name": p.name,
                        "type": "directory" if p.is_dir() else "file",
                        "size": p.stat().st_size if p.is_file() else None,
                        "path": str(p),
                    })

                summary_lines = [f"{'[DIR] ' if i['type']=='directory' else '[FILE]'} {i['name']} ({i['size'] or '-'} bytes)" for i in items]
                output = "\n".join(summary_lines) if summary_lines else "Directory is empty or no files match pattern."

                return ToolResult(
                    success=True,
                    output=output,
                    data={"directory": str(dir_path), "total_items": len(items), "items": items}
                )

            elif action_clean in ("search_in_file", "search", "grep"):
                raw_path = params.get("path") or params.get("filepath")
                query = params.get("query", "")

                if not raw_path or not query:
                    return ToolResult(
                        success=False,
                        output="",
                        error="Missing 'path' or 'query' parameter for search_in_file.",
                        data={"action": action}
                    )

                path = self._resolve_path(raw_path)
                if not path.exists() or not path.is_file():
                    return ToolResult(
                        success=False,
                        output="",
                        error=f"File not found: {path}",
                        data={"path": str(path)}
                    )

                matching_lines = []
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    for line_no, line in enumerate(f, start=1):
                        if query.lower() in line.lower():
                            matching_lines.append(f"Line {line_no}: {line.strip()}")

                if matching_lines:
                    output = "\n".join(matching_lines)
                    return ToolResult(
                        success=True,
                        output=output,
                        data={"path": str(path), "matches_found": len(matching_lines)}
                    )
                else:
                    return ToolResult(
                        success=True,
                        output=f"No occurrences of '{query}' found in {path.name}.",
                        data={"path": str(path), "matches_found": 0}
                    )

            else:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Unknown file action '{action}'. Supported actions: read_file, write_file, list_files, search_in_file.",
                    data={"action": action, "params": params}
                )

        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Error executing file action '{action}': {str(e)}",
                data={"action": action, "params": params}
            )
