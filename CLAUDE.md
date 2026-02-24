# CC-Memory — Persistent Memory Bank for Claude Code

## What is this
MCP server that provides persistent memory across Claude Code sessions and projects.
Captures context automatically via hooks (PreCompact, SessionStart), stores in SQLite + FTS5,
provides search tools via MCP protocol.

## Stack
- **Runtime:** Python 3.11+
- **MCP:** stdio transport (no HTTP server needed)
- **Storage:** SQLite + FTS5 (full-text search)
- **Hooks:** Claude Code lifecycle hooks (PreCompact, SessionStart)

## Architecture
```
Claude Code Hooks          MCP Server (stdio)           Storage
PreCompact ──────> auto-save context ──────> SQLite + FTS5
SessionStart ────> auto-inject relevant <──── search by project/recency
UserPromptSubmit > periodic context check

MCP Tools:
  memory_save     — save a memory (decision, file change, task, learning)
  memory_search   — FTS5 search across all sessions/projects
  memory_recent   — last N memories for current project
  memory_project  — all memories for a project
  memory_session  — memories from a specific session
  memory_forget   — delete a memory
```

## Key Principles
- **Auto-capture:** hooks save context without user intervention
- **Supplement MEMORY.md:** high-level facts stay in MEMORY.md, details in MCP
- **Cross-project:** memories searchable across all projects
- **FTS5 first:** full-text search before considering embeddings
- **Privacy:** no API keys, credentials, or PII stored
- **Lightweight:** stdio MCP, no external services

## Project Structure
```
CC-Memory/
├── src/                  — MCP server source
│   ├── server.py         — MCP server (stdio)
│   ├── storage.py        — SQLite + FTS5 operations
│   ├── extractor.py      — JSONL transcript parser
│   └── hooks/            — Claude Code hook scripts
├── tests/                — pytest tests
├── scripts/              — install/setup scripts
├── docs/
│   ├── research/         — compact research findings
│   ├── brainstorms/      — brainstorm results
│   └── plans/            — implementation plans
└── data/                 — local SQLite DB (gitignored)
```

## Development
- Follow Superpowers workflow: brainstorm -> plan -> TDD -> review
- Tests with pytest
- AI-Dev v3 cycle: CONTRACT -> PLAN -> RED -> GREEN -> REFACTOR -> VERIFY
