"""MCP server for CC-Memory — persistent memory bank for Claude Code."""

from __future__ import annotations

import atexit
import logging
import os

from mcp.server.fastmcp import FastMCP

from cc_memory.config import DB_PATH
from cc_memory.storage import Storage, VALID_TYPES, MAX_LIMIT

logger = logging.getLogger(__name__)

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


@mcp.tool()
def memory_stats(
    project: str,
) -> str:
    """Get quick DB overview for a project — no API key needed.

    Returns: total memories, breakdown by type, date range, estimated duplicate count.

    Args:
        project: Project name
    """
    storage = get_storage()
    counts = storage.count_by_type(project)
    if not counts:
        return f"No memories for project '{project}'."

    total = sum(counts.values())
    lines = [f"## Stats for '{project}'", f"**Total:** {total} memories", "", "**By type:**"]
    for t in sorted(counts.keys()):
        lines.append(f"  - {t}: {counts[t]}")

    # Duplicate estimate
    groups = storage.group_duplicates(project)
    dup_groups = [g for g in groups if g.count > 1]
    dup_count = sum(g.count - 1 for g in dup_groups)  # extras beyond first
    if dup_count:
        pct = round(dup_count / total * 100)
        lines.append(f"\n**Duplicates:** ~{dup_count} ({pct}% of total)")
    else:
        lines.append("\n**Duplicates:** none detected")

    return "\n".join(lines)


@mcp.tool()
def memory_consolidate(
    project: str,
    dry_run: bool = True,
) -> str:
    """Consolidate memories: deduplicate, extract learnings, clean low-value records.

    AI-powered analysis (Sonnet, Opus fallback via Bouncer Rule).
    Default dry_run=True for safety — shows what WOULD happen without modifying DB.

    Args:
        project: Project name to consolidate
        dry_run: If True (default), preview changes without modifying DB
    """
    storage = get_storage()

    # Validate project exists
    counts = storage.count_by_type(project)
    if not counts:
        # Suggest available projects
        all_rows = storage.conn.execute(
            "SELECT DISTINCT project FROM memories ORDER BY project"
        ).fetchall()
        projects = [r["project"] for r in all_rows]
        if projects:
            return f"Project '{project}' not found. Available projects: {', '.join(projects)}"
        return f"No memories in database."

    # Check API key
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return (
            "Set ANTHROPIC_API_KEY environment variable to use consolidation.\n"
            "Consolidation uses Claude API (Sonnet/Opus) to analyze patterns in your memories."
        )

    # Import here to avoid import errors when API key is missing
    from cc_memory.analyzer import Analyzer
    from cc_memory.consolidator import Consolidator, ConsolidateOptions

    try:
        analyzer = Analyzer(api_key=api_key)
        consolidator = Consolidator(storage, analyzer)
        options = ConsolidateOptions(dry_run=dry_run)
        report = consolidator.consolidate(project, options)
    except Exception as e:
        logger.error("Consolidation failed: %s", e)
        return f"Consolidation error: {e}"

    # Format report
    mode = "DRY RUN" if dry_run else "APPLIED"
    lines = [
        f"## Consolidation Report [{mode}]",
        f"**Project:** {project}",
        f"**Duplicates removed:** {report.duplicates_removed}",
        f"**Learnings created:** {report.learnings_created}",
        f"**Patterns found:** {report.patterns_found}",
        f"**API calls used:** {report.api_calls_used}",
    ]

    if report.stats_before:
        lines.append(f"\n**Before:** {report.stats_before}")
    if report.stats_after:
        lines.append(f"**After:** {report.stats_after}")

    if report.suggestions_for_claude_md:
        lines.append("\n## Suggestions for CLAUDE.md")
        lines.append("Add to project CLAUDE.md:")
        for s in report.suggestions_for_claude_md:
            lines.append(f'- "{s}"')

    if dry_run:
        lines.append("\n*This was a dry run. Use `memory_consolidate(project, dry_run=False)` to apply changes.*")

    return "\n".join(lines)


def main() -> None:
    """Entry point for cc-memory-server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
