"""Consolidation pipeline — transforms raw memories into structured knowledge.

Pipeline: GROUP → ANALYZE → SAVE → CLEAN → AUDIT → REPORT
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from cc_memory.analyzer import AnalysisResult, Analyzer, BudgetExceededError
from cc_memory.storage import Memory, MemoryGroup, Storage

logger = logging.getLogger(__name__)

# ── Decay scoring ──────────────────────────────────────────────

TYPE_WEIGHTS: dict[str, float] = {
    "decision": 1.0,
    "learning": 0.9,
    "task": 0.8,
    "brainstorm": 0.5,
    "file_change": 0.3,
    "error": 0.2,
}

# Minimum duplicates to trigger analysis per type
_MIN_DUPLICATES: dict[str, int] = {
    "error": 3,
    "file_change": 5,
    "decision": 3,
}

# Analysis type mapping for each memory type
_ANALYSIS_TYPE: dict[str, str] = {
    "error": "error_to_learning",
    "file_change": "file_changes_to_hot_zones",
    "decision": "decisions_to_rules",
}


def decay_score(memory: Memory) -> float:
    """Compute decay score on-the-fly: type_weight * recency_factor.

    recency_factor = exp(-0.03 * age_days)
    ~0.5 at 23 days, ~0.05 at 100 days.
    """
    try:
        created = datetime.strptime(memory.created_at, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return 0.0
    age_days = max(0, (datetime.now(timezone.utc).replace(tzinfo=None) - created).days)
    recency = math.exp(-0.03 * age_days)
    weight = TYPE_WEIGHTS.get(memory.type, 0.3)
    return weight * recency


# ── Dataclasses ────────────────────────────────────────────────


@dataclass
class ConsolidateOptions:
    """Options for consolidation pipeline."""

    decay_threshold: float = 0.1
    max_api_calls: int = 15
    dry_run: bool = False


@dataclass
class ConsolidateReport:
    """Report from a consolidation run."""

    duplicates_removed: int
    learnings_created: int
    patterns_found: int
    suggestions_for_claude_md: list[str]
    api_calls_used: int
    stats_before: dict[str, int]
    stats_after: dict[str, int]


# ── Consolidator ───────────────────────────────────────────────


class Consolidator:
    """Orchestrates the consolidation pipeline: GROUP → ANALYZE → SAVE → CLEAN → AUDIT → REPORT."""

    def __init__(self, storage: Storage, analyzer: Analyzer) -> None:
        self._storage = storage
        self._analyzer = analyzer

    def consolidate(
        self, project: str, options: ConsolidateOptions,
    ) -> ConsolidateReport:
        """Run the full consolidation pipeline for a project."""
        stats_before = self._storage.count_by_type(project)

        if not stats_before:
            return ConsolidateReport(
                duplicates_removed=0,
                learnings_created=0,
                patterns_found=0,
                suggestions_for_claude_md=[],
                api_calls_used=0,
                stats_before={},
                stats_after={},
            )

        # ── GROUP ──────────────────────────────────────────
        groups = self._storage.group_duplicates(project)

        # ── ANALYZE + SAVE + CLEAN ─────────────────────────
        learnings_created = 0
        duplicates_removed = 0
        patterns_found = 0
        all_suggestions: list[str] = []
        ids_to_delete: list[int] = []

        for group in groups:
            analysis_type = _ANALYSIS_TYPE.get(group.type)
            if not analysis_type:
                continue

            min_count = _MIN_DUPLICATES.get(group.type, 3)
            if group.count < min_count:
                continue

            # Get full memory objects for the group
            memories = self._fetch_memories_by_ids(group.memory_ids)
            if not memories:
                continue

            try:
                result = self._analyzer.analyze_group(memories, analysis_type)
            except BudgetExceededError:
                logger.warning("API budget exceeded during consolidation")
                break

            if result.confidence == 0.0 and not result.content:
                continue

            patterns_found += 1
            all_suggestions.extend(result.suggestions)

            if not options.dry_run:
                # SAVE: create new learning from analysis
                self._storage.save(
                    session_id="consolidation",
                    project=project,
                    type="learning",
                    content=result.content,
                    metadata={
                        "source": "consolidation",
                        "analysis_type": analysis_type,
                        "source_count": group.count,
                        "confidence": result.confidence,
                    },
                )
                learnings_created += 1

            # Collect duplicate IDs for cleanup — keep first (oldest) as evidence
            ids_to_delete.extend(group.memory_ids[1:])
            duplicates_removed += group.count - 1

        # ── CLEAN (batch delete analyzed duplicates first) ──
        if not options.dry_run and ids_to_delete:
            self._storage.delete_batch(ids_to_delete)

        # ── DECAY CLEANUP (after batch delete to avoid double-counting) ──
        decay_deleted = self._cleanup_low_score(project, options)
        duplicates_removed += decay_deleted

        # ── AUDIT ──────────────────────────────────────────
        stats_after = self._storage.count_by_type(project)

        report = ConsolidateReport(
            duplicates_removed=duplicates_removed,
            learnings_created=learnings_created,
            patterns_found=patterns_found,
            suggestions_for_claude_md=all_suggestions,
            api_calls_used=self._analyzer.api_calls_made,
            stats_before=stats_before,
            stats_after=stats_after,
        )

        if not options.dry_run:
            self._save_audit_log(project, report)

        return report

    def _fetch_memories_by_ids(self, memory_ids: list[int]) -> list[Memory]:
        """Fetch full Memory objects by their IDs."""
        return self._storage.get_by_ids(memory_ids)

    def _cleanup_low_score(
        self, project: str, options: ConsolidateOptions,
    ) -> int:
        """Delete memories below decay threshold. Returns count deleted."""
        # Only clean error and file_change types (preserve decisions, learnings, tasks)
        cleanable_types = ("error", "file_change")
        deleted = 0

        for mem_type in cleanable_types:
            memories = self._storage.by_project(project, type=mem_type, limit=500)
            low_score_ids = [
                m.id for m in memories
                if decay_score(m) < options.decay_threshold
            ]
            if low_score_ids and not options.dry_run:
                deleted += self._storage.delete_batch(low_score_ids)
            elif low_score_ids:
                deleted += len(low_score_ids)  # dry_run: count what would be deleted

        return deleted

    def _save_audit_log(self, project: str, report: ConsolidateReport) -> None:
        """Save consolidation report as a learning for traceability."""
        summary = (
            f"Consolidation: {report.duplicates_removed} duplicates removed, "
            f"{report.learnings_created} learnings created, "
            f"{report.patterns_found} patterns found"
        )
        self._storage.save(
            session_id="consolidation",
            project=project,
            type="learning",
            content=summary,
            metadata={
                "source": "consolidation",
                "report": asdict(report),
            },
        )
