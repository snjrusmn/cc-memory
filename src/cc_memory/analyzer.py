"""AI Analyzer — Claude API integration with Bouncer Rule for memory consolidation."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

import anthropic

from cc_memory.storage import Memory

logger = logging.getLogger(__name__)

SONNET_MODEL = "claude-sonnet-4-20250514"
OPUS_MODEL = "claude-opus-4-20250514"
BOUNCER_THRESHOLD = 0.8
MAX_RETRIES = 3


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    """Result of AI analysis on a group of memories."""

    content: str
    type: str
    confidence: float
    source_ids: list[int]
    suggestions: list[str]


class BudgetExceededError(Exception):
    """Raised when API call budget is exhausted."""


# ── Prompt templates ────────────────────────────────────────────

_PROMPTS: dict[str, str] = {
    "error_to_learning": (
        "Analyze these recurring errors from a development project.\n"
        "Extract a concise lesson learned (1-2 sentences).\n"
        'Return JSON: {{"lesson": "...", "confidence": 0.0-1.0, "suggestion": "..."}}\n\n'
        "Errors (occurred {count} times):\n{content}"
    ),
    "file_changes_to_hot_zones": (
        "These files were modified frequently in recent sessions.\n"
        "Identify the hot zones (most active areas) and what work is happening.\n"
        'Return JSON: {{"hot_zones": [{{"file": "...", "changes": N, "insight": "..."}}], "confidence": 0.0-1.0}}\n\n'
        "File changes:\n{content}"
    ),
    "decisions_to_rules": (
        "Analyze these architectural/design decisions from a project.\n"
        "Identify patterns or recurring preferences that could become project rules.\n"
        'Return JSON: {{"rules": [{{"rule": "...", "evidence": "...", "strength": N}}], "confidence": 0.0-1.0}}\n\n'
        "Decisions:\n{content}"
    ),
}

# ── Response parsers ────────────────────────────────────────────

def _parse_error_learning(data: dict, source_ids: list[int]) -> AnalysisResult:
    return AnalysisResult(
        content=data.get("lesson", ""),
        type="learning",
        confidence=data.get("confidence", 0.0),
        source_ids=source_ids,
        suggestions=[s for s in [data.get("suggestion", "")] if s],
    )


def _parse_hot_zones(data: dict, source_ids: list[int]) -> AnalysisResult:
    zones = data.get("hot_zones", [])
    content = "; ".join(
        f"{z.get('file', '?')}: {z.get('insight', '?')}" for z in zones
    )
    return AnalysisResult(
        content=content or "No hot zones identified",
        type="learning",
        confidence=data.get("confidence", 0.0),
        source_ids=source_ids,
        suggestions=[],
    )


def _parse_rules(data: dict, source_ids: list[int]) -> AnalysisResult:
    rules = data.get("rules", [])
    content = "; ".join(r.get("rule", "?") for r in rules)
    suggestions = [
        r["rule"] for r in rules if r.get("strength", 0) >= 5
    ]
    return AnalysisResult(
        content=content or "No rules identified",
        type="learning",
        confidence=data.get("confidence", 0.0),
        source_ids=source_ids,
        suggestions=suggestions,
    )


_PARSERS: dict[str, Any] = {
    "error_to_learning": _parse_error_learning,
    "file_changes_to_hot_zones": _parse_hot_zones,
    "decisions_to_rules": _parse_rules,
}


# ── Analyzer ────────────────────────────────────────────────────

class Analyzer:
    """Claude API analyzer with Bouncer Rule (Sonnet → Opus escalation)."""

    def __init__(
        self,
        api_key: str | None = None,
        max_api_calls: int = 15,
    ) -> None:
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise ValueError(
                "API key required. Set ANTHROPIC_API_KEY env var or pass api_key."
            )
        self._client = anthropic.Anthropic(api_key=key)
        self.max_api_calls = max_api_calls
        self.api_calls_made = 0

    def analyze_group(
        self,
        memories: list[Memory],
        analysis_type: str,
    ) -> AnalysisResult:
        """Analyze a group of memories using Bouncer Rule (Sonnet → Opus)."""
        if not memories:
            return AnalysisResult("", "learning", 0.0, [], [])

        if analysis_type not in _PROMPTS:
            return AnalysisResult("", "learning", 0.0, [], [])

        source_ids = [m.id for m in memories]
        content = "\n".join(m.content for m in memories)
        prompt = _PROMPTS[analysis_type].format(
            count=len(memories), content=content,
        )

        # Sonnet first
        data = self._call_api(SONNET_MODEL, prompt)
        parser = _PARSERS[analysis_type]
        result = parser(data, source_ids)

        # Bouncer Rule: escalate to Opus if confidence < threshold
        if result.confidence < BOUNCER_THRESHOLD:
            data = self._call_api(OPUS_MODEL, prompt)
            result = parser(data, source_ids)

        return result

    def _call_api(self, model: str, prompt: str) -> dict:
        """Call Claude API with budget tracking and retry logic."""
        if self.api_calls_made >= self.max_api_calls:
            raise BudgetExceededError(
                f"API call budget exceeded: {self.max_api_calls} calls used"
            )

        self.api_calls_made += 1

        for attempt in range(MAX_RETRIES):
            try:
                response = self._client.messages.create(
                    model=model,
                    max_tokens=1024,
                    messages=[{"role": "user", "content": prompt}],
                )
                text = response.content[0].text
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    logger.warning("Invalid JSON from %s: %s", model, text[:200])
                    return {}
            except anthropic.RateLimitError:
                if attempt < MAX_RETRIES - 1:
                    time.sleep(2**attempt)
                else:
                    raise

        return {}  # unreachable, but makes type checker happy
