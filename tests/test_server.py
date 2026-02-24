"""Tests for cc_memory.server — MCP server tools."""

import pytest

from cc_memory.storage import Storage
from cc_memory.server import (
    memory_save,
    memory_search,
    memory_recent,
    memory_project,
    memory_session,
    memory_forget,
    _reset_storage,
)


@pytest.fixture(autouse=True)
def _inject_test_storage(storage):
    """Inject in-memory storage into server module for all tests."""
    _reset_storage(storage)
    yield
    _reset_storage(None)


# ── memory_save ──────────────────────────────────────────────────


class TestMemorySave:
    def test_saves_and_returns_confirmation(self):
        result = memory_save("s1", "proj", "decision", "chose SQLite")
        assert "Saved memory #1" in result
        assert "decision" in result
        assert "proj" in result

    def test_saves_with_metadata(self):
        result = memory_save("s1", "proj", "file_change", "edited server.py", {"file": "server.py"})
        assert "Saved memory" in result

    def test_invalid_type_returns_error(self):
        result = memory_save("s1", "proj", "invalid", "content")
        assert "Error" in result

    def test_all_valid_types(self):
        for t in ["decision", "file_change", "task", "learning", "error", "brainstorm"]:
            result = memory_save("s1", "proj", t, f"content for {t}")
            assert "Saved memory" in result


# ── memory_search ────────────────────────────────────────────────


class TestMemorySearch:
    def test_finds_by_content(self):
        memory_save("s1", "proj", "decision", "chose SQLite over Postgres")
        result = memory_search("SQLite")
        assert "#1" in result
        assert "SQLite" in result

    def test_filter_by_project(self):
        memory_save("s1", "proj-a", "decision", "keyword in proj-a")
        memory_save("s1", "proj-b", "decision", "keyword in proj-b")
        result = memory_search("keyword", project="proj-a")
        assert "proj-a" in result
        assert "proj-b" not in result

    def test_filter_by_type(self):
        memory_save("s1", "proj", "decision", "testing keyword")
        memory_save("s1", "proj", "learning", "testing keyword learned")
        result = memory_search("testing", type="learning")
        assert "learning" in result

    def test_no_results(self):
        result = memory_search("nonexistent_xyzzy")
        assert "No memories found" in result

    def test_empty_query(self):
        memory_save("s1", "proj", "decision", "something")
        result = memory_search("")
        assert "No memories found" in result

    def test_limit(self):
        for i in range(10):
            memory_save("s1", "proj", "decision", f"architecture decision {i}")
        result = memory_search("architecture", limit=3)
        lines = [l for l in result.strip().split("\n") if l.startswith("[")]
        assert len(lines) == 3


# ── memory_recent ────────────────────────────────────────────────


class TestMemoryRecent:
    def test_returns_recent_for_project(self):
        memory_save("s1", "proj", "decision", "first")
        memory_save("s1", "proj", "learning", "second")
        result = memory_recent("proj")
        assert "#" in result
        assert "first" in result
        assert "second" in result

    def test_empty_project(self):
        result = memory_recent("nonexistent")
        assert "No memories" in result

    def test_limit(self):
        for i in range(10):
            memory_save("s1", "proj", "decision", f"item {i}")
        result = memory_recent("proj", limit=3)
        lines = [l for l in result.strip().split("\n") if l.startswith("[")]
        assert len(lines) == 3


# ── memory_project ───────────────────────────────────────────────


class TestMemoryProject:
    def test_returns_all_for_project(self):
        memory_save("s1", "proj", "decision", "d1")
        memory_save("s1", "proj", "learning", "l1")
        result = memory_project("proj")
        assert "d1" in result
        assert "l1" in result

    def test_filter_by_type(self):
        memory_save("s1", "proj", "decision", "d1")
        memory_save("s1", "proj", "learning", "l1")
        result = memory_project("proj", type="decision")
        assert "d1" in result
        assert "l1" not in result

    def test_empty_project(self):
        result = memory_project("nonexistent")
        assert "No memories" in result


# ── memory_session ───────────────────────────────────────────────


class TestMemorySession:
    def test_returns_for_session(self):
        memory_save("session-1", "proj", "decision", "d1")
        memory_save("session-1", "proj", "learning", "l1")
        memory_save("session-2", "proj", "decision", "d2")
        result = memory_session("session-1")
        assert "d1" in result
        assert "l1" in result
        assert "d2" not in result

    def test_empty_session(self):
        result = memory_session("nonexistent")
        assert "No memories" in result


# ── memory_forget ────────────────────────────────────────────────


class TestMemoryForget:
    def test_deletes_existing(self):
        memory_save("s1", "proj", "decision", "to delete")
        result = memory_forget(1)
        assert "Deleted memory #1" in result

    def test_nonexistent_returns_not_found(self):
        result = memory_forget(99999)
        assert "not found" in result

    def test_deleted_not_searchable(self):
        memory_save("s1", "proj", "decision", "unique_deletable_text")
        memory_forget(1)
        result = memory_search("unique_deletable_text")
        assert "No memories found" in result


# ── error handling ───────────────────────────────────────────────


class TestErrorHandling:
    def test_save_missing_required_returns_error(self):
        result = memory_save("s1", "proj", "bad_type", "content")
        assert "Error" in result
