"""UserPromptSubmit hook — tracks prompts, auto-saves decision/task keywords."""

from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

from cc_memory.config import DB_PATH, detect_project
from cc_memory.storage import Storage

# Sanitize session_id: allow only alphanumeric, dash, underscore
_SAFE_ID_RE = re.compile(r"[^a-zA-Z0-9_-]")

# Keywords that indicate a decision or task in user prompt
DECISION_PATTERNS = [
    re.compile(r"\b(?:решил[иа]?|decided|chose|выбрал[иа]?)\b", re.IGNORECASE),
    re.compile(r"\b(?:давай|let'?s use|будем использовать)\b", re.IGNORECASE),
]

TASK_PATTERNS = [
    re.compile(r"\b(?:TODO|FIXME|NEXT)\b[:]\s*", re.IGNORECASE),
    re.compile(r"\b(?:нужно|надо|необходимо|сделай|добавь)\b", re.IGNORECASE),
]

SAVE_EVERY_N = 10


def _counter_dir() -> Path:
    """Per-user temp directory for counter files."""
    base = Path(tempfile.gettempdir()) / "cc-memory"
    base.mkdir(mode=0o700, exist_ok=True)
    return base


def _counter_path(session_id: str) -> Path:
    """Path to prompt counter file for this session (sanitized)."""
    safe_id = _SAFE_ID_RE.sub("_", session_id)[:128]
    path = _counter_dir() / f"{safe_id}.count"
    # Verify resolved path stays within counter dir
    if not str(path.resolve()).startswith(str(_counter_dir().resolve())):
        return _counter_dir() / "invalid.count"
    return path


def get_counter(session_id: str) -> int:
    """Get current prompt count for session."""
    p = _counter_path(session_id)
    if p.exists():
        try:
            return int(p.read_text().strip())
        except (ValueError, OSError):
            return 0
    return 0


def increment_counter(session_id: str) -> int:
    """Increment and return new prompt count."""
    count = get_counter(session_id) + 1
    try:
        _counter_path(session_id).write_text(str(count))
    except OSError:
        pass
    return count


def detect_keywords(prompt: str) -> list[dict[str, str]]:
    """Detect decision/task keywords in user prompt."""
    results = []
    for pattern in DECISION_PATTERNS:
        if pattern.search(prompt):
            results.append({"type": "decision", "content": f"User decision: {prompt[:300]}"})
            break

    for pattern in TASK_PATTERNS:
        if pattern.search(prompt):
            results.append({"type": "task", "content": f"User task: {prompt[:300]}"})
            break

    return results


def run(stdin_data: str, db_path: str | None = None) -> dict:
    """Core hook logic. Returns JSON output dict (non-blocking)."""
    try:
        hook_input = json.loads(stdin_data)
    except json.JSONDecodeError:
        return {}

    session_id = hook_input.get("session_id", "unknown")
    prompt = hook_input.get("prompt", "")
    cwd = hook_input.get("cwd")
    if not cwd:
        return {}
    project = detect_project(cwd)

    if not prompt:
        return {}

    count = increment_counter(session_id)

    # Detect keywords in prompt
    memories = detect_keywords(prompt)

    # Every N prompts, save a breadcrumb
    if count % SAVE_EVERY_N == 0 and not memories:
        memories.append({
            "type": "learning",
            "content": f"Session checkpoint: {count} prompts processed",
        })

    if memories:
        effective_db = db_path or DB_PATH
        try:
            with Storage(effective_db) as storage:
                storage.init_db()
                for mem in memories:
                    storage.save(session_id, project, mem["type"], mem["content"])
        except Exception as e:
            print(f"CC-Memory warning: {e}", file=sys.stderr)

    # Non-blocking: no additionalContext needed
    return {}


def main() -> None:
    """Entry point for cc-memory-user-prompt hook."""
    stdin_data = sys.stdin.read()
    result = run(stdin_data)
    if result:
        print(json.dumps(result))


if __name__ == "__main__":
    main()
