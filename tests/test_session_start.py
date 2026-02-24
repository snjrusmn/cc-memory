"""Tests for cc_memory.hooks.session_start — SessionStart hook."""

import json
from pathlib import Path

import pytest

from cc_memory.hooks.session_start import run, detect_project, format_context
from cc_memory.storage import Storage, Memory


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def populated_db(db_path):
    """DB with some memories for testing."""
    storage = Storage(db_path)
    storage.init_db()
    storage.save("s1", "my-project", "decision", "Chose SQLite for storage")
    storage.save("s1", "my-project", "file_change", "Created src/storage.py")
    storage.save("s1", "my-project", "task", "TODO: Add migration support")
    storage.save("s1", "my-project", "learning", "FTS5 supports Cyrillic")
    storage.save("s1", "my-project", "error", "Test failed: AssertionError")
    storage.close()
    return db_path


def _make_input(cwd="/home/user/my-project"):
    return json.dumps({
        "session_id": "new-session",
        "cwd": cwd,
        "hook_event_name": "SessionStart",
        "source": "startup",
    })


# ── detect_project ───────────────────────────────────────────────


class TestDetectProject:
    def test_returns_dirname(self, tmp_path):
        d = tmp_path / "cool-project"
        d.mkdir()
        assert detect_project(str(d)) == "cool-project"

    def test_uses_git_root(self, tmp_path):
        d = tmp_path / "cool-project"
        d.mkdir()
        (d / ".git").mkdir()
        sub = d / "src" / "lib"
        sub.mkdir(parents=True)
        assert detect_project(str(sub)) == "cool-project"


# ── format_context ───────────────────────────────────────────────


class TestFormatContext:
    def test_empty_memories(self):
        assert format_context("proj", []) == ""

    def test_includes_project_header(self, populated_db):
        storage = Storage(populated_db)
        storage.init_db()
        memories = storage.recent("my-project")
        storage.close()
        ctx = format_context("my-project", memories)
        assert "## CC-Memory Context" in ctx
        assert "my-project" in ctx

    def test_includes_decisions_section(self, populated_db):
        storage = Storage(populated_db)
        storage.init_db()
        memories = storage.recent("my-project")
        storage.close()
        ctx = format_context("my-project", memories)
        assert "### Recent Decisions" in ctx
        assert "SQLite" in ctx

    def test_includes_tasks_section(self, populated_db):
        storage = Storage(populated_db)
        storage.init_db()
        memories = storage.recent("my-project")
        storage.close()
        ctx = format_context("my-project", memories)
        assert "### Active Tasks" in ctx
        assert "migration" in ctx

    def test_includes_file_changes(self, populated_db):
        storage = Storage(populated_db)
        storage.init_db()
        memories = storage.recent("my-project")
        storage.close()
        ctx = format_context("my-project", memories)
        assert "### Recent File Changes" in ctx
        assert "storage.py" in ctx

    def test_includes_learnings(self, populated_db):
        storage = Storage(populated_db)
        storage.init_db()
        memories = storage.recent("my-project")
        storage.close()
        ctx = format_context("my-project", memories)
        assert "### Learnings" in ctx
        assert "FTS5" in ctx


# ── run ──────────────────────────────────────────────────────────


class TestRun:
    def test_returns_additional_context(self, populated_db, tmp_path):
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()
        result = run(_make_input(cwd=str(project_dir)), db_path=populated_db)
        assert "hookSpecificOutput" in result
        assert "additionalContext" in result["hookSpecificOutput"]
        assert "CC-Memory Context" in result["hookSpecificOutput"]["additionalContext"]

    def test_empty_db_returns_empty(self, db_path, tmp_path):
        # Create empty DB
        storage = Storage(db_path)
        storage.init_db()
        storage.close()
        project_dir = tmp_path / "empty-project"
        project_dir.mkdir()
        result = run(_make_input(cwd=str(project_dir)), db_path=db_path)
        assert result == {}

    def test_nonexistent_db_returns_empty(self):
        result = run(_make_input(), db_path="/nonexistent/db.sqlite")
        # Should not crash, just return empty
        assert result == {} or "hookSpecificOutput" in result

    def test_invalid_json_returns_empty(self, populated_db):
        result = run("not json", db_path=populated_db)
        assert result == {}

    def test_all_session_start_sources(self, populated_db, tmp_path):
        """Hook should work for any SessionStart source."""
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()
        for source in ["startup", "resume", "clear", "compact"]:
            inp = json.dumps({
                "session_id": f"session-{source}",
                "cwd": str(project_dir),
                "hook_event_name": "SessionStart",
                "source": source,
            })
            result = run(inp, db_path=populated_db)
            assert "hookSpecificOutput" in result
