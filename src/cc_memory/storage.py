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


VALID_TYPES = frozenset(
    {"decision", "file_change", "task", "learning", "error", "brainstorm"}
)

MAX_LIMIT = 500
MAX_CONTENT_LENGTH = 50_000

# Characters/words that need escaping in FTS5 queries
_FTS5_SPECIAL = re.compile(r'["\'\*\(\)\{\}\+\:\^\-\.\\;/]')
_FTS5_KEYWORDS = {"AND", "OR", "NOT", "NEAR"}


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

    def by_session(self, session_id: str, limit: int = 50) -> list[Memory]:
        """Get all memories for a session."""
        limit = self._clamp_limit(limit)
        rows = self.conn.execute(
            "SELECT * FROM memories WHERE session_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        return [self._row_to_memory(r) for r in rows]

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
