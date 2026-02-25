"""Tests for cc_memory.hooks.user_prompt — UserPromptSubmit hook."""

import json
from pathlib import Path

import pytest

import cc_memory.hooks.user_prompt as user_prompt_mod
from cc_memory.hooks.user_prompt import (
    run,
    detect_keywords,
    get_counter,
    increment_counter,
    _counter_path,
    SAVE_EVERY_N,
)
from cc_memory.storage import Storage


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture(autouse=True)
def _use_tmp_counter_dir(tmp_path, monkeypatch):
    """Use tmp_path for counter files instead of shared temp dir."""
    counter_dir = tmp_path / "cc-memory-counters"
    counter_dir.mkdir()
    monkeypatch.setattr(user_prompt_mod, "_counter_dir", lambda: counter_dir)


def _make_input(prompt="Hello", session_id="test-session", cwd="/home/user/my-project"):
    return json.dumps({
        "session_id": session_id,
        "prompt": prompt,
        "cwd": cwd,
        "hook_event_name": "UserPromptSubmit",
    })


# ── prompt counter ───────────────────────────────────────────────


class TestPromptCounter:
    def test_starts_at_zero(self):
        assert get_counter("test-counter-new") == 0

    def test_increments(self):
        sid = "test-counter-inc"
        assert increment_counter(sid) == 1
        assert increment_counter(sid) == 2
        assert increment_counter(sid) == 3

    def test_persists_across_calls(self):
        sid = "test-counter-persist"
        increment_counter(sid)
        increment_counter(sid)
        assert get_counter(sid) == 2


# ── keyword detection ────────────────────────────────────────────


class TestDetectKeywords:
    def test_detects_decision_keywords(self):
        assert any(m["type"] == "decision" for m in detect_keywords("Решили использовать SQLite"))
        assert any(m["type"] == "decision" for m in detect_keywords("I decided to use FastAPI"))
        assert any(m["type"] == "decision" for m in detect_keywords("Давай используем React"))

    def test_detects_task_keywords(self):
        assert any(m["type"] == "task" for m in detect_keywords("Нужно добавить тесты"))
        assert any(m["type"] == "task" for m in detect_keywords("TODO: fix the bug"))
        assert any(m["type"] == "task" for m in detect_keywords("Сделай рефакторинг"))

    def test_no_keywords_in_normal_prompt(self):
        assert detect_keywords("What is the weather today?") == []
        assert detect_keywords("Show me the file") == []

    def test_both_decision_and_task(self):
        result = detect_keywords("Решили что нужно рефакторить код")
        types = [m["type"] for m in result]
        assert "decision" in types
        assert "task" in types


# ── auto-save on keywords ────────────────────────────────────────


class TestAutoSaveKeywords:
    def test_saves_decision_to_db(self, db_path, tmp_path):
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()
        run(_make_input(
            prompt="Решили использовать SQLite",
            session_id="test-save-decision",
            cwd=str(project_dir),
        ), db_path=db_path)

        storage = Storage(db_path)
        storage.init_db()
        memories = storage.by_session("test-save-decision")
        storage.close()
        assert any(m.type == "decision" for m in memories)

    def test_saves_task_to_db(self, db_path, tmp_path):
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()
        run(_make_input(
            prompt="Нужно добавить валидацию",
            session_id="test-save-task",
            cwd=str(project_dir),
        ), db_path=db_path)

        storage = Storage(db_path)
        storage.init_db()
        memories = storage.by_session("test-save-task")
        storage.close()
        assert any(m.type == "task" for m in memories)

    def test_no_save_for_normal_prompt(self, db_path, tmp_path):
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()
        run(_make_input(
            prompt="Show me the file",
            session_id="test-no-save",
            cwd=str(project_dir),
        ), db_path=db_path)

        storage = Storage(db_path)
        storage.init_db()
        memories = storage.by_session("test-no-save")
        storage.close()
        assert len(memories) == 0


# ── periodic checkpoint ──────────────────────────────────────────


class TestPeriodicCheckpoint:
    def test_saves_checkpoint_every_n_prompts(self, db_path, tmp_path):
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()
        sid = "test-checkpoint"

        for i in range(SAVE_EVERY_N):
            run(_make_input(
                prompt="regular prompt",
                session_id=sid,
                cwd=str(project_dir),
            ), db_path=db_path)

        storage = Storage(db_path)
        storage.init_db()
        memories = storage.by_session(sid)
        storage.close()
        assert any("checkpoint" in m.content.lower() for m in memories)


# ── run ──────────────────────────────────────────────────────────


class TestRun:
    def test_returns_empty_dict(self, db_path):
        result = run(_make_input(), db_path=db_path)
        assert result == {}

    def test_invalid_json(self, db_path):
        result = run("not json", db_path=db_path)
        assert result == {}

    def test_empty_prompt(self, db_path):
        result = run(_make_input(prompt=""), db_path=db_path)
        assert result == {}

    def test_missing_cwd_returns_empty(self, db_path):
        """Missing cwd field returns empty dict."""
        inp = json.dumps({
            "session_id": "s1",
            "prompt": "hello",
            "hook_event_name": "UserPromptSubmit",
        })
        result = run(inp, db_path=db_path)
        assert result == {}


# ── session_id sanitization ─────────────────────────────────────


class TestSessionIdSanitization:
    def test_sanitizes_special_chars(self):
        """Session ID with special chars gets sanitized for filename."""
        path = _counter_path("../../etc/cron.d/evil")
        assert ".." not in str(path.name)
        assert "/" not in str(path.name)

    def test_truncates_long_session_id(self):
        long_id = "a" * 300
        path = _counter_path(long_id)
        assert len(path.name) < 200

    def test_normal_session_id_unchanged(self):
        path = _counter_path("abc-123_test")
        assert "abc-123_test" in str(path.name)
