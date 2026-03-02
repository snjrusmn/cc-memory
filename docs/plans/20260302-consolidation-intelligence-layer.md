# CC-Memory: Consolidation & Intelligence Layer

## Overview
- Add `memory_consolidate` MCP tool that transforms raw memories into structured knowledge
- AI-powered analysis (Sonnet, Opus fallback via Bouncer Rule) extracts lessons from errors, patterns from repeated actions, rules from decisions, hot zones from file changes
- Results saved as learnings in DB + suggestions for CLAUDE.md for strong patterns (5+ occurrences)
- Includes Smarter SessionStart (balanced type sampling instead of blind "recent 20")
- Includes decay scoring for prioritizing valuable memories over noise
- Add `memory_stats` lightweight tool for quick DB overview without API calls

## Context (from discovery)
- **Current state:** 2982 memories (1571 file_change, 533 error, 282 task, 150 decision, 10 learning)
- **Problem:** SessionStart grabs last 20 records regardless of type — often all errors
- **Problem:** 18% of memories are duplicate/similar errors (noise)
- **No Anthropic SDK** currently — needs to be added as dependency
- **Files involved:**
  - `src/cc_memory/server.py` — add new MCP tools (175 lines, FastMCP pattern)
  - `src/cc_memory/storage.py` — add consolidation queries + delete_batch (247 lines)
  - `src/cc_memory/hooks/session_start.py` — smarter type-balanced retrieval (112 lines)
  - New: `src/cc_memory/consolidator.py` — AI analysis pipeline
  - New: `src/cc_memory/analyzer.py` — Claude API integration with Bouncer Rule

## Development Approach
- **Testing approach**: TDD (tests first)
- Complete each task fully before moving to the next
- Make small, focused changes
- **CRITICAL: every task MUST include new/updated tests** for code changes
- **CRITICAL: all tests must pass before starting next task**
- **CRITICAL: update this plan file when scope changes during implementation**
- Run tests after each change: `cd /Users/sanjarusmanov/Documents/AI_PROJECTS/CC-Memory && uv run pytest tests/ -v`
- Maintain backward compatibility with existing 158 tests

## Testing Strategy
- **Unit tests**: required for every task — mock Claude API calls, test grouping/normalization logic
- **Integration tests**: test full consolidation pipeline with in-memory SQLite
- Mock `anthropic.Anthropic` client in tests (no real API calls in CI)

## Progress Tracking
- Mark completed items with `[x]` immediately when done
- Add newly discovered tasks with + prefix
- Document issues/blockers with !! prefix
- Update plan if implementation deviates from original scope

## Implementation Steps

### Task 1: Add Anthropic SDK dependency and analyzer module

**Files:**
- Modify: `pyproject.toml`
- Create: `src/cc_memory/analyzer.py`
- Create: `tests/test_analyzer.py`

- [ ] Add `anthropic>=0.40,<1.0` to dependencies in pyproject.toml
- [ ] Run `uv sync` to install
- [ ] Write tests for `Analyzer` class: initialization, model selection, API call structure
- [ ] Write tests for Bouncer Rule: Sonnet default, Opus escalation when confidence < 0.8
- [ ] Write tests for API budget: `max_api_calls` limit respected, counter incremented per call
- [ ] Write tests for rate limiting: exponential backoff on 429 errors
- [ ] Create `analyzer.py` with `Analyzer` class:
  - `__init__(self, api_key: str | None = None)` — reads `ANTHROPIC_API_KEY` env var
  - `analyze_group(memories: list[Memory], analysis_type: str) -> AnalysisResult`
  - `AnalysisResult` dataclass: `content: str, type: str, confidence: float, source_ids: list[int], suggestions: list[str]`
  - Bouncer Rule: Sonnet first → if confidence < 0.8 → Opus re-analysis
  - `api_calls_made: int` counter, raises `BudgetExceededError` when `max_api_calls` reached
  - Exponential backoff on 429 (1s, 2s, 4s, max 3 retries)
- [ ] Write tests for error handling (API timeout, missing key, invalid response, budget exceeded)
- [ ] Run tests — must pass before task 2

### Task 2: Add duplicate grouping and batch operations to storage layer

**Files:**
- Modify: `src/cc_memory/storage.py`
- Create: `tests/test_grouping.py`

- [ ] Write tests for `group_duplicates(project, type)` method — exact match after normalization
- [ ] Write tests for content normalization (strip ANSI codes, collapse whitespace, strip truncation `... [truncated]`)
- [ ] Write tests for `delete_batch(memory_ids: list[int]) -> int` — single transaction, returns count
- [ ] Write tests for `count_by_type(project: str) -> dict[str, int]` stats query
- [ ] Write tests for `find_below_threshold(project, score_fn, threshold) -> list[Memory]` — decay filtering
- [ ] Implement `_normalize_content(content: str) -> str` — strip ANSI, collapse whitespace, lowercase
- [ ] Implement `group_duplicates(project: str, type: str | None = None) -> list[MemoryGroup]` in Storage:
  - Groups memories with identical normalized content
  - `MemoryGroup` dataclass: `content: str, type: str, count: int, memory_ids: list[int], first_seen: str, last_seen: str`
  - No fuzzy matching — exact match only (semantic similarity deferred to future embeddings)
- [ ] Implement `delete_batch(memory_ids: list[int]) -> int` — single transaction DELETE
- [ ] Implement `count_by_type(project: str) -> dict[str, int]`
- [ ] Run tests — must pass before task 3

### Task 3: Create consolidation pipeline

**Files:**
- Create: `src/cc_memory/consolidator.py`
- Create: `tests/test_consolidator.py`

- [ ] Write tests for `Consolidator.consolidate(project, options)` end-to-end flow (mocked Analyzer)
- [ ] Write tests for each transformation rule:
  - errors (3+ duplicates) → learning with source context
  - repeated file_changes (same file 5+ times) → hot zone insight
  - decisions (related topics) → rule/pattern
  - tasks (completed + pending) → status summary
- [ ] Write tests for decay scoring formula: `score = type_weight * recency_factor`
  - type_weight: decision=1.0, learning=0.9, task=0.8, brainstorm=0.5, file_change=0.3, error=0.2
  - recency_factor: `math.exp(-0.03 * age_days)` — ~0.5 at 23 days, ~0.05 at 100 days
  - Computed on-the-fly during consolidation (not persisted)
- [ ] Write tests for cleanup: delete_batch for processed duplicates, low-score records below threshold
- [ ] Write tests for consolidation audit log (report saved as learning with metadata)
- [ ] Write tests for `max_api_calls` budget respected through pipeline
- [ ] Implement `Consolidator` class:
  - `__init__(self, storage: Storage, analyzer: Analyzer)`
  - `consolidate(project: str, options: ConsolidateOptions) -> ConsolidateReport`
  - `ConsolidateOptions` dataclass: `decay_threshold=0.1, max_errors_per_project=50, max_api_calls=15, dry_run=False`
  - `ConsolidateReport` dataclass: `duplicates_removed, learnings_created, patterns_found, suggestions_for_claude_md, api_calls_used, stats_before, stats_after`
- [ ] Implement transformation pipeline: GROUP → ANALYZE → SAVE → CLEAN → AUDIT → REPORT
  - AUDIT step: save consolidation report as learning with `metadata={"source": "consolidation", "report": {...}}`
- [ ] Run tests — must pass before task 4

### Task 4: Add memory_consolidate and memory_stats MCP tools

**Files:**
- Modify: `src/cc_memory/server.py`
- Modify: `tests/test_server.py`

- [ ] Write tests for `memory_stats` tool: returns type distribution, total, date range, duplicate %
- [ ] Write tests for `memory_consolidate` tool: success, dry_run, no-API-key, unknown project
- [ ] Write tests for project validation: unknown project returns available project list
- [ ] Write tests for report formatting (human-readable string output)
- [ ] Add `memory_stats(project: str)` tool to server.py:
  - Lightweight, no API key needed
  - Returns: total memories, breakdown by type, date range, estimated duplicate count
- [ ] Add `memory_consolidate(project: str, dry_run: bool = True)` tool to server.py:
  - Default `dry_run=True` for safety
  - Validates project exists in DB, suggests available projects if not found
  - Returns formatted report string with stats + suggestions
  - Handles missing API key gracefully: "Set ANTHROPIC_API_KEY to use consolidation"
- [ ] Run tests — must pass before task 5

### Task 5: Smarter SessionStart (type-balanced retrieval)

**Files:**
- Modify: `src/cc_memory/hooks/session_start.py`
- Modify: `src/cc_memory/storage.py`
- Modify: `tests/test_session_start.py`

- [ ] Write tests for `recent_balanced(project)` storage method
- [ ] Write tests for edge cases: project with only errors, project with no decisions, empty project
- [ ] Write tests for updated `format_context` — renders what it receives without secondary limits
- [ ] Implement `recent_balanced(project: str) -> list[Memory]` in Storage:
  - Query per type with limits: 5 decisions, 5 tasks, 5 file_changes, 3 learnings, 2 errors, 2 brainstorms = ~22 max
  - Order each group by `created_at DESC`
  - Balanced across types — no single type dominates
- [ ] Update `session_start.py`:
  - Use `recent_balanced()` instead of `recent(limit=20)`
  - Simplify `format_context()` to render all received memories without per-type re-limiting (defense-in-depth limits now at query level)
- [ ] Ensure backward compatibility: `recent()` method unchanged, new method is additive
- [ ] Run tests — must pass before task 6

### Task 6: Verify acceptance criteria

- [ ] Verify `memory_stats` works on real data (quick sanity check)
- [ ] Verify `memory_consolidate` with `dry_run=True` on real data — review report
- [ ] Verify `memory_consolidate` with `dry_run=False` — check DB state after
- [ ] Verify Smarter SessionStart produces balanced context (hook simulation)
- [ ] Verify Bouncer Rule: Sonnet → Opus escalation works correctly
- [ ] Verify `max_api_calls` budget stops at limit
- [ ] Run full test suite: `uv run pytest tests/ -v`
- [ ] Verify all 158+ tests pass (existing + new)

### Task 7: [Final] Update documentation and deploy

- [ ] Update README.md: add memory_consolidate + memory_stats to tools table, document Bouncer Rule
- [ ] Update CLAUDE.md: add new module descriptions (consolidator, analyzer)
- [ ] Sync updated code to VPS: `rsync -avz --exclude='.venv' --exclude='__pycache__' --exclude='data/' --exclude='.git' /Users/sanjarusmanov/Documents/AI_PROJECTS/CC-Memory/ root@37.60.232.173:/root/CC-Memory/`
- [ ] Run `uv sync` on VPS to install new anthropic dependency
- [ ] Run tests on VPS to verify
- [ ] Move this plan to `docs/plans/completed/`

## Technical Details

### AI Analysis Prompts

**Error → Learning prompt (Sonnet):**
```
Analyze these recurring errors from a development project.
Extract a concise lesson learned (1-2 sentences).
Return JSON: {"lesson": "...", "confidence": 0.0-1.0, "suggestion": "..."}

Errors (occurred {count} times):
{error_content}
```

**File Changes → Hot Zone prompt (Sonnet):**
```
These files were modified frequently in recent sessions.
Identify the hot zones (most active areas) and what work is happening.
Return JSON: {"hot_zones": [{"file": "...", "changes": N, "insight": "..."}], "confidence": 0.0-1.0}

File changes:
{grouped_file_changes}
```

**Decisions → Rule prompt (Sonnet):**
```
Analyze these architectural/design decisions from a project.
Identify patterns or recurring preferences that could become project rules.
Return JSON: {"rules": [{"rule": "...", "evidence": "...", "strength": N}], "confidence": 0.0-1.0}

Decisions:
{grouped_decisions}
```

### Bouncer Rule Implementation

```python
result = analyzer.call_sonnet(prompt)
if result.confidence < 0.8:
    result = analyzer.call_opus(prompt)  # escalate
return result
```

### API Budget & Rate Limiting

```python
class Analyzer:
    def __init__(self, api_key, max_api_calls=15):
        self.max_api_calls = max_api_calls
        self.api_calls_made = 0

    def _call_api(self, model, prompt):
        if self.api_calls_made >= self.max_api_calls:
            raise BudgetExceededError(f"Limit {self.max_api_calls} reached")
        self.api_calls_made += 1
        # Exponential backoff on 429: 1s, 2s, 4s (max 3 retries)
        for attempt in range(3):
            try:
                return self.client.messages.create(...)
            except anthropic.RateLimitError:
                time.sleep(2 ** attempt)
        raise RateLimitError("Max retries exceeded")
```

### Decay Scoring Formula

```python
import math

TYPE_WEIGHTS = {
    "decision": 1.0,
    "learning": 0.9,
    "task": 0.8,
    "brainstorm": 0.5,
    "file_change": 0.3,
    "error": 0.2,
}

def decay_score(memory: Memory) -> float:
    """Computed on-the-fly during consolidation (not persisted)."""
    age_days = (datetime.now() - parse(memory.created_at)).days
    recency = math.exp(-0.03 * age_days)  # ~0.5 at 23 days, ~0.05 at 100 days
    return TYPE_WEIGHTS.get(memory.type, 0.3) * recency
```

### CLAUDE.md Suggestion Format

When a pattern has 5+ occurrences, memory_consolidate returns:
```
## Suggestions for CLAUDE.md

Add to project CLAUDE.md:
- "Always commit before deploy — recurring error (seen 12 times)"
- "Finance.tsx is the primary development file in Second Brain webapp"
```

### Consolidation Audit Log

Each consolidation run saves a record for traceability:
```python
storage.save(
    session_id="consolidation",
    project=project,
    type="learning",
    content=f"Consolidation: {report.duplicates_removed} duplicates removed, {report.learnings_created} learnings created",
    metadata={"source": "consolidation", "report": asdict(report)}
)
```

## Post-Completion

**Manual verification:**
- Run `memory_stats` on real data and verify output
- Run `memory_consolidate` with `dry_run=True` on real data and review report
- Run `memory_consolidate` with `dry_run=False` and verify DB state
- Open new Claude Code session and verify SessionStart injects balanced context
- Test on VPS via SSH to confirm cross-environment compatibility

**Future enhancements (not in scope):**
- Auto-consolidation after PreCompact (currently manual only)
- Semantic similarity via embeddings (currently exact-match after normalization)
- Cross-project pattern detection
- Web UI for browsing consolidated insights
- Concurrent consolidation lock mechanism
