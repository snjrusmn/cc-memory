"""Tests for cc_memory.extractor — JSONL transcript parser."""

import json
from pathlib import Path

import pytest

from cc_memory.extractor import Extractor

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = FIXTURES / "sample_transcript.jsonl"


@pytest.fixture
def extractor():
    return Extractor(SAMPLE)


# ── extract_file_changes ─────────────────────────────────────────


class TestExtractFileChanges:
    def test_finds_write_operations(self, extractor):
        changes = extractor.extract_file_changes()
        paths = [c["content"] for c in changes]
        assert any("storage.py" in p for p in paths)

    def test_finds_edit_operations(self, extractor):
        changes = extractor.extract_file_changes()
        paths = [c["content"] for c in changes]
        assert any("config.yaml" in p for p in paths)

    def test_skips_sensitive_files(self, extractor):
        changes = extractor.extract_file_changes()
        paths = [c["content"] for c in changes]
        assert not any(".env" in p for p in paths)

    def test_returns_dicts_with_type(self, extractor):
        changes = extractor.extract_file_changes()
        assert all(c["type"] == "file_change" for c in changes)


# ── extract_decisions ────────────────────────────────────────────


class TestExtractDecisions:
    def test_finds_ask_user_question_answers(self, extractor):
        decisions = extractor.extract_decisions()
        contents = [d["content"] for d in decisions]
        assert any("SQLite" in c for c in contents)

    def test_returns_dicts_with_type(self, extractor):
        decisions = extractor.extract_decisions()
        assert all(d["type"] == "decision" for d in decisions)


# ── extract_tasks ────────────────────────────────────────────────


class TestExtractTasks:
    def test_finds_todo_patterns(self, extractor):
        tasks = extractor.extract_tasks()
        contents = [t["content"] for t in tasks]
        assert any("migration" in c for c in contents)

    def test_finds_next_patterns(self, extractor):
        tasks = extractor.extract_tasks()
        contents = [t["content"] for t in tasks]
        assert any("query layer" in c for c in contents)

    def test_returns_dicts_with_type(self, extractor):
        tasks = extractor.extract_tasks()
        assert all(t["type"] == "task" for t in tasks)


# ── extract_errors ───────────────────────────────────────────────


class TestExtractErrors:
    def test_finds_tool_errors(self, extractor):
        errors = extractor.extract_errors()
        contents = [e["content"] for e in errors]
        assert any("FAILED" in c or "AssertionError" in c for c in contents)

    def test_returns_dicts_with_type(self, extractor):
        errors = extractor.extract_errors()
        assert all(e["type"] == "error" for e in errors)


# ── extract_learnings ────────────────────────────────────────────


class TestExtractLearnings:
    def test_finds_insight_patterns(self, extractor):
        learnings = extractor.extract_learnings()
        contents = [l["content"] for l in learnings]
        assert any("Insight" in c or "SQLite" in c for c in contents)

    def test_finds_learned_patterns(self, extractor):
        learnings = extractor.extract_learnings()
        contents = [l["content"] for l in learnings]
        assert any("FTS5" in c for c in contents)

    def test_finds_cyrillic_patterns(self, extractor):
        learnings = extractor.extract_learnings()
        contents = [l["content"] for l in learnings]
        assert any("Оказалось" in c or "кириллицу" in c for c in contents)

    def test_returns_dicts_with_type(self, extractor):
        learnings = extractor.extract_learnings()
        assert all(l["type"] == "learning" for l in learnings)


# ── privacy filtering ────────────────────────────────────────────


class TestPrivacyFiltering:
    def test_skips_env_files(self, extractor):
        changes = extractor.extract_file_changes()
        paths = [c["content"] for c in changes]
        assert not any(".env" in p for p in paths)

    def test_is_sensitive_detects_env(self, extractor):
        assert extractor._is_sensitive(".env")
        assert extractor._is_sensitive("/path/to/.env.local")

    def test_is_sensitive_detects_credentials(self, extractor):
        assert extractor._is_sensitive("credentials.json")
        assert extractor._is_sensitive("Contains API_KEY=abc123")

    def test_is_sensitive_detects_private_tags(self, extractor):
        assert extractor._is_sensitive("data <private>secret</private> more")

    def test_not_sensitive_for_normal_content(self, extractor):
        assert not extractor._is_sensitive("normal code content")
        assert not extractor._is_sensitive("src/storage.py")

    def test_is_sensitive_detects_ssh_keys(self, extractor):
        assert extractor._is_sensitive("file id_rsa found")
        assert extractor._is_sensitive("id_ed25519 detected")

    def test_is_sensitive_detects_connection_strings(self, extractor):
        assert extractor._is_sensitive("postgresql://user:pass@host/db")
        assert extractor._is_sensitive("mongodb://localhost:27017")

    def test_is_sensitive_detects_aws_keys(self, extractor):
        assert extractor._is_sensitive("AKIAIOSFODNN7EXAMPLE")
        assert extractor._is_sensitive("aws_secret_access_key = abc")

    def test_is_sensitive_detects_cert_files(self, extractor):
        assert extractor._is_sensitive("loaded cert.pem")
        assert extractor._is_sensitive("keystore.p12")


# ── extract_all ──────────────────────────────────────────────────


class TestExtractAll:
    def test_combines_all_extractors(self, extractor):
        all_memories = extractor.extract_all()
        types = {m["type"] for m in all_memories}
        assert "file_change" in types
        assert "decision" in types
        assert "task" in types
        assert "error" in types
        assert "learning" in types

    def test_returns_list_of_dicts(self, extractor):
        all_memories = extractor.extract_all()
        assert isinstance(all_memories, list)
        for m in all_memories:
            assert "type" in m
            assert "content" in m

    def test_no_sensitive_content(self, extractor):
        all_memories = extractor.extract_all()
        for m in all_memories:
            assert ".env" not in m["content"]
            assert "secret123" not in m["content"]
            assert "sk-abc123" not in m["content"]
