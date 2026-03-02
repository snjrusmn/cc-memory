"""Tests for the Analyzer module — Claude API integration with Bouncer Rule."""

from __future__ import annotations

import json
from dataclasses import asdict
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from cc_memory.analyzer import (
    Analyzer,
    AnalysisResult,
    BudgetExceededError,
)
from cc_memory.storage import Memory


def _make_memory(
    id: int = 1,
    type: str = "error",
    content: str = "test error",
    project: str = "test-project",
) -> Memory:
    return Memory(
        id=id,
        session_id="sess-1",
        project=project,
        type=type,
        content=content,
        metadata=None,
        created_at="2026-03-01 10:00:00",
    )


# ── Initialization ──────────────────────────────────────────────


class TestAnalyzerInit:
    def test_init_with_explicit_api_key(self):
        analyzer = Analyzer(api_key="sk-test-key", max_api_calls=10)
        assert analyzer.max_api_calls == 10
        assert analyzer.api_calls_made == 0

    def test_init_reads_env_var(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-env")
        analyzer = Analyzer()
        assert analyzer.api_calls_made == 0

    def test_init_no_key_raises(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
            Analyzer()

    def test_default_max_api_calls(self):
        analyzer = Analyzer(api_key="sk-test")
        assert analyzer.max_api_calls == 15


# ── AnalysisResult dataclass ────────────────────────────────────


class TestAnalysisResult:
    def test_dataclass_fields(self):
        result = AnalysisResult(
            content="Always commit before deploy",
            type="learning",
            confidence=0.95,
            source_ids=[1, 2, 3],
            suggestions=["Add to CLAUDE.md"],
        )
        assert result.content == "Always commit before deploy"
        assert result.type == "learning"
        assert result.confidence == 0.95
        assert result.source_ids == [1, 2, 3]
        assert result.suggestions == ["Add to CLAUDE.md"]

    def test_to_dict(self):
        result = AnalysisResult(
            content="test", type="learning", confidence=0.9,
            source_ids=[1], suggestions=[],
        )
        d = asdict(result)
        assert d["content"] == "test"
        assert d["confidence"] == 0.9


# ── Bouncer Rule ────────────────────────────────────────────────


class TestBouncerRule:
    def _mock_api_response(self, content: str):
        """Create a mock API response matching Anthropic SDK structure."""
        mock_response = MagicMock()
        mock_block = MagicMock()
        mock_block.text = content
        mock_response.content = [mock_block]
        return mock_response

    def test_sonnet_success_no_escalation(self):
        """When Sonnet returns confidence >= 0.8, no Opus call."""
        analyzer = Analyzer(api_key="sk-test")
        sonnet_response = self._mock_api_response(
            json.dumps({"lesson": "Always commit first", "confidence": 0.9, "suggestion": ""})
        )
        analyzer._client = MagicMock()
        analyzer._client.messages.create.return_value = sonnet_response

        result = analyzer.analyze_group(
            [_make_memory()], analysis_type="error_to_learning"
        )

        assert result.confidence >= 0.8
        assert analyzer.api_calls_made == 1
        # Should NOT call Opus
        assert analyzer._client.messages.create.call_count == 1
        call_args = analyzer._client.messages.create.call_args
        assert "sonnet" in call_args.kwargs.get("model", "")

    def test_opus_escalation_on_low_confidence(self):
        """When Sonnet returns confidence < 0.8, escalates to Opus."""
        analyzer = Analyzer(api_key="sk-test")
        sonnet_response = self._mock_api_response(
            json.dumps({"lesson": "Maybe something", "confidence": 0.5, "suggestion": ""})
        )
        opus_response = self._mock_api_response(
            json.dumps({"lesson": "Definitely commit first", "confidence": 0.95, "suggestion": "Add to CLAUDE.md"})
        )
        analyzer._client = MagicMock()
        analyzer._client.messages.create.side_effect = [sonnet_response, opus_response]

        result = analyzer.analyze_group(
            [_make_memory()], analysis_type="error_to_learning"
        )

        assert result.confidence == 0.95
        assert analyzer.api_calls_made == 2
        calls = analyzer._client.messages.create.call_args_list
        assert "sonnet" in calls[0].kwargs.get("model", "")
        assert "opus" in calls[1].kwargs.get("model", "")

    def test_sonnet_only_when_confidence_exactly_0_8(self):
        """Confidence == 0.8 should NOT escalate (threshold is <0.8)."""
        analyzer = Analyzer(api_key="sk-test")
        response = self._mock_api_response(
            json.dumps({"lesson": "Good enough", "confidence": 0.8, "suggestion": ""})
        )
        analyzer._client = MagicMock()
        analyzer._client.messages.create.return_value = response

        result = analyzer.analyze_group(
            [_make_memory()], analysis_type="error_to_learning"
        )

        assert result.confidence == 0.8
        assert analyzer.api_calls_made == 1


# ── API Budget ──────────────────────────────────────────────────


class TestApiBudget:
    def _mock_response(self, confidence=0.9):
        mock_response = MagicMock()
        mock_block = MagicMock()
        mock_block.text = json.dumps(
            {"lesson": "test", "confidence": confidence, "suggestion": ""}
        )
        mock_response.content = [mock_block]
        return mock_response

    def test_budget_increments_per_call(self):
        analyzer = Analyzer(api_key="sk-test", max_api_calls=5)
        analyzer._client = MagicMock()
        analyzer._client.messages.create.return_value = self._mock_response()

        analyzer.analyze_group([_make_memory()], "error_to_learning")
        assert analyzer.api_calls_made == 1

        analyzer.analyze_group([_make_memory()], "error_to_learning")
        assert analyzer.api_calls_made == 2

    def test_budget_exceeded_raises(self):
        analyzer = Analyzer(api_key="sk-test", max_api_calls=1)
        analyzer._client = MagicMock()
        analyzer._client.messages.create.return_value = self._mock_response()

        # First call succeeds
        analyzer.analyze_group([_make_memory()], "error_to_learning")
        assert analyzer.api_calls_made == 1

        # Second call exceeds budget
        with pytest.raises(BudgetExceededError, match="1"):
            analyzer.analyze_group([_make_memory()], "error_to_learning")

    def test_budget_counts_escalation_as_two(self):
        """Bouncer Rule escalation uses 2 API calls from budget."""
        analyzer = Analyzer(api_key="sk-test", max_api_calls=3)
        low_confidence = MagicMock()
        low_confidence.content = [MagicMock(text=json.dumps(
            {"lesson": "unsure", "confidence": 0.5, "suggestion": ""}
        ))]
        high_confidence = MagicMock()
        high_confidence.content = [MagicMock(text=json.dumps(
            {"lesson": "sure", "confidence": 0.95, "suggestion": ""}
        ))]
        analyzer._client = MagicMock()
        analyzer._client.messages.create.side_effect = [low_confidence, high_confidence]

        analyzer.analyze_group([_make_memory()], "error_to_learning")
        assert analyzer.api_calls_made == 2  # Sonnet + Opus


# ── Rate Limiting ───────────────────────────────────────────────


class TestRateLimiting:
    def test_retries_on_rate_limit(self):
        import anthropic

        analyzer = Analyzer(api_key="sk-test")

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps(
            {"lesson": "test", "confidence": 0.9, "suggestion": ""}
        ))]

        rate_limit_error = anthropic.RateLimitError(
            message="rate limited",
            response=MagicMock(status_code=429),
            body=None,
        )

        analyzer._client = MagicMock()
        analyzer._client.messages.create.side_effect = [
            rate_limit_error,
            mock_response,  # succeeds on retry
        ]

        with patch("cc_memory.analyzer.time.sleep") as mock_sleep:
            result = analyzer.analyze_group([_make_memory()], "error_to_learning")

        assert result.confidence == 0.9
        mock_sleep.assert_called_once_with(1)  # first backoff = 2^0 = 1

    def test_max_retries_exceeded(self):
        import anthropic

        analyzer = Analyzer(api_key="sk-test")
        rate_limit_error = anthropic.RateLimitError(
            message="rate limited",
            response=MagicMock(status_code=429),
            body=None,
        )
        analyzer._client = MagicMock()
        analyzer._client.messages.create.side_effect = rate_limit_error

        with patch("cc_memory.analyzer.time.sleep"):
            with pytest.raises(anthropic.RateLimitError):
                analyzer.analyze_group([_make_memory()], "error_to_learning")


# ── Error Handling ──────────────────────────────────────────────


class TestErrorHandling:
    def test_invalid_json_response(self):
        analyzer = Analyzer(api_key="sk-test")
        bad_response = MagicMock()
        bad_response.content = [MagicMock(text="not valid json {{{")]
        analyzer._client = MagicMock()
        analyzer._client.messages.create.return_value = bad_response

        result = analyzer.analyze_group([_make_memory()], "error_to_learning")
        # Should return a result with low confidence rather than crash
        assert result.confidence == 0.0

    def test_missing_fields_in_response(self):
        analyzer = Analyzer(api_key="sk-test")
        partial_response = MagicMock()
        partial_response.content = [MagicMock(text=json.dumps({"lesson": "test"}))]
        analyzer._client = MagicMock()
        analyzer._client.messages.create.return_value = partial_response

        result = analyzer.analyze_group([_make_memory()], "error_to_learning")
        assert result.content == "test"
        assert result.confidence == 0.0  # missing confidence defaults to 0.0

    def test_empty_memories_list(self):
        analyzer = Analyzer(api_key="sk-test")
        result = analyzer.analyze_group([], "error_to_learning")
        assert result.confidence == 0.0
        assert analyzer.api_calls_made == 0  # no API call for empty input


# ── Analysis Types ──────────────────────────────────────────────


class TestAnalysisTypes:
    def _setup_analyzer(self, response_json: dict) -> Analyzer:
        analyzer = Analyzer(api_key="sk-test")
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps(response_json))]
        analyzer._client = MagicMock()
        analyzer._client.messages.create.return_value = mock_response
        return analyzer

    def test_error_to_learning(self):
        analyzer = self._setup_analyzer({
            "lesson": "Always commit before deploy",
            "confidence": 0.9,
            "suggestion": "Add to CLAUDE.md",
        })
        result = analyzer.analyze_group(
            [_make_memory(type="error", content="Uncommitted changes")],
            "error_to_learning",
        )
        assert result.type == "learning"
        assert "commit" in result.content.lower()

    def test_file_changes_to_hot_zones(self):
        analyzer = self._setup_analyzer({
            "hot_zones": [{"file": "Finance.tsx", "changes": 40, "insight": "Main dev file"}],
            "confidence": 0.85,
        })
        result = analyzer.analyze_group(
            [_make_memory(type="file_change", content="Edited Finance.tsx")],
            "file_changes_to_hot_zones",
        )
        assert result.type == "learning"
        assert result.confidence == 0.85

    def test_decisions_to_rules(self):
        analyzer = self._setup_analyzer({
            "rules": [{"rule": "Use SQLite for local storage", "evidence": "3 projects", "strength": 5}],
            "confidence": 0.92,
        })
        result = analyzer.analyze_group(
            [_make_memory(type="decision", content="Chose SQLite")],
            "decisions_to_rules",
        )
        assert result.type == "learning"
        assert result.confidence == 0.92

    def test_unknown_analysis_type_returns_empty(self):
        analyzer = Analyzer(api_key="sk-test")
        result = analyzer.analyze_group([_make_memory()], "unknown_type")
        assert result.confidence == 0.0
        assert analyzer.api_calls_made == 0
