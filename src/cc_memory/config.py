"""Shared configuration for CC-Memory."""

from __future__ import annotations

import os
from pathlib import Path

DB_PATH = os.environ.get("CC_MEMORY_DB", str(Path.home() / ".cc-memory" / "memories.db"))

_MAX_PROJECT_DEPTH = 10


def detect_project(cwd: str) -> str:
    """Detect project name from cwd (basename of git root or cwd)."""
    path = Path(cwd).resolve()
    for i, parent in enumerate([path, *path.parents]):
        if i >= _MAX_PROJECT_DEPTH:
            break
        if (parent / ".git").exists():
            return parent.name
    return path.name
