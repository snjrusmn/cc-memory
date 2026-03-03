# CC-Memory — Persistent Memory Bank for Claude Code

## What is this
MCP server that provides persistent memory across Claude Code sessions and projects.
Captures context automatically via hooks (PreCompact, SessionStart, UserPromptSubmit),
stores in SQLite + FTS5, provides search tools via MCP protocol (stdio transport).

## Stack
- **Runtime:** Python 3.12 (managed by uv)
- **MCP:** FastMCP with stdio transport
- **Storage:** SQLite + FTS5 (full-text search)
- **Hooks:** Claude Code lifecycle hooks (PreCompact, SessionStart, UserPromptSubmit)
- **AI Analysis:** Anthropic SDK (Sonnet/Opus with Bouncer Rule)
- **Tests:** pytest (245 tests)

## Architecture
```
Claude Code Hooks          MCP Server (stdio)           Storage
PreCompact ──────> auto-save context ──────> SQLite + FTS5
SessionStart ────> auto-inject relevant <──── search by project/recency
UserPromptSubmit > keyword detection + periodic checkpoint

MCP Tools (8):
  memory_save        — save a memory (decision, file_change, task, learning, error, brainstorm)
  memory_search      — FTS5 search across all sessions/projects
  memory_recent      — last N memories for current project
  memory_project     — all memories for a project (optional type filter)
  memory_session     — memories from a specific session
  memory_forget      — delete a memory by ID
  memory_stats       — quick DB overview (type counts, duplicates) — no API key needed
  memory_consolidate — AI-powered cleanup: dedup, extract learnings, decay scoring (Bouncer Rule)
```

## Key Principles
- **Auto-capture:** hooks save context without user intervention
- **Supplement MEMORY.md:** high-level facts stay in MEMORY.md, details in MCP
- **Cross-project:** memories searchable across all projects
- **FTS5 first:** full-text search before considering embeddings
- **Privacy:** skips .env, credentials, API keys, tokens, private tags
- **Lightweight:** stdio MCP, no external services

## Project Structure
```
CC-Memory/
├── src/cc_memory/
│   ├── __init__.py       — package init
│   ├── config.py         — shared DB_PATH and detect_project()
│   ├── server.py         — FastMCP server (stdio, 8 tools)
│   ├── storage.py        — SQLite + FTS5 (Memory dataclass, CRUD, search, grouping, context manager)
│   ├── analyzer.py       — Claude API integration with Bouncer Rule (Sonnet → Opus escalation)
│   ├── consolidator.py   — Consolidation pipeline: GROUP → ANALYZE → SAVE → CLEAN → AUDIT → REPORT
│   ├── extractor.py      — JSONL transcript parser (5 extractors + privacy filter)
│   └── hooks/
│       ├── __init__.py
│       ├── pre_compact.py    — PreCompact: extract & save before /compact
│       ├── session_start.py  — SessionStart: inject recent memories as context
│       └── user_prompt.py    — UserPromptSubmit: keyword detection + checkpoints
├── tests/                    — 245 pytest tests
│   ├── fixtures/             — sample JSONL transcript
│   ├── test_storage.py       — 70 tests (+ balanced retrieval)
│   ├── test_server.py        — 32 tests (+ stats, consolidate tools)
│   ├── test_analyzer.py      — 21 tests (Bouncer Rule, budget, rate limiting)
│   ├── test_consolidator.py  — 22 tests (pipeline, decay, cleanup, audit)
│   ├── test_grouping.py      — 23 tests (normalization, dedup, batch delete)
│   ├── test_extractor.py     — 27 tests
│   ├── test_pre_compact.py   — 13 tests
│   ├── test_session_start.py — 13 tests
│   ├── test_user_prompt.py   — 19 tests
│   └── test_install.py       — 3 tests
├── scripts/
│   └── install.sh        — install/uninstall (--dry-run supported)
├── docs/
│   ├── research/         — compact research findings
│   ├── verified-jsonl-format.md — JSONL & hook format documentation
│   └── plans/            — implementation plans
└── data/                 — local SQLite DB (gitignored)
```

## Commands
```bash
# Run tests
cd /Users/sanjarusmanov/Documents/AI_PROJECTS/CC-Memory && uv run pytest tests/ -v

# Install (registers MCP server + hooks)
./scripts/install.sh

# Install dry-run (preview changes)
./scripts/install.sh --dry-run

# Uninstall
./scripts/install.sh --uninstall

# Run MCP server manually (stdio)
uv run cc-memory-server
```

## DB Location
Default: `~/.cc-memory/memories.db`
Override: `CC_MEMORY_DB` environment variable
