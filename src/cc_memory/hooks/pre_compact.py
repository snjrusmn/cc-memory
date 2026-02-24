"""PreCompact hook — extracts and saves memories before context compaction."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from cc_memory.config import DB_PATH, detect_project
from cc_memory.extractor import Extractor
from cc_memory.storage import Storage


def run(stdin_data: str, db_path: str | None = None) -> dict:
    """Core hook logic. Returns JSON output dict.

    Args:
        stdin_data: JSON string from Claude Code hook system
        db_path: Override DB path (for testing)
    """
    try:
        hook_input = json.loads(stdin_data)
    except json.JSONDecodeError:
        return {"systemMessage": "CC-Memory: invalid hook input"}

    session_id = hook_input.get("session_id", "unknown")
    transcript_path = hook_input.get("transcript_path", "")
    cwd = hook_input.get("cwd", os.getcwd())
    project = detect_project(cwd)

    if not transcript_path or not Path(transcript_path).exists():
        return {"systemMessage": f"CC-Memory: no transcript found at {transcript_path}"}

    # Extract memories from transcript
    extractor = Extractor(transcript_path)
    memories = extractor.extract_all()

    if not memories:
        return {"systemMessage": "CC-Memory: no memories extracted from transcript"}

    # Save to DB
    storage = Storage(db_path or DB_PATH)
    storage.init_db()

    counts: dict[str, int] = {}
    for mem in memories:
        mem_type = mem["type"]
        storage.save(session_id, project, mem_type, mem["content"])
        counts[mem_type] = counts.get(mem_type, 0) + 1

    storage.close()

    # Format summary
    parts = [f"{v} {k}s" for k, v in sorted(counts.items())]
    summary = f"CC-Memory: saved {len(memories)} memories ({', '.join(parts)})"

    return {"systemMessage": summary}


def main():
    """Entry point for cc-memory-pre-compact hook."""
    stdin_data = sys.stdin.read()
    result = run(stdin_data)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
