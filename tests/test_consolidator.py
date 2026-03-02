"""Tests for the Consolidation pipeline — GROUP → ANALYZE → SAVE → CLEAN → AUDIT → REPORT."""

from __future__ import annotations

import math
from dataclasses import asdict
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from cc_memory.analyzer import AnalysisResult, BudgetExceededError
from cc_memory.consolidator import (
    Consolidator,
    ConsolidateOptions,
    ConsolidateReport,
    TYPE_WEIGHTS,
    decay_score,
)
from cc_memory.storage import Memory, Storage


# ── Fixtures ────────────────────────────────────────────────────


@pytest.fixture
def storage():
    """In-memory storage for tests."""
    s = Storage(":memory:")
    s.init_db()
    yield s
    s.close()


@pytest.fixture
def mock_analyzer():
    """Mock analyzer that returns predictable results."""
    analyzer = MagicMock()
    analyzer.api_calls_made = 0
    analyzer.max_api_calls = 15
    return analyzer


def _seed_errors(storage: Storage, count: int = 5, content: str = "Exit code 1\nUncommitted changes.") -> None:
    """Seed storage with duplicate errors."""
    for i in range(count):
        storage.save(f"sess-{i}", "proj-a", "error", content)


def _seed_mixed(storage: Storage) -> None:
    """Seed storage with mixed memory types for full pipeline testing."""
    # 5 identical errors (should trigger error → learning)
    for i in range(5):
        storage.save(f"sess-{i}", "proj-a", "error", "Exit code 1\nUncommitted changes.")
    # 3 identical errors (different content)
    for i in range(3):
        storage.save(f"sess-{i}", "proj-a", "error", "File not found: /tmp/missing.txt")
    # 6 file changes for the same file (should trigger hot zone)
    for i in range(6):
        storage.save(f"sess-{i}", "proj-a", "file_change", "Edited src/main.py: various changes")
    # 3 decisions (should trigger rule detection)
    for i in range(3):
        storage.save(f"sess-{i}", "proj-a", "decision", "Use SQLite for storage")
    # 2 unique learnings (should NOT be touched)
    storage.save("sess-1", "proj-a", "learning", "TDD works well for this project")
    storage.save("sess-2", "proj-a", "learning", "FTS5 handles search efficiently")


# ── ConsolidateOptions dataclass ───────────────────────────────


class TestConsolidateOptions:
    def test_defaults(self):
        opts = ConsolidateOptions()
        assert opts.decay_threshold == 0.1
        assert opts.max_api_calls == 15
        assert opts.dry_run is False

    def test_custom_values(self):
        opts = ConsolidateOptions(decay_threshold=0.05, max_api_calls=5, dry_run=True)
        assert opts.decay_threshold == 0.05
        assert opts.max_api_calls == 5
        assert opts.dry_run is True


# ── ConsolidateReport dataclass ────────────────────────────────


class TestConsolidateReport:
    def test_defaults(self):
        report = ConsolidateReport(
            duplicates_removed=10,
            learnings_created=3,
            patterns_found=2,
            suggestions_for_claude_md=["Always commit before deploy"],
            api_calls_used=4,
            stats_before={"error": 20, "decision": 5},
            stats_after={"error": 10, "decision": 5, "learning": 3},
        )
        assert report.duplicates_removed == 10
        assert report.learnings_created == 3
        assert len(report.suggestions_for_claude_md) == 1

    def test_to_dict(self):
        report = ConsolidateReport(
            duplicates_removed=0,
            learnings_created=0,
            patterns_found=0,
            suggestions_for_claude_md=[],
            api_calls_used=0,
            stats_before={},
            stats_after={},
        )
        d = asdict(report)
        assert "duplicates_removed" in d
        assert "stats_before" in d


# ── decay_score ────────────────────────────────────────────────


class TestDecayScore:
    def test_fresh_decision_has_max_score(self):
        """A decision created just now should have score ≈ 1.0."""
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        m = Memory(id=1, session_id="s", project="p", type="decision",
                   content="test", metadata=None, created_at=now)
        score = decay_score(m)
        assert 0.95 <= score <= 1.0

    def test_old_error_has_low_score(self):
        """A 100-day-old error should have very low score."""
        old = (datetime.utcnow() - timedelta(days=100)).strftime("%Y-%m-%d %H:%M:%S")
        m = Memory(id=1, session_id="s", project="p", type="error",
                   content="test", metadata=None, created_at=old)
        score = decay_score(m)
        assert score < 0.05

    def test_type_weights_applied(self):
        """Decision (weight=1.0) should score higher than error (weight=0.2) at same age."""
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        decision = Memory(id=1, session_id="s", project="p", type="decision",
                          content="test", metadata=None, created_at=now)
        error = Memory(id=2, session_id="s", project="p", type="error",
                       content="test", metadata=None, created_at=now)
        assert decay_score(decision) > decay_score(error)

    def test_recency_factor_at_23_days(self):
        """At 23 days, recency should be approximately 0.5."""
        age_23 = (datetime.utcnow() - timedelta(days=23)).strftime("%Y-%m-%d %H:%M:%S")
        m = Memory(id=1, session_id="s", project="p", type="decision",
                   content="test", metadata=None, created_at=age_23)
        score = decay_score(m)
        expected = 1.0 * math.exp(-0.03 * 23)
        assert abs(score - expected) < 0.05

    def test_all_type_weights_defined(self):
        """All valid memory types should have a weight."""
        from cc_memory.storage import VALID_TYPES
        for t in VALID_TYPES:
            assert t in TYPE_WEIGHTS

    def test_unknown_type_uses_default_weight(self):
        """Unknown types should use default weight of 0.3."""
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        m = Memory(id=1, session_id="s", project="p", type="brainstorm",
                   content="test", metadata=None, created_at=now)
        score = decay_score(m)
        assert abs(score - TYPE_WEIGHTS["brainstorm"]) < 0.05


# ── Consolidator.consolidate — end-to-end ──────────────────────


class TestConsolidateEndToEnd:
    def test_full_pipeline_with_duplicates(self, storage, mock_analyzer):
        """Full pipeline: seed duplicates → analyze → save learnings → clean → audit."""
        _seed_mixed(storage)
        stats_before = storage.count_by_type("proj-a")
        assert stats_before["error"] == 8

        # Mock analyzer to return good results for each analysis type
        mock_analyzer.analyze_group.side_effect = [
            # First group of errors (5 duplicates)
            AnalysisResult(
                content="Always commit before deploy",
                type="learning", confidence=0.9,
                source_ids=[1, 2, 3, 4, 5],
                suggestions=["Add to CLAUDE.md: always commit before deploy"],
            ),
            # Second group of errors (3 duplicates)
            AnalysisResult(
                content="Check file existence before operations",
                type="learning", confidence=0.85,
                source_ids=[6, 7, 8],
                suggestions=[],
            ),
            # File changes hot zone (6 duplicates)
            AnalysisResult(
                content="src/main.py is the hot zone",
                type="learning", confidence=0.9,
                source_ids=[9, 10, 11, 12, 13, 14],
                suggestions=["src/main.py is the primary development file"],
            ),
            # Decisions → rules (3 duplicates)
            AnalysisResult(
                content="Use SQLite for local storage",
                type="learning", confidence=0.92,
                source_ids=[15, 16, 17],
                suggestions=[],
            ),
        ]

        consolidator = Consolidator(storage, mock_analyzer)
        report = consolidator.consolidate("proj-a", ConsolidateOptions())

        # Verify learnings were created
        assert report.learnings_created > 0
        # Verify duplicates were removed
        assert report.duplicates_removed > 0
        # Verify suggestions collected
        assert len(report.suggestions_for_claude_md) >= 1
        # Verify stats tracked
        assert "error" in report.stats_before
        assert report.api_calls_used == mock_analyzer.api_calls_made

    def test_dry_run_does_not_modify_db(self, storage, mock_analyzer):
        """dry_run=True should analyze but not save or delete anything."""
        _seed_errors(storage, 5)
        count_before = len(storage.recent("proj-a", limit=100))

        mock_analyzer.analyze_group.return_value = AnalysisResult(
            content="lesson", type="learning", confidence=0.9,
            source_ids=[1, 2, 3, 4, 5], suggestions=[],
        )

        consolidator = Consolidator(storage, mock_analyzer)
        report = consolidator.consolidate("proj-a", ConsolidateOptions(dry_run=True))

        count_after = len(storage.recent("proj-a", limit=100))
        assert count_after == count_before
        # Report should still show what WOULD happen
        assert report.duplicates_removed > 0 or report.learnings_created > 0

    def test_empty_project_returns_empty_report(self, storage, mock_analyzer):
        """Consolidating an empty project should return zeros."""
        consolidator = Consolidator(storage, mock_analyzer)
        report = consolidator.consolidate("nonexistent", ConsolidateOptions())

        assert report.duplicates_removed == 0
        assert report.learnings_created == 0
        assert report.patterns_found == 0
        assert report.suggestions_for_claude_md == []
        assert mock_analyzer.analyze_group.call_count == 0


# ── Transformation rules ───────────────────────────────────────


class TestTransformationRules:
    def test_errors_to_learning_threshold(self, storage, mock_analyzer):
        """Only groups with 3+ duplicates should trigger analysis."""
        # 2 identical errors — below threshold
        storage.save("s1", "proj-a", "error", "Some error")
        storage.save("s2", "proj-a", "error", "Some error")

        mock_analyzer.analyze_group.return_value = AnalysisResult(
            content="lesson", type="learning", confidence=0.9,
            source_ids=[], suggestions=[],
        )

        consolidator = Consolidator(storage, mock_analyzer)
        report = consolidator.consolidate("proj-a", ConsolidateOptions())

        # Should NOT analyze groups below threshold
        assert mock_analyzer.analyze_group.call_count == 0

    def test_errors_above_threshold_analyzed(self, storage, mock_analyzer):
        """Groups with 3+ duplicates should be analyzed."""
        _seed_errors(storage, 4)

        mock_analyzer.analyze_group.return_value = AnalysisResult(
            content="Always commit first",
            type="learning", confidence=0.9,
            source_ids=[1, 2, 3, 4], suggestions=[],
        )

        consolidator = Consolidator(storage, mock_analyzer)
        report = consolidator.consolidate("proj-a", ConsolidateOptions())

        assert mock_analyzer.analyze_group.call_count >= 1

    def test_file_changes_hot_zone_threshold(self, storage, mock_analyzer):
        """File changes need 5+ duplicates for hot zone analysis."""
        # 4 identical file changes — below threshold
        for i in range(4):
            storage.save(f"s{i}", "proj-a", "file_change", "Edited src/main.py")

        mock_analyzer.analyze_group.return_value = AnalysisResult(
            content="hot zone", type="learning", confidence=0.9,
            source_ids=[], suggestions=[],
        )

        consolidator = Consolidator(storage, mock_analyzer)
        report = consolidator.consolidate("proj-a", ConsolidateOptions())

        # file_change group has 4 < 5, should NOT analyze
        assert mock_analyzer.analyze_group.call_count == 0

    def test_decisions_analyzed_for_rules(self, storage, mock_analyzer):
        """Decision groups with 3+ should be analyzed for rules."""
        for i in range(3):
            storage.save(f"s{i}", "proj-a", "decision", "Use TDD for all features")

        mock_analyzer.analyze_group.return_value = AnalysisResult(
            content="TDD is the standard",
            type="learning", confidence=0.92,
            source_ids=[1, 2, 3],
            suggestions=["Always use TDD"],
        )

        consolidator = Consolidator(storage, mock_analyzer)
        report = consolidator.consolidate("proj-a", ConsolidateOptions())

        assert mock_analyzer.analyze_group.call_count >= 1


# ── Cleanup ────────────────────────────────────────────────────


class TestCleanup:
    def test_processed_duplicates_deleted(self, storage, mock_analyzer):
        """After analysis, duplicate errors should be removed (keeping learnings)."""
        _seed_errors(storage, 5)

        mock_analyzer.analyze_group.return_value = AnalysisResult(
            content="Always commit first",
            type="learning", confidence=0.9,
            source_ids=[1, 2, 3, 4, 5], suggestions=[],
        )

        consolidator = Consolidator(storage, mock_analyzer)
        report = consolidator.consolidate("proj-a", ConsolidateOptions())

        # Original 5 errors should be removed
        remaining_errors = storage.by_project("proj-a", type="error")
        assert len(remaining_errors) == 0
        # New learning should exist
        learnings = storage.by_project("proj-a", type="learning")
        assert len(learnings) >= 1

    def test_low_score_memories_cleaned(self, storage, mock_analyzer):
        """Memories below decay threshold should be removed."""
        # Create old errors (100+ days old)
        for i in range(3):
            storage.save(f"s{i}", "proj-a", "error", f"Old error {i}")

        # Manually set created_at to 120 days ago
        old_date = (datetime.utcnow() - timedelta(days=120)).strftime("%Y-%m-%d %H:%M:%S")
        storage.conn.execute(
            "UPDATE memories SET created_at = ? WHERE project = ?",
            (old_date, "proj-a"),
        )
        storage.conn.commit()

        # No analysis expected (all unique), but decay cleanup should happen
        consolidator = Consolidator(storage, mock_analyzer)
        report = consolidator.consolidate("proj-a", ConsolidateOptions(decay_threshold=0.1))

        # Very old errors (120 days, weight 0.2) → score ≈ 0.2 * exp(-3.6) ≈ 0.005 < 0.1
        # All errors should be deleted; only the audit log learning remains
        remaining_errors = storage.by_project("proj-a", type="error")
        assert len(remaining_errors) == 0
        assert report.duplicates_removed >= 3


# ── Audit log ──────────────────────────────────────────────────


class TestAuditLog:
    def test_consolidation_report_saved_as_learning(self, storage, mock_analyzer):
        """Each consolidation run should save an audit record as a learning."""
        _seed_errors(storage, 5)

        mock_analyzer.analyze_group.return_value = AnalysisResult(
            content="lesson", type="learning", confidence=0.9,
            source_ids=[1, 2, 3, 4, 5], suggestions=[],
        )

        consolidator = Consolidator(storage, mock_analyzer)
        consolidator.consolidate("proj-a", ConsolidateOptions())

        # Find audit record (has "report" key in metadata, vs analysis learnings that have "analysis_type")
        learnings = storage.by_project("proj-a", type="learning")
        audit_records = [
            m for m in learnings
            if m.metadata and m.metadata.get("source") == "consolidation" and "report" in m.metadata
        ]
        assert len(audit_records) == 1
        assert "report" in audit_records[0].metadata

    def test_dry_run_no_audit_log(self, storage, mock_analyzer):
        """dry_run should NOT save audit log."""
        _seed_errors(storage, 5)

        mock_analyzer.analyze_group.return_value = AnalysisResult(
            content="lesson", type="learning", confidence=0.9,
            source_ids=[1, 2, 3, 4, 5], suggestions=[],
        )

        consolidator = Consolidator(storage, mock_analyzer)
        consolidator.consolidate("proj-a", ConsolidateOptions(dry_run=True))

        learnings = storage.by_project("proj-a", type="learning")
        audit_records = [
            m for m in learnings
            if m.metadata and m.metadata.get("source") == "consolidation"
        ]
        assert len(audit_records) == 0


# ── Budget handling ────────────────────────────────────────────


class TestBudgetInPipeline:
    def test_budget_exceeded_returns_partial_report(self, storage, mock_analyzer):
        """If budget is exceeded mid-pipeline, return partial results."""
        _seed_mixed(storage)

        call_count = 0

        def limited_analyze(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count > 2:
                raise BudgetExceededError("Budget exceeded")
            return AnalysisResult(
                content="lesson", type="learning", confidence=0.9,
                source_ids=[], suggestions=[],
            )

        mock_analyzer.analyze_group.side_effect = limited_analyze

        consolidator = Consolidator(storage, mock_analyzer)
        report = consolidator.consolidate("proj-a", ConsolidateOptions())

        # Should NOT raise — returns partial report
        assert report is not None
        # Should have processed some but not all
        assert report.learnings_created <= 2
