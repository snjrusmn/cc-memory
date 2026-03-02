"""Tests for cc_memory.storage — SQLite + FTS5 storage layer."""

import pytest

from cc_memory.storage import Memory, Storage, VALID_TYPES, MAX_LIMIT, MAX_CONTENT_LENGTH, _sanitize_fts_query


# ── init_db ──────────────────────────────────────────────────────


class TestInitDb:
    def test_creates_memories_table(self, storage):
        rows = storage.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='memories'"
        ).fetchall()
        assert len(rows) == 1

    def test_creates_fts_table(self, storage):
        rows = storage.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='memories_fts'"
        ).fetchall()
        assert len(rows) == 1

    def test_creates_indexes(self, storage):
        indexes = {
            row["name"]
            for row in storage.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        assert "idx_memories_project_date" in indexes
        assert "idx_memories_session" in indexes
        assert "idx_memories_type" in indexes

    def test_idempotent(self, storage):
        """Calling init_db twice should not error."""
        storage.init_db()


# ── save ─────────────────────────────────────────────────────────


class TestSave:
    def test_returns_integer_id(self, storage):
        mid = storage.save("s1", "proj", "decision", "chose SQLite")
        assert isinstance(mid, int)
        assert mid > 0

    def test_saves_all_fields(self, storage):
        meta = {"file": "storage.py", "line": 42}
        mid = storage.save("s1", "proj", "file_change", "edited storage.py", meta)
        row = storage.conn.execute(
            "SELECT * FROM memories WHERE id = ?", (mid,)
        ).fetchone()
        assert row["session_id"] == "s1"
        assert row["project"] == "proj"
        assert row["type"] == "file_change"
        assert row["content"] == "edited storage.py"
        assert '"file": "storage.py"' in row["metadata"]

    def test_auto_increments_id(self, storage):
        id1 = storage.save("s1", "proj", "decision", "first")
        id2 = storage.save("s1", "proj", "decision", "second")
        assert id2 > id1

    def test_rejects_invalid_type(self, storage):
        with pytest.raises(ValueError, match="Invalid type"):
            storage.save("s1", "proj", "invalid_type", "content")

    def test_all_valid_types(self, storage):
        for t in VALID_TYPES:
            mid = storage.save("s1", "proj", t, f"content for {t}")
            assert mid > 0

    def test_metadata_none(self, storage):
        mid = storage.save("s1", "proj", "decision", "no meta")
        row = storage.conn.execute(
            "SELECT metadata FROM memories WHERE id = ?", (mid,)
        ).fetchone()
        assert row["metadata"] is None


# ── search (FTS5) ────────────────────────────────────────────────


class TestSearch:
    def test_finds_by_content(self, storage):
        storage.save("s1", "proj", "decision", "chose SQLite over Postgres")
        storage.save("s1", "proj", "decision", "use FastAPI for HTTP")
        results = storage.search("SQLite")
        assert len(results) == 1
        assert "SQLite" in results[0].content

    def test_filter_by_project(self, storage):
        storage.save("s1", "proj-a", "decision", "shared keyword test")
        storage.save("s1", "proj-b", "decision", "shared keyword test")
        results = storage.search("keyword", project="proj-a")
        assert len(results) == 1
        assert results[0].project == "proj-a"

    def test_filter_by_type(self, storage):
        storage.save("s1", "proj", "decision", "important note about testing")
        storage.save("s1", "proj", "learning", "learned about testing")
        results = storage.search("testing", type="learning")
        assert len(results) == 1
        assert results[0].type == "learning"

    def test_limit(self, storage):
        for i in range(10):
            storage.save("s1", "proj", "decision", f"decision number {i} about architecture")
        results = storage.search("architecture", limit=3)
        assert len(results) == 3

    def test_empty_query_returns_empty(self, storage):
        storage.save("s1", "proj", "decision", "something")
        assert storage.search("") == []
        assert storage.search("   ") == []

    def test_no_results(self, storage):
        storage.save("s1", "proj", "decision", "hello world")
        results = storage.search("nonexistent_xyzzy")
        assert results == []

    def test_returns_memory_objects(self, storage):
        storage.save("s1", "proj", "decision", "chose SQLite")
        results = storage.search("SQLite")
        assert len(results) == 1
        m = results[0]
        assert isinstance(m, Memory)
        assert m.session_id == "s1"
        assert m.project == "proj"

    def test_cyrillic_text(self, storage):
        storage.save("s1", "proj", "decision", "выбрали SQLite для хранения")
        storage.save("s1", "proj", "learning", "узнали про индексы в Postgres")
        results = storage.search("SQLite")
        assert len(results) == 1
        assert "выбрали" in results[0].content

    def test_json_metadata_preserved(self, storage):
        meta = {"tags": ["python", "sqlite"], "priority": 1}
        storage.save("s1", "proj", "decision", "metadata test content", meta)
        results = storage.search("metadata test")
        assert len(results) == 1
        assert results[0].metadata == meta


# ── recent ───────────────────────────────────────────────────────


class TestRecent:
    def test_returns_recent_for_project(self, storage):
        storage.save("s1", "proj-a", "decision", "first")
        storage.save("s1", "proj-a", "decision", "second")
        storage.save("s1", "proj-b", "decision", "other project")
        results = storage.recent("proj-a")
        assert len(results) == 2
        assert all(m.project == "proj-a" for m in results)

    def test_ordered_by_created_at_desc(self, storage):
        storage.save("s1", "proj", "decision", "older")
        storage.save("s1", "proj", "decision", "newer")
        results = storage.recent("proj")
        # Newer has higher id
        assert results[0].id > results[1].id

    def test_limit(self, storage):
        for i in range(10):
            storage.save("s1", "proj", "decision", f"item {i}")
        results = storage.recent("proj", limit=3)
        assert len(results) == 3

    def test_empty_project(self, storage):
        results = storage.recent("nonexistent")
        assert results == []


# ── by_project ───────────────────────────────────────────────────


class TestByProject:
    def test_returns_all_for_project(self, storage):
        storage.save("s1", "proj", "decision", "d1")
        storage.save("s1", "proj", "learning", "l1")
        storage.save("s1", "other", "decision", "d2")
        results = storage.by_project("proj")
        assert len(results) == 2

    def test_filter_by_type(self, storage):
        storage.save("s1", "proj", "decision", "d1")
        storage.save("s1", "proj", "learning", "l1")
        results = storage.by_project("proj", type="decision")
        assert len(results) == 1
        assert results[0].type == "decision"

    def test_limit(self, storage):
        for i in range(10):
            storage.save("s1", "proj", "decision", f"d{i}")
        results = storage.by_project("proj", limit=5)
        assert len(results) == 5


# ── by_session ───────────────────────────────────────────────────


class TestBySession:
    def test_returns_all_for_session(self, storage):
        storage.save("session-1", "proj", "decision", "d1")
        storage.save("session-1", "proj", "learning", "l1")
        storage.save("session-2", "proj", "decision", "d2")
        results = storage.by_session("session-1")
        assert len(results) == 2
        assert all(m.session_id == "session-1" for m in results)

    def test_empty_session(self, storage):
        results = storage.by_session("nonexistent")
        assert results == []


# ── delete ───────────────────────────────────────────────────────


class TestDelete:
    def test_deletes_existing(self, storage):
        mid = storage.save("s1", "proj", "decision", "to delete")
        assert storage.delete(mid) is True
        results = storage.recent("proj")
        assert len(results) == 0

    def test_returns_false_for_nonexistent(self, storage):
        assert storage.delete(99999) is False

    def test_removed_from_fts(self, storage):
        mid = storage.save("s1", "proj", "decision", "unique_searchable_text")
        storage.delete(mid)
        results = storage.search("unique_searchable_text")
        assert results == []


# ── context manager ──────────────────────────────────────────────


class TestContextManager:
    def test_with_statement(self):
        with Storage(":memory:") as s:
            s.init_db()
            s.save("s1", "proj", "decision", "context manager test")
            results = s.recent("proj")
            assert len(results) == 1

    def test_closes_on_exit(self):
        s = Storage(":memory:")
        s.init_db()
        s.__enter__()
        s.__exit__(None, None, None)
        # Connection should be closed — further operations raise
        import sqlite3
        with pytest.raises(sqlite3.ProgrammingError):
            s.conn.execute("SELECT 1")


# ── FTS5 query sanitizer ────────────────────────────────────────


class TestFtsQuerySanitizer:
    def test_escapes_quotes(self):
        assert '"' not in _sanitize_fts_query('test "quoted" text')

    def test_escapes_single_quotes(self):
        assert "'" not in _sanitize_fts_query("test 'quoted' text")

    def test_escapes_asterisk(self):
        assert "*" not in _sanitize_fts_query("test*")

    def test_escapes_parentheses(self):
        result = _sanitize_fts_query("test (group)")
        assert "(" not in result
        assert ")" not in result

    def test_escapes_and_keyword(self):
        result = _sanitize_fts_query("this AND that")
        assert '"AND"' in result

    def test_escapes_or_keyword(self):
        result = _sanitize_fts_query("this OR that")
        assert '"OR"' in result

    def test_escapes_not_keyword(self):
        result = _sanitize_fts_query("NOT this")
        assert '"NOT"' in result

    def test_empty_string(self):
        assert _sanitize_fts_query("") == ""

    def test_whitespace_only(self):
        assert _sanitize_fts_query("   ") == ""

    def test_normal_query_unchanged(self):
        assert _sanitize_fts_query("simple query") == "simple query"

    def test_cpp_plus_signs_stripped(self):
        # C++ special chars are stripped to prevent FTS5 crash
        result = _sanitize_fts_query("C++ programming")
        assert "+" not in result
        assert "programming" in result

    def test_escapes_braces(self):
        result = _sanitize_fts_query("test {range}")
        assert "{" not in result
        assert "}" not in result

    def test_escapes_colon(self):
        result = _sanitize_fts_query("key:value")
        assert ":" not in result

    def test_escapes_caret(self):
        result = _sanitize_fts_query("^start")
        assert "^" not in result

    def test_escapes_minus(self):
        result = _sanitize_fts_query("include -exclude")
        assert "-" not in result

    def test_escapes_dot(self):
        result = _sanitize_fts_query("file.name")
        assert "." not in result

    def test_escapes_backslash(self):
        result = _sanitize_fts_query("path\\to\\file")
        assert "\\" not in result

    def test_escapes_semicolon(self):
        result = _sanitize_fts_query("stmt; DROP TABLE")
        assert ";" not in result

    def test_escapes_slash(self):
        result = _sanitize_fts_query("NEAR/3 word")
        assert "/" not in result


# ── WAL mode ────────────────────────────────────────────────────


class TestWalMode:
    def test_wal_mode_enabled(self, storage):
        mode = storage.conn.execute("PRAGMA journal_mode").fetchone()[0]
        # :memory: DBs use "memory" journal mode, not WAL
        # WAL is only for file-based DBs
        assert mode in ("wal", "memory")

    def test_busy_timeout_set(self, storage):
        timeout = storage.conn.execute("PRAGMA busy_timeout").fetchone()[0]
        assert timeout == 5000


# ── limit clamping ──────────────────────────────────────────────


class TestLimitClamping:
    def test_clamp_negative_to_one(self, storage):
        for i in range(5):
            storage.save("s1", "proj", "decision", f"item {i}")
        results = storage.recent("proj", limit=-1)
        assert len(results) == 1

    def test_clamp_zero_to_one(self, storage):
        storage.save("s1", "proj", "decision", "item")
        results = storage.recent("proj", limit=0)
        assert len(results) == 1

    def test_clamp_huge_to_max(self, storage):
        storage.save("s1", "proj", "decision", "item")
        # Should not crash with huge limit
        results = storage.recent("proj", limit=999999999)
        assert len(results) == 1


# ── content length limit ────────────────────────────────────────


class TestContentLengthLimit:
    def test_truncates_long_content(self, storage):
        long_content = "x" * (MAX_CONTENT_LENGTH + 100)
        mid = storage.save("s1", "proj", "decision", long_content)
        row = storage.conn.execute(
            "SELECT content FROM memories WHERE id = ?", (mid,)
        ).fetchone()
        assert len(row["content"]) <= MAX_CONTENT_LENGTH + 20  # allow for truncation marker
        assert row["content"].endswith("... [truncated]")

    def test_normal_content_not_truncated(self, storage):
        content = "short content"
        mid = storage.save("s1", "proj", "decision", content)
        row = storage.conn.execute(
            "SELECT content FROM memories WHERE id = ?", (mid,)
        ).fetchone()
        assert row["content"] == content


# ── frozen Memory dataclass ─────────────────────────────────────


class TestFrozenMemory:
    def test_memory_is_immutable(self, storage):
        storage.save("s1", "proj", "decision", "test")
        results = storage.recent("proj")
        m = results[0]
        with pytest.raises(AttributeError):
            m.content = "mutated"

    def test_memory_is_hashable(self, storage):
        storage.save("s1", "proj", "decision", "test")
        results = storage.recent("proj")
        # Frozen dataclass should be hashable
        assert hash(results[0]) is not None


# ── DB directory permissions ────────────────────────────────────


class TestDbPermissions:
    def test_creates_dir_with_restricted_permissions(self, tmp_path):
        db_file = tmp_path / "new_dir" / "test.db"
        s = Storage(str(db_file))
        s.init_db()
        s.close()
        import stat
        mode = db_file.parent.stat().st_mode & 0o777
        assert mode == 0o700


# ── recent_balanced ────────────────────────────────────────────


class TestRecentBalanced:
    def _seed_imbalanced(self, storage: Storage) -> None:
        """Seed storage with imbalanced data — dominated by errors."""
        # 30 errors (would dominate recent 20)
        for i in range(30):
            storage.save(f"s{i}", "proj", "error", f"Error #{i}")
        # 5 decisions
        for i in range(5):
            storage.save(f"s{i}", "proj", "decision", f"Decision #{i}")
        # 3 tasks
        for i in range(3):
            storage.save(f"s{i}", "proj", "task", f"Task #{i}")
        # 2 learnings
        storage.save("s1", "proj", "learning", "Learning #1")
        storage.save("s2", "proj", "learning", "Learning #2")
        # 1 brainstorm
        storage.save("s1", "proj", "brainstorm", "Brainstorm #1")
        # 4 file_changes
        for i in range(4):
            storage.save(f"s{i}", "proj", "file_change", f"File change #{i}")

    def test_balanced_retrieval(self, storage):
        """Should return memories balanced across types, not dominated by errors."""
        self._seed_imbalanced(storage)
        results = storage.recent_balanced("proj")
        types = [m.type for m in results]
        # Errors should be limited, not dominating
        assert types.count("error") <= 2
        # Decisions should be present
        assert types.count("decision") >= 1
        # Total should be reasonable (≤22 per spec)
        assert len(results) <= 22

    def test_respects_per_type_limits(self, storage):
        """Each type should respect its configured limit."""
        self._seed_imbalanced(storage)
        results = storage.recent_balanced("proj")
        types = [m.type for m in results]
        assert types.count("decision") <= 5
        assert types.count("task") <= 5
        assert types.count("file_change") <= 5
        assert types.count("learning") <= 3
        assert types.count("error") <= 2
        assert types.count("brainstorm") <= 2

    def test_project_with_only_errors(self, storage):
        """Project with only errors should still return results."""
        for i in range(20):
            storage.save(f"s{i}", "proj", "error", f"Error #{i}")
        results = storage.recent_balanced("proj")
        assert len(results) == 2  # max 2 errors
        assert all(m.type == "error" for m in results)

    def test_project_with_no_decisions(self, storage):
        """Should gracefully handle missing types."""
        storage.save("s1", "proj", "error", "Error #1")
        storage.save("s1", "proj", "task", "Task #1")
        results = storage.recent_balanced("proj")
        types = {m.type for m in results}
        assert "error" in types
        assert "task" in types
        assert "decision" not in types

    def test_empty_project(self, storage):
        """Empty project should return empty list."""
        results = storage.recent_balanced("nonexistent")
        assert results == []

    def test_recent_method_unchanged(self, storage):
        """Original recent() method should still work as before."""
        self._seed_imbalanced(storage)
        results = storage.recent("proj", limit=20)
        # Original method returns latest 20 regardless of type
        assert len(results) == 20

    def test_ordered_by_recency_within_type(self, storage):
        """Within each type, most recent should come first."""
        storage.save("s1", "proj", "decision", "Old decision")
        storage.save("s2", "proj", "decision", "New decision")
        results = storage.recent_balanced("proj")
        decisions = [m for m in results if m.type == "decision"]
        assert decisions[0].content == "New decision"
