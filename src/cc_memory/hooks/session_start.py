"""SessionStart hook — injects recent project memories on session start."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from cc_memory.config import DB_PATH, detect_project
from cc_memory.storage import Storage


def format_context(project: str, memories: list) -> str:
    """Format memories as structured markdown for Claude context."""
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
        for m in decisions[:10]:
            lines.append(f"- {m.content} ({m.created_at})")
        lines.append("")

    if tasks:
        lines.append("### Active Tasks")
        for m in tasks[:10]:
            lines.append(f"- {m.content}")
        lines.append("")

    if file_changes:
        lines.append("### Recent File Changes")
        for m in file_changes[:10]:
            lines.append(f"- {m.content}")
        lines.append("")

    if learnings:
        lines.append("### Learnings")
        for m in learnings[:5]:
            lines.append(f"- {m.content}")
        lines.append("")

    if errors:
        lines.append("### Recent Errors")
        for m in errors[:5]:
            lines.append(f"- {m.content[:200]}")
        lines.append("")

    return "\n".join(lines)


def run(stdin_data: str, db_path: str | None = None) -> dict:
    """Core hook logic. Returns JSON output dict."""
    try:
        hook_input = json.loads(stdin_data)
    except json.JSONDecodeError:
        return {}

    cwd = hook_input.get("cwd", os.getcwd())
    project = detect_project(cwd)

    effective_db = db_path or DB_PATH
    if not db_path and not Path(effective_db).exists():
        return {}

    try:
        storage = Storage(effective_db)
        storage.init_db()
        memories = storage.recent(project, limit=20)
        storage.close()
    except Exception:
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


def main():
    """Entry point for cc-memory-session-start hook."""
    stdin_data = sys.stdin.read()
    result = run(stdin_data)
    if result:
        print(json.dumps(result))


if __name__ == "__main__":
    main()
