"""Shared configuration for CC-Memory."""

from __future__ import annotations

import os
from pathlib import Path

DB_PATH = os.environ.get("CC_MEMORY_DB", str(Path.home() / ".cc-memory" / "memories.db"))


def detect_project(cwd: str) -> str:
    """Detect project name from cwd (basename of git root or cwd)."""
    path = Path(cwd)
    for parent in [path, *path.parents]:
        if (parent / ".git").exists():
            return parent.name
    return path.name
