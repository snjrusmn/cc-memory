"""Tests for cc_memory.server — MCP server tools."""

from unittest.mock import MagicMock, patch

import pytest

from cc_memory.storage import Storage
from cc_memory.server import (
    memory_save,
    memory_search,
    memory_recent,
    memory_project,
    memory_session,
    memory_forget,
    memory_stats,
    memory_consolidate,
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


# ── memory_stats ────────────────────────────────────────────────


class TestMemoryStats:
    def test_returns_type_distribution(self):
        memory_save("s1", "proj", "error", "err 1")
        memory_save("s1", "proj", "error", "err 2")
        memory_save("s1", "proj", "decision", "dec 1")
        result = memory_stats("proj")
        assert "error" in result
        assert "2" in result
        assert "decision" in result

    def test_returns_total_count(self):
        for i in range(5):
            memory_save("s1", "proj", "error", f"err {i}")
        result = memory_stats("proj")
        assert "5" in result

    def test_returns_duplicate_estimate(self):
        # 3 identical errors → should report duplicates
        for _ in range(3):
            memory_save("s1", "proj", "error", "same error content")
        result = memory_stats("proj")
        assert "duplicate" in result.lower()

    def test_empty_project(self):
        result = memory_stats("nonexistent")
        assert "No memories" in result

    def test_no_api_key_needed(self):
        """memory_stats should work without ANTHROPIC_API_KEY."""
        memory_save("s1", "proj", "decision", "test")
        result = memory_stats("proj")
        assert "Error" not in result


# ── memory_consolidate ──────────────────────────────────────────


class TestMemoryConsolidate:
    def test_dry_run_default(self):
        """Default should be dry_run=True."""
        for _ in range(5):
            memory_save("s1", "proj", "error", "same error")
        with patch("cc_memory.analyzer.Analyzer") as MockAnalyzer:
            instance = MockAnalyzer.return_value
            instance.api_calls_made = 0
            instance.max_api_calls = 15
            from cc_memory.analyzer import AnalysisResult
            instance.analyze_group.return_value = AnalysisResult(
                content="lesson", type="learning", confidence=0.9,
                source_ids=[1, 2, 3, 4, 5], suggestions=[],
            )
            result = memory_consolidate("proj")

        # dry_run should NOT delete anything
        remaining = memory_recent("proj", limit=100)
        assert "same error" in remaining

    def test_dry_run_false_modifies_db(self, monkeypatch):
        """dry_run=False should actually clean up."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        for _ in range(5):
            memory_save("s1", "proj", "error", "same error")
        with patch("cc_memory.analyzer.Analyzer") as MockAnalyzer:
            instance = MockAnalyzer.return_value
            instance.api_calls_made = 2
            instance.max_api_calls = 15
            from cc_memory.analyzer import AnalysisResult
            instance.analyze_group.return_value = AnalysisResult(
                content="Always check first",
                type="learning", confidence=0.9,
                source_ids=[1, 2, 3, 4, 5],
                suggestions=["Add to CLAUDE.md"],
            )
            result = memory_consolidate("proj", dry_run=False)

        assert "learning" in result.lower() or "created" in result.lower()

    def test_missing_api_key(self, monkeypatch):
        """Should return helpful message when ANTHROPIC_API_KEY is missing."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        memory_save("s1", "proj", "error", "test")
        result = memory_consolidate("proj")
        assert "ANTHROPIC_API_KEY" in result

    def test_unknown_project_suggests_available(self):
        """Unknown project should list available projects."""
        memory_save("s1", "real-proj", "decision", "test")
        result = memory_consolidate("nonexistent")
        assert "real-proj" in result

    def test_report_formatting(self, monkeypatch):
        """Report should be human-readable."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        for _ in range(5):
            memory_save("s1", "proj", "error", "repeated error")
        with patch("cc_memory.analyzer.Analyzer") as MockAnalyzer:
            instance = MockAnalyzer.return_value
            instance.api_calls_made = 1
            instance.max_api_calls = 15
            from cc_memory.analyzer import AnalysisResult
            instance.analyze_group.return_value = AnalysisResult(
                content="lesson learned",
                type="learning", confidence=0.9,
                source_ids=[1, 2, 3, 4, 5],
                suggestions=["Always commit first"],
            )
            result = memory_consolidate("proj")
        # Should contain section headers
        assert "duplicate" in result.lower() or "removed" in result.lower() or "stats" in result.lower()
