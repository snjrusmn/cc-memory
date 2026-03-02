"""SessionStart hook — injects recent project memories on session start."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from cc_memory.config import DB_PATH, detect_project
from cc_memory.storage import Memory, Storage


def format_context(project: str, memories: list[Memory]) -> str:
    """Format memories as structured markdown for Claude context.

    Renders all received memories grouped by type.
    Per-type limits are enforced at query level (recent_balanced), not here.
    """
    if not memories:
        return ""

    decisions = [m for m in memories if m.type == "decision"]
    tasks = [m for m in memories if m.type == "task"]
    file_changes = [m for m in memories if m.type == "file_change"]
    learnings = [m for m in memories if m.type == "learning"]
    errors = [m for m in memories if m.type == "error"]

    last_date = memories[0].created_at if memories else "unknown"

    lines = [
        f"## CC-Memory Context",
        f"**Project:** {project} | **Memories:** {len(memories)} | **Last session:** {last_date}",
        "",
    ]

    if decisions:
        lines.append("### Recent Decisions")
        for m in decisions:
            lines.append(f"- {m.content} ({m.created_at})")
        lines.append("")

    if tasks:
        lines.append("### Active Tasks")
        for m in tasks:
            lines.append(f"- {m.content}")
        lines.append("")

    if file_changes:
        lines.append("### Recent File Changes")
        for m in file_changes:
            lines.append(f"- {m.content}")
        lines.append("")

    if learnings:
        lines.append("### Learnings")
        for m in learnings:
            lines.append(f"- {m.content}")
        lines.append("")

    if errors:
        lines.append("### Recent Errors")
        for m in errors:
            lines.append(f"- {m.content[:200]}")
        lines.append("")

    return "\n".join(lines)


def run(stdin_data: str, db_path: str | None = None) -> dict:
    """Core hook logic. Returns JSON output dict."""
    try:
        hook_input = json.loads(stdin_data)
    except json.JSONDecodeError:
        return {}

    cwd = hook_input.get("cwd")
    if not cwd:
        return {}
    project = detect_project(cwd)

    # Skip if no DB exists yet (first run, no memories saved yet)
    if db_path is None and not Path(DB_PATH).exists():
        return {}
    effective_db = db_path or DB_PATH

    try:
        with Storage(effective_db) as storage:
            storage.init_db()
            memories = storage.recent_balanced(project)
    except Exception as e:
        print(f"CC-Memory warning: {e}", file=sys.stderr)
        return {}

    if not memories:
        return {}

    context = format_context(project, memories)
    return {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }


def main() -> None:
    """Entry point for cc-memory-session-start hook."""
    stdin_data = sys.stdin.read()
    result = run(stdin_data)
    if result:
        print(json.dumps(result))


if __name__ == "__main__":
    main()
