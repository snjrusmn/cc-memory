# CC-Memory

Persistent memory bank for Claude Code via MCP (Model Context Protocol).

Automatically captures decisions, file changes, tasks, learnings, and errors from Claude Code sessions. Memories persist across sessions and are searchable via FTS5 full-text search.

## Quick Start

```bash
# Install
./scripts/install.sh

# Verify
claude mcp list | grep cc-memory
```

## How It Works

**Hooks** capture context automatically:
- **PreCompact** — extracts memories from transcript before `/compact`
- **SessionStart** — injects recent project memories into new sessions
- **UserPromptSubmit** — detects decision/task keywords in prompts

**MCP Tools** provide manual access:
- `memory_save` — save a memory
- `memory_search` — full-text search
- `memory_recent` — recent memories for project
- `memory_project` — all project memories
- `memory_session` — session memories
- `memory_forget` — delete a memory

## Requirements

- Python 3.12+ (managed by uv)
- Claude Code with MCP support
- jq (for install script hook merging)

## Development

```bash
uv sync                    # install dependencies
uv run pytest tests/ -v    # run tests (134 tests)
```
