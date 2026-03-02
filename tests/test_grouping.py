"""Tests for duplicate grouping, batch delete, and stats in storage layer."""

from __future__ import annotations

import pytest

from cc_memory.storage import Storage, MemoryGroup, _normalize_content


# ── Fixtures ────────────────────────────────────────────────────


@pytest.fixture
def storage():
    """In-memory storage for tests."""
    s = Storage(":memory:")
    s.init_db()
    yield s
    s.close()


def _seed_duplicates(storage: Storage) -> None:
    """Seed storage with duplicate errors and varied file changes."""
    # 5 identical errors (after normalization)
    for i in range(5):
        storage.save(f"sess-{i}", "proj-a", "error", "  Exit code 1\n  Uncommitted changes.  ")
    # 3 identical errors (different content)
    for i in range(3):
        storage.save(f"sess-{i}", "proj-a", "error", "File not found: /tmp/missing.txt")
    # 2 decisions (same)
    storage.save("sess-1", "proj-a", "decision", "Chose SQLite for storage")
    storage.save("sess-2", "proj-a", "decision", "Chose SQLite for storage")
    # 1 unique decision
    storage.save("sess-3", "proj-a", "decision", "Use TDD for all features")
    # File changes
    storage.save("sess-1", "proj-a", "file_change", "Edited src/main.py: added function")
    storage.save("sess-2", "proj-a", "file_change", "Edited src/main.py: fixed bug")
    # Different project
    storage.save("sess-1", "proj-b", "error", "Exit code 1\n  Uncommitted changes.")


# ── _normalize_content ──────────────────────────────────────────


class TestNormalizeContent:
    def test_strips_ansi_codes(self):
        text = "\033[0;31m[deploy]\033[0m Error occurred"
        assert _normalize_content(text) == "[deploy] error occurred"

    def test_collapses_whitespace(self):
        assert _normalize_content("  hello   world  \n\n  ") == "hello world"

    def test_lowercases(self):
        assert _normalize_content("Hello World") == "hello world"

    def test_strips_truncation_marker(self):
        assert _normalize_content("some text... [truncated]") == "some text..."

    def test_empty_string(self):
        assert _normalize_content("") == ""

    def test_preserves_meaningful_content(self):
        assert _normalize_content("Exit code 1") == "exit code 1"

    def test_complex_ansi(self):
        text = "\033[1;32mSuccess\033[0m and \033[31mfailure\033[0m"
        assert _normalize_content(text) == "success and failure"


# ── group_duplicates ────────────────────────────────────────────


class TestGroupDuplicates:
    def test_groups_identical_errors(self, storage):
        _seed_duplicates(storage)
        groups = storage.group_duplicates("proj-a", type="error")
        # Should have 2 groups: "uncommitted" (5) and "file not found" (3)
        assert len(groups) == 2
        counts = sorted([g.count for g in groups], reverse=True)
        assert counts == [5, 3]

    def test_group_contains_memory_ids(self, storage):
        _seed_duplicates(storage)
        groups = storage.group_duplicates("proj-a", type="error")
        big_group = max(groups, key=lambda g: g.count)
        assert len(big_group.memory_ids) == 5
        assert all(isinstance(mid, int) for mid in big_group.memory_ids)

    def test_group_has_first_and_last_seen(self, storage):
        _seed_duplicates(storage)
        groups = storage.group_duplicates("proj-a", type="error")
        for g in groups:
            assert g.first_seen is not None
            assert g.last_seen is not None

    def test_groups_decisions(self, storage):
        _seed_duplicates(storage)
        groups = storage.group_duplicates("proj-a", type="decision")
        # 2 groups: "Chose SQLite" (2) and "Use TDD" (1)
        assert len(groups) == 2
        counts = sorted([g.count for g in groups], reverse=True)
        assert counts == [2, 1]

    def test_all_types_when_type_is_none(self, storage):
        _seed_duplicates(storage)
        groups = storage.group_duplicates("proj-a")
        # Should include error, decision, file_change groups
        types_found = {g.type for g in groups}
        assert "error" in types_found
        assert "decision" in types_found

    def test_filters_by_project(self, storage):
        _seed_duplicates(storage)
        groups_a = storage.group_duplicates("proj-a", type="error")
        groups_b = storage.group_duplicates("proj-b", type="error")
        assert len(groups_a) == 2  # 2 distinct errors in proj-a
        assert len(groups_b) == 1  # 1 error in proj-b

    def test_empty_project(self, storage):
        groups = storage.group_duplicates("nonexistent")
        assert groups == []

    def test_memory_group_dataclass(self, storage):
        _seed_duplicates(storage)
        groups = storage.group_duplicates("proj-a", type="error")
        g = groups[0]
        assert isinstance(g, MemoryGroup)
        assert isinstance(g.content, str)
        assert isinstance(g.type, str)
        assert isinstance(g.count, int)
        assert isinstance(g.memory_ids, list)


# ── delete_batch ────────────────────────────────────────────────


class TestDeleteBatch:
    def test_deletes_multiple_ids(self, storage):
        ids = [
            storage.save("s1", "proj", "error", "err 1"),
            storage.save("s2", "proj", "error", "err 2"),
            storage.save("s3", "proj", "error", "err 3"),
        ]
        deleted = storage.delete_batch(ids[:2])
        assert deleted == 2
        # Third should still exist
        remaining = storage.recent("proj", limit=10)
        assert len(remaining) == 1
        assert remaining[0].id == ids[2]

    def test_returns_zero_for_empty_list(self, storage):
        assert storage.delete_batch([]) == 0

    def test_returns_zero_for_nonexistent_ids(self, storage):
        assert storage.delete_batch([999, 1000]) == 0

    def test_single_transaction(self, storage):
        """All deletes happen in one transaction."""
        ids = [
            storage.save("s1", "proj", "error", f"err {i}") for i in range(100)
        ]
        deleted = storage.delete_batch(ids)
        assert deleted == 100
        assert storage.recent("proj", limit=200) == []

    def test_fts5_index_updated(self, storage):
        """FTS5 index should be updated after batch delete."""
        storage.save("s1", "proj", "error", "unique searchable error content")
        mid = storage.save("s2", "proj", "error", "another error")
        # Search should find both
        assert len(storage.search("unique searchable")) == 1
        storage.delete_batch([mid])
        # Search should still find the first one
        assert len(storage.search("unique searchable")) == 1


# ── count_by_type ───────────────────────────────────────────────


class TestCountByType:
    def test_counts_all_types(self, storage):
        _seed_duplicates(storage)
        counts = storage.count_by_type("proj-a")
        assert counts["error"] == 8  # 5 + 3
        assert counts["decision"] == 3  # 2 + 1
        assert counts["file_change"] == 2

    def test_empty_project(self, storage):
        counts = storage.count_by_type("nonexistent")
        assert counts == {}

    def test_single_type(self, storage):
        storage.save("s1", "proj", "learning", "lesson 1")
        storage.save("s2", "proj", "learning", "lesson 2")
        counts = storage.count_by_type("proj")
        assert counts == {"learning": 2}
