"""Tests for cc_memory.hooks.pre_compact — PreCompact hook."""

import json
import tempfile
from pathlib import Path

import pytest

from cc_memory.hooks.pre_compact import run, detect_project
from cc_memory.storage import Storage

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = FIXTURES / "sample_transcript.jsonl"


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


def _make_input(session_id="test-session", transcript_path=None, cwd="/home/user/my-project"):
    return json.dumps({
        "session_id": session_id,
        "transcript_path": str(transcript_path or SAMPLE),
        "cwd": cwd,
        "hook_event_name": "PreCompact",
        "trigger": "auto",
    })


# ── detect_project ───────────────────────────────────────────────


class TestDetectProject:
    def test_returns_dirname(self, tmp_path):
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()
        assert detect_project(str(project_dir)) == "my-project"

    def test_uses_git_root(self, tmp_path):
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()
        (project_dir / ".git").mkdir()
        sub = project_dir / "src" / "lib"
        sub.mkdir(parents=True)
        assert detect_project(str(sub)) == "my-project"


# ── run ──────────────────────────────────────────────────────────


class TestRun:
    def test_extracts_and_saves_memories(self, db_path):
        result = run(_make_input(), db_path=db_path)
        assert "saved" in result.get("systemMessage", "")
        assert "memories" in result["systemMessage"]

    def test_returns_system_message(self, db_path):
        result = run(_make_input(), db_path=db_path)
        assert "systemMessage" in result

    def test_saves_to_database(self, db_path):
        run(_make_input(session_id="s1"), db_path=db_path)
        storage = Storage(db_path)
        storage.init_db()
        memories = storage.by_session("s1")
        assert len(memories) > 0
        storage.close()

    def test_uses_session_id_from_input(self, db_path):
        run(_make_input(session_id="my-session-42"), db_path=db_path)
        storage = Storage(db_path)
        storage.init_db()
        memories = storage.by_session("my-session-42")
        assert len(memories) > 0
        storage.close()

    def test_detects_project_from_cwd(self, db_path, tmp_path):
        project_dir = tmp_path / "cool-project"
        project_dir.mkdir()
        result = run(_make_input(cwd=str(project_dir)), db_path=db_path)
        storage = Storage(db_path)
        storage.init_db()
        memories = storage.by_project("cool-project")
        assert len(memories) > 0
        storage.close()

    def test_invalid_json_input(self, db_path):
        result = run("not json at all", db_path=db_path)
        assert "invalid" in result.get("systemMessage", "").lower()

    def test_missing_transcript(self, db_path):
        result = run(_make_input(transcript_path="/nonexistent/path.jsonl"), db_path=db_path)
        assert "no transcript" in result.get("systemMessage", "").lower()

    def test_empty_transcript(self, db_path, tmp_path):
        empty_file = tmp_path / "empty.jsonl"
        empty_file.write_text("")
        result = run(_make_input(transcript_path=str(empty_file)), db_path=db_path)
        assert "no memories" in result.get("systemMessage", "").lower()

    def test_counts_by_type(self, db_path):
        result = run(_make_input(), db_path=db_path)
        msg = result["systemMessage"]
        # Should include type counts like "3 file_changes, 2 decisions"
        assert "decision" in msg or "file_change" in msg or "error" in msg
