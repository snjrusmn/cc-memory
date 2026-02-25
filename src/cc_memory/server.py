"""MCP server for CC-Memory — persistent memory bank for Claude Code."""

from __future__ import annotations

import atexit

from mcp.server.fastmcp import FastMCP

from cc_memory.config import DB_PATH
from cc_memory.storage import Storage, VALID_TYPES, MAX_LIMIT

mcp = FastMCP("cc-memory")

_storage: Storage | None = None


def _truncate(text: str, max_len: int = 200) -> str:
    """Truncate text with ellipsis indicator."""
    return text[:max_len] + "..." if len(text) > max_len else text


def get_storage() -> Storage:
    """Lazy-init storage singleton."""
    global _storage
    if _storage is None:
        _storage = Storage(DB_PATH)
        _storage.init_db()
        atexit.register(_storage.close)
    return _storage


def _reset_storage(storage: Storage | None = None) -> None:
    """Reset storage singleton (for testing)."""
    global _storage
    _storage = storage


@mcp.tool()
def memory_save(
    session_id: str,
    project: str,
    type: str,
    content: str,
    metadata: dict | None = None,
) -> str:
    """Save a memory (decision, file_change, task, learning, error, brainstorm).

    Args:
        session_id: Current session identifier
        project: Project name
        type: Memory type — one of: decision, file_change, task, learning, error, brainstorm
        content: The memory text to save
        metadata: Optional structured data (JSON object)
    """
    storage = get_storage()
    try:
        mid = storage.save(session_id, project, type, content, metadata)
        return f"Saved memory #{mid} ({type}) for project '{project}'"
    except ValueError:
        return f"Error: invalid memory type '{type}'. Must be one of: {', '.join(sorted(VALID_TYPES))}"


@mcp.tool()
def memory_search(
    query: str,
    project: str | None = None,
    type: str | None = None,
    limit: int = 20,
) -> str:
    """Search memories using full-text search (FTS5).

    Args:
        query: Search query text
        project: Optional project name to filter by
        type: Optional memory type filter
        limit: Max results to return (default 20)
    """
    storage = get_storage()
    results = storage.search(query, project=project, type=type, limit=limit)
    if not results:
        return "No memories found."
    lines = []
    for m in results:
        lines.append(f"[#{m.id}] ({m.type}) {m.project} — {_truncate(m.content)}")
    return "\n".join(lines)


@mcp.tool()
def memory_recent(
    project: str,
    limit: int = 20,
) -> str:
    """Get most recent memories for a project.

    Args:
        project: Project name
        limit: Max results to return (default 20)
    """
    storage = get_storage()
    results = storage.recent(project, limit=limit)
    if not results:
        return f"No memories for project '{project}'."
    lines = []
    for m in results:
        lines.append(f"[#{m.id}] ({m.type}) {m.created_at} — {_truncate(m.content)}")
    return "\n".join(lines)


@mcp.tool()
def memory_project(
    project: str,
    type: str | None = None,
    limit: int = 50,
) -> str:
    """Get all memories for a project, optionally filtered by type.

    Args:
        project: Project name
        type: Optional memory type filter
        limit: Max results to return (default 50)
    """
    storage = get_storage()
    results = storage.by_project(project, type=type, limit=limit)
    if not results:
        return f"No memories for project '{project}'."
    lines = []
    for m in results:
        lines.append(f"[#{m.id}] ({m.type}) {m.created_at} — {_truncate(m.content)}")
    return "\n".join(lines)


@mcp.tool()
def memory_session(
    session_id: str,
    limit: int = 50,
) -> str:
    """Get memories from a specific session.

    Args:
        session_id: Session identifier
        limit: Max results to return (default 50)
    """
    storage = get_storage()
    results = storage.by_session(session_id, limit=limit)
    if not results:
        return f"No memories for session '{session_id}'."
    lines = []
    for m in results:
        lines.append(f"[#{m.id}] ({m.type}) {m.project} — {_truncate(m.content)}")
    return "\n".join(lines)


@mcp.tool()
def memory_forget(
    memory_id: int,
) -> str:
    """Delete a memory by its ID.

    Args:
        memory_id: ID of the memory to delete
    """
    storage = get_storage()
    if storage.delete(memory_id):
        return f"Deleted memory #{memory_id}."
    return f"Memory #{memory_id} not found."


def main() -> None:
    """Entry point for cc-memory-server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
