# CC-Memory

**Persistent memory bank for [Claude Code](https://docs.anthropic.com/en/docs/claude-code) via MCP (Model Context Protocol).**

CC-Memory solves the problem of context loss in Claude Code sessions. When you run `/compact` or start a new session, Claude forgets file paths, architectural decisions, task progress, and debugging insights. CC-Memory automatically captures this context and brings it back when you need it.

## The Problem

Claude Code's built-in `/compact` command summarizes the conversation but loses:
- Which files were created or modified
- What architectural decisions were made and why
- Active TODO items and task progress
- Debugging insights and lessons learned
- Error patterns that were resolved

Starting a new session is even worse -- you begin with zero context about the project's history.

## How CC-Memory Solves It

CC-Memory runs as an MCP server alongside Claude Code and uses three lifecycle hooks to automatically capture and restore context:

```
                              ┌──────────────────────┐
                              │   SQLite + FTS5 DB    │
                              │  ~/.cc-memory/        │
                              │   memories.db         │
                              └──────┬───────┬────────┘
                                     │       │
              ┌──────────────────────┘       └──────────────────────┐
              │                                                      │
    ┌─────────▼──────────┐    ┌──────────────────┐    ┌─────────────▼──────────┐
    │   PreCompact Hook  │    │  UserPromptSubmit │    │   SessionStart Hook    │
    │                    │    │      Hook         │    │                        │
    │  Before /compact:  │    │                   │    │  On new session:       │
    │  Parse transcript  │    │  On each prompt:  │    │  Query recent memories │
    │  Extract memories  │    │  Detect keywords  │    │  Format as markdown    │
    │  Save to DB        │    │  Save decisions   │    │  Inject into context   │
    └────────────────────┘    └───────────────────┘    └────────────────────────┘
```

### 1. PreCompact Hook (before `/compact`)

When you run `/compact`, this hook fires first. It parses the full JSONL transcript and extracts:

- **File changes** -- every `Write` and `Edit` tool call with file paths and summaries
- **Decisions** -- answers to `AskUserQuestion` prompts + patterns like "decided", "chose"
- **Tasks** -- `TODO:`, `FIXME:`, `NEXT:` patterns + `TaskCreate` tool calls
- **Errors** -- tool results with `is_error: true`
- **Learnings** -- patterns like "Insight:", "learned:", "оказалось:"

All extracted memories are saved to the SQLite database before the context is compressed.

### 2. SessionStart Hook (on new session)

When you open Claude Code or resume a session, this hook queries the database for the current project's recent memories and injects them as additional context. Claude receives structured markdown like:

```markdown
## CC-Memory Context
**Project:** my-project | **Memories:** 15 | **Last session:** 2026-02-25 14:30:00

### Recent Decisions
- Chose SQLite for storage (2026-02-25 14:00:00)
- Using FTS5 for full-text search (2026-02-25 13:45:00)

### Active Tasks
- TODO: Add migration support
- Task: Implement caching layer

### Recent File Changes
- Created src/storage.py
- Edited src/server.py: 'old code' → 'new code'

### Learnings
- FTS5 supports Cyrillic text out of the box
```

### 3. UserPromptSubmit Hook (on each prompt)

Runs on every user message. Two functions:

- **Keyword detection** -- if your prompt contains decision words ("decided", "chose", "решили", "давай") or task words ("нужно", "TODO", "сделай"), it auto-saves the prompt as a memory
- **Periodic checkpoints** -- every 10 prompts, saves a breadcrumb so you know session length

## MCP Tools (Manual Access)

In addition to automatic hooks, CC-Memory provides 6 MCP tools that Claude can use during a session:

| Tool | Description | Example Use |
|------|-------------|-------------|
| `memory_save` | Save a memory manually | "Remember that we chose PostgreSQL for prod" |
| `memory_search` | Full-text search (FTS5) | "Search memories for authentication" |
| `memory_recent` | Recent memories for project | "What did we do in the last session?" |
| `memory_project` | All memories for a project | "Show all decisions for this project" |
| `memory_session` | Memories from a session | "What happened in session abc-123?" |
| `memory_forget` | Delete a memory | "Forget memory #42" |

### Memory Types

Each memory has a type that enables filtering:

| Type | Auto-captured from | Description |
|------|-------------------|-------------|
| `decision` | AskUserQuestion, keyword patterns | Architectural and design decisions |
| `file_change` | Write/Edit tool calls | Files created or modified |
| `task` | TODO/FIXME/NEXT patterns, TaskCreate | Active tasks and TODOs |
| `learning` | Insight/learned patterns | Debugging insights, TILs |
| `error` | Tool results with is_error | Errors encountered and resolved |
| `brainstorm` | Manual save only | Ideas and brainstorming notes |

## Privacy & Security

CC-Memory includes a privacy filter that automatically skips sensitive content:

- `.env` files and their contents
- Files/content matching `credentials`, `secret`, `password`
- API keys (`api_key`, `api.key`)
- Auth tokens (`access_token`, `auth_token`, `bearer_token`)
- Private keys
- Content wrapped in `<private>...</private>` tags

The database is stored locally at `~/.cc-memory/memories.db` -- nothing is sent to external services.

## Installation

### Prerequisites

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) with MCP support
- Python 3.12+ (managed by [uv](https://docs.astral.sh/uv/))
- `jq` (for automatic hook registration)

### Install

```bash
git clone https://github.com/snjrusmn/cc-memory.git
cd cc-memory
./scripts/install.sh
```

The install script:
1. Installs Python dependencies via `uv sync`
2. Creates the DB directory (`~/.cc-memory/`)
3. Registers the MCP server with Claude Code
4. Adds hooks to `~/.claude/settings.json` (preserving existing hooks)

### Verify

```bash
claude mcp list | grep cc-memory
```

### Uninstall

```bash
./scripts/install.sh --uninstall
```

Removes the MCP server and hooks. Database files are preserved.

### Dry Run

```bash
./scripts/install.sh --dry-run
```

Preview what the install script would do without making changes.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `CC_MEMORY_DB` | `~/.cc-memory/memories.db` | Path to SQLite database |

## Architecture

```
CC-Memory/
├── src/cc_memory/
│   ├── config.py           # Shared DB_PATH and detect_project()
│   ├── server.py           # FastMCP server (stdio, 6 tools)
│   ├── storage.py          # SQLite + FTS5 storage layer
│   ├── extractor.py        # JSONL transcript parser (5 extractors)
│   └── hooks/
│       ├── pre_compact.py  # PreCompact: extract & save before /compact
│       ├── session_start.py # SessionStart: inject memories into context
│       └── user_prompt.py  # UserPromptSubmit: keyword detection
├── tests/                  # 158 pytest tests
├── scripts/
│   └── install.sh          # Install/uninstall with --dry-run
└── data/                   # Local SQLite DB (gitignored)
```

### Storage Layer

Uses SQLite with FTS5 (Full-Text Search 5) for fast text search across all memories:

```sql
CREATE TABLE memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    project TEXT NOT NULL,
    type TEXT NOT NULL,  -- decision|file_change|task|learning|error|brainstorm
    content TEXT NOT NULL,
    metadata JSON,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE VIRTUAL TABLE memories_fts USING fts5(
    content, project, type,
    content=memories, content_rowid=id
);
```

FTS5 supports:
- Full-text search across all memory content
- Filtering by project and memory type
- Ranking results by relevance
- Cyrillic and other Unicode text

### Project Detection

CC-Memory automatically detects the current project by walking up from `cwd` looking for a `.git` directory. If found, uses the git root directory name. Otherwise, uses the current directory name.

### Hook I/O Protocol

All hooks receive JSON on stdin from Claude Code:
```json
{
    "session_id": "abc-123",
    "cwd": "/path/to/project",
    "hook_event_name": "PreCompact",
    "transcript_path": "~/.claude/projects/.../session.jsonl"
}
```

Output varies by hook:
- **PreCompact**: `{"systemMessage": "CC-Memory: saved 12 memories (3 decisions, 5 file_changes, ...)"}`
- **SessionStart**: `{"hookSpecificOutput": {"additionalContext": "## CC-Memory Context\n..."}}`
- **UserPromptSubmit**: `{}` (non-blocking, side-effects only)

## Development

```bash
# Install dependencies
uv sync

# Run tests
uv run pytest tests/ -v

# Run a specific test file
uv run pytest tests/test_storage.py -v

# Run MCP server manually
uv run cc-memory-server
```

### Test Suite

158 tests covering all components:

| File | Tests | What it covers |
|------|-------|---------------|
| `test_storage.py` | 63 | SQLite + FTS5 CRUD, search, context manager, FTS5 sanitizer, WAL mode, limit clamping, content length, frozen dataclass, DB permissions |
| `test_extractor.py` | 27 | JSONL parsing, 5 extractors, privacy filtering (SSH keys, connection strings, AWS keys, certificates) |
| `test_server.py` | 22 | All 6 MCP tools, error handling |
| `test_user_prompt.py` | 19 | Keyword detection, counters, auto-save, session ID sanitization |
| `test_session_start.py` | 13 | Context formatting, memory injection |
| `test_pre_compact.py` | 13 | Transcript extraction, project detection, path validation |
| `test_install.py` | 3 | Install script dry-run and uninstall |

## How It Fits with MEMORY.md

CC-Memory is designed to **supplement**, not replace, Claude Code's built-in memory system:

| | MEMORY.md | CC-Memory |
|--|-----------|-----------|
| **What** | High-level facts, preferences, conventions | Detailed session history, file changes, decisions |
| **How** | Manual edits | Automatic capture via hooks |
| **Scope** | Global or per-project | Per-project, cross-session |
| **Search** | Read entire file | FTS5 full-text search |
| **Size** | ~200 lines (truncated) | Unlimited (SQLite) |

**MEMORY.md** is for stable knowledge: "Always use pytest", "DB is PostgreSQL".
**CC-Memory** is for session artifacts: "Created auth middleware in session X", "Chose JWT over sessions because Y".

## Backlog

> Из сравнительного анализа 7 CC-Memory систем (claude-mem, claude-diary, mcp-memory-service, claude-code-vector-memory, claude-memory-bank, claude-supermemory, claude-user-memory) и PKM-ресёрча (PARA, Zettelkasten, AI-PKM Tools).

### Высокий приоритет

- [ ] **Reflection & Pattern Detection** — `/reflect` команда по модели [claude-diary](https://github.com/rlancemartin/claude-diary). Анализ накопленных memories: 2+ вхождения = паттерн, 3+ = сильный паттерн. Генерация правил для Lessons Learned / CLAUDE.md. Категории: preferences, design decisions, anti-patterns, efficiency lessons, project patterns.

- [ ] **Consolidation & Decay** — по модели [mcp-memory-service](https://github.com/doobidoo/mcp-memory-service). Сжатие старых memories (>90 дней) в summary. Decay scoring: access frequency + recency + memory type. Автоматическая очистка шума при сохранении ценных решений. MCP-инструмент `memory_consolidate`.

### Средний приоритет

- [ ] **Semantic Search (Embeddings)** — sqlite-vec + модель эмбеддингов (MiniLM-L6-v2 через ONNX, локально). Hybrid scoring по модели [claude-code-vector-memory](https://github.com/christian-byrne/claude-code-vector-memory): similarity 70% + recency 20% + complexity 10%. FTS5 остаётся fallback. Новый MCP-инструмент `memory_semantic_search`.

- [ ] **Progressive Disclosure** — 3-layer retrieval по модели [claude-mem](https://github.com/thedotmack/claude-mem): Layer 1 (compact index ~50 tokens) → Layer 2 (timeline) → Layer 3 (full details ~500 tokens). ~10x экономия токенов при SessionStart инжекции. Оптимизация для больших проектов (1000+ memories).

- [ ] **Second Brain Integration** — индексация vault-заметок из Obsidian (markdown → memories). Cross-reference: memory ↔ vault note. MCP-инструмент `memory_vault_search` для поиска по vault + memories одновременно. Двусторонняя связь с [Second Brain](https://github.com/snjrusmn/second-brain) проектом.

### Низкий приоритет

- [ ] **AI Session Summarization** — авто-суммаризация сессии через Claude Haiku при PreCompact. Вместо сырых file_changes → осмысленное описание "что было сделано".

- [ ] **Web UI** — браузерный интерфейс для просмотра и управления memories. Фильтры по проекту/типу/дате. Визуализация паттернов.

- [ ] **Cross-Machine Sync** — синхронизация SQLite через VPS. Одна БД на все машины.

### Источники

| Проект | Что взяли |
|---|---|
| [claude-diary](https://github.com/rlancemartin/claude-diary) | Reflect паттерн, diary + pattern detection, PreCompact auto-diary |
| [claude-mem](https://github.com/thedotmack/claude-mem) | Progressive 3-layer disclosure, ~10x token savings |
| [mcp-memory-service](https://github.com/doobidoo/mcp-memory-service) | Consolidation + decay, hybrid BM25 + vector, knowledge graph concept |
| [claude-code-vector-memory](https://github.com/christian-byrne/claude-code-vector-memory) | Hybrid scoring formula (similarity 70% + recency 20% + complexity 10%) |
| PKM Research (PARA, Zettelkasten, AI-PKM) | Vault integration, semantic search, auto-categorization patterns |

## License

MIT
