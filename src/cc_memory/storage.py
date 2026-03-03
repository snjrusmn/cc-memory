"""SQLite + FTS5 storage layer for CC-Memory."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Memory:
    """A single memory record."""

    id: int
    session_id: str
    project: str
    type: str
    content: str
    metadata: dict[str, Any] | None
    created_at: str


@dataclass(frozen=True, slots=True)
class MemoryGroup:
    """A group of memories with identical normalized content."""

    content: str
    type: str
    count: int
    memory_ids: list[int]
    first_seen: str
    last_seen: str


VALID_TYPES = frozenset(
    {"decision", "file_change", "task", "learning", "error", "brainstorm"}
)

MAX_LIMIT = 500
MAX_CONTENT_LENGTH = 50_000

# ANSI escape sequences
_ANSI_RE = re.compile(r"\033\[[0-9;]*m")

# Characters/words that need escaping in FTS5 queries
_FTS5_SPECIAL = re.compile(r'["\'\*\(\)\{\}\+\:\^\-\.\\;/]')
_FTS5_KEYWORDS = {"AND", "OR", "NOT", "NEAR"}


def _normalize_content(content: str) -> str:
    """Normalize content for duplicate detection: strip ANSI, collapse whitespace, lowercase."""
    if not content:
        return ""
    # Strip ANSI escape codes
    text = _ANSI_RE.sub("", content)
    # Strip truncation marker
    text = text.replace("... [truncated]", "...")
    # Collapse whitespace
    text = " ".join(text.split())
    # Lowercase
    return text.lower().strip()


def _sanitize_fts_query(query: str) -> str:
    """Escape special FTS5 characters and keywords."""
    if not query or not query.strip():
        return ""
    # Remove special characters
    sanitized = _FTS5_SPECIAL.sub(" ", query)
    # Escape FTS5 keywords by quoting them
    tokens = sanitized.split()
    result = []
    for token in tokens:
        if token.upper() in _FTS5_KEYWORDS:
            result.append(f'"{token}"')
        else:
            result.append(token)
    return " ".join(result)


class Storage:
    """SQLite + FTS5 storage for memories."""

    def __init__(self, db_path: str | Path) -> None:
        if db_path == ":memory:":
            self.conn = sqlite3.connect(":memory:")
        else:
            path = Path(db_path)
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")

    def init_db(self) -> None:
        """Create tables and FTS5 index."""
        types_check = ", ".join(f"'{t}'" for t in sorted(VALID_TYPES))
        self.conn.executescript(f"""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                project TEXT NOT NULL,
                type TEXT NOT NULL CHECK(type IN ({types_check})),
                content TEXT NOT NULL,
                metadata JSON,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                content, project, type,
                content=memories,
                content_rowid=id
            );

            CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                INSERT INTO memories_fts(rowid, content, project, type)
                VALUES (new.id, new.content, new.project, new.type);
            END;

            CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, content, project, type)
                VALUES('delete', old.id, old.content, old.project, old.type);
            END;

            CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, content, project, type)
                VALUES('delete', old.id, old.content, old.project, old.type);
                INSERT INTO memories_fts(rowid, content, project, type)
                VALUES (new.id, new.content, new.project, new.type);
            END;

            CREATE INDEX IF NOT EXISTS idx_memories_project_date ON memories(project, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_memories_session ON memories(session_id);
            CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(type);
        """)

    def save(
        self,
        session_id: str,
        project: str,
        type: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Save a memory and return its id."""
        if type not in VALID_TYPES:
            raise ValueError(f"Invalid type '{type}'. Must be one of: {sorted(VALID_TYPES)}")
        if len(content) > MAX_CONTENT_LENGTH:
            content = content[:MAX_CONTENT_LENGTH] + "... [truncated]"
        meta_json = json.dumps(metadata, ensure_ascii=False) if metadata else None
        cur = self.conn.execute(
            "INSERT INTO memories (session_id, project, type, content, metadata) VALUES (?, ?, ?, ?, ?)",
            (session_id, project, type, content, meta_json),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    @staticmethod
    def _clamp_limit(limit: int) -> int:
        return max(1, min(limit, MAX_LIMIT))

    def search(
        self,
        query: str,
        project: str | None = None,
        type: str | None = None,
        limit: int = 20,
    ) -> list[Memory]:
        """FTS5 full-text search with optional filters."""
        sanitized = _sanitize_fts_query(query)
        if not sanitized:
            return []

        limit = self._clamp_limit(limit)
        conditions = ["memories_fts MATCH ?"]
        params: list[Any] = [sanitized]

        if project:
            conditions.append("m.project = ?")
            params.append(project)
        if type:
            conditions.append("m.type = ?")
            params.append(type)

        where = " AND ".join(conditions)
        params.append(limit)

        try:
            rows = self.conn.execute(
                f"""
                SELECT m.id, m.session_id, m.project, m.type, m.content, m.metadata, m.created_at
                FROM memories m
                JOIN memories_fts ON memories_fts.rowid = m.id
                WHERE {where}
                ORDER BY rank
                LIMIT ?
                """,
                params,
            ).fetchall()
        except sqlite3.OperationalError as e:
            logger.warning("FTS5 query failed: %s (query: %s)", e, sanitized)
            return []
        return [self._row_to_memory(r) for r in rows]

    def recent(self, project: str, limit: int = 20) -> list[Memory]:
        """Get most recent memories for a project."""
        limit = self._clamp_limit(limit)
        rows = self.conn.execute(
            "SELECT * FROM memories WHERE project = ? ORDER BY created_at DESC, id DESC LIMIT ?",
            (project, limit),
        ).fetchall()
        return [self._row_to_memory(r) for r in rows]

    def by_project(
        self, project: str, type: str | None = None, limit: int = 50
    ) -> list[Memory]:
        """Get all memories for a project, optionally filtered by type."""
        limit = self._clamp_limit(limit)
        if type:
            rows = self.conn.execute(
                "SELECT * FROM memories WHERE project = ? AND type = ? ORDER BY created_at DESC, id DESC LIMIT ?",
                (project, type, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM memories WHERE project = ? ORDER BY created_at DESC, id DESC LIMIT ?",
                (project, limit),
            ).fetchall()
        return [self._row_to_memory(r) for r in rows]

    # Per-type limits for balanced retrieval
    _BALANCED_LIMITS: dict[str, int] = {
        "decision": 5,
        "task": 5,
        "file_change": 5,
        "learning": 3,
        "error": 2,
        "brainstorm": 2,
    }

    def recent_balanced(self, project: str) -> list[Memory]:
        """Get recent memories balanced across types — no single type dominates.

        Returns up to ~22 memories with per-type limits:
        5 decisions, 5 tasks, 5 file_changes, 3 learnings, 2 errors, 2 brainstorms.
        """
        result: list[Memory] = []
        for mem_type, limit in self._BALANCED_LIMITS.items():
            rows = self.conn.execute(
                "SELECT * FROM memories WHERE project = ? AND type = ? ORDER BY created_at DESC, id DESC LIMIT ?",
                (project, mem_type, limit),
            ).fetchall()
            result.extend(self._row_to_memory(r) for r in rows)
        return result

    def by_session(self, session_id: str, limit: int = 50) -> list[Memory]:
        """Get all memories for a session."""
        limit = self._clamp_limit(limit)
        rows = self.conn.execute(
            "SELECT * FROM memories WHERE session_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        return [self._row_to_memory(r) for r in rows]

    def group_duplicates(
        self, project: str, type: str | None = None,
    ) -> list[MemoryGroup]:
        """Group memories with identical normalized content."""
        conditions = ["project = ?"]
        params: list[Any] = [project]
        if type:
            conditions.append("type = ?")
            params.append(type)
        where = " AND ".join(conditions)

        rows = self.conn.execute(
            f"SELECT id, type, content, created_at FROM memories WHERE {where} ORDER BY created_at",
            params,
        ).fetchall()

        # Group by normalized content + type
        groups: dict[tuple[str, str], list[tuple[int, str]]] = {}
        for row in rows:
            key = (_normalize_content(row["content"]), row["type"])
            if key not in groups:
                groups[key] = []
            groups[key].append((row["id"], row["created_at"]))

        result = []
        for (norm_content, mem_type), entries in groups.items():
            result.append(MemoryGroup(
                content=norm_content,
                type=mem_type,
                count=len(entries),
                memory_ids=[e[0] for e in entries],
                first_seen=entries[0][1],
                last_seen=entries[-1][1],
            ))
        return result

    def delete_batch(self, memory_ids: list[int]) -> int:
        """Delete multiple memories in a single transaction. Returns count deleted."""
        if not memory_ids:
            return 0
        placeholders = ",".join("?" for _ in memory_ids)
        cur = self.conn.execute(
            f"DELETE FROM memories WHERE id IN ({placeholders})",
            memory_ids,
        )
        self.conn.commit()
        return cur.rowcount

    def count_by_type(self, project: str) -> dict[str, int]:
        """Count memories by type for a project."""
        rows = self.conn.execute(
            "SELECT type, COUNT(*) as cnt FROM memories WHERE project = ? GROUP BY type",
            (project,),
        ).fetchall()
        return {row["type"]: row["cnt"] for row in rows}

    def get_by_ids(self, memory_ids: list[int]) -> list[Memory]:
        """Fetch full Memory objects by their IDs."""
        if not memory_ids:
            return []
        placeholders = ",".join("?" for _ in memory_ids)
        rows = self.conn.execute(
            f"SELECT * FROM memories WHERE id IN ({placeholders})",
            memory_ids,
        ).fetchall()
        return [self._row_to_memory(r) for r in rows]

    def list_projects(self) -> list[str]:
        """List all distinct project names in the database."""
        rows = self.conn.execute(
            "SELECT DISTINCT project FROM memories ORDER BY project"
        ).fetchall()
        return [r["project"] for r in rows]

    def delete(self, memory_id: int) -> bool:
        """Delete a memory by id. Returns True if deleted."""
        cur = self.conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def close(self) -> None:
        """Close the database connection."""
        self.conn.close()

    def __enter__(self) -> Storage:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @staticmethod
    def _row_to_memory(row: sqlite3.Row) -> Memory:
        meta = row["metadata"]
        if meta:
            meta = json.loads(meta)
        return Memory(
            id=row["id"],
            session_id=row["session_id"],
            project=row["project"],
            type=row["type"],
            content=row["content"],
            metadata=meta,
            created_at=row["created_at"],
        )
