# CC-Memory: Persistent Memory Bank for Claude Code

## Overview
MCP server that provides persistent memory across Claude Code sessions and projects.
Captures context automatically via hooks (PreCompact, SessionStart, UserPromptSubmit),
stores in SQLite + FTS5, provides search tools via MCP protocol (stdio transport).

**Problem:** Built-in `/compact` loses file paths, decisions, task status, and CLAUDE.md context.
**Solution:** Auto-capture memories before compact, auto-inject after. Knowledge accumulates cross-session, cross-project.
**Integration:** Supplements existing MEMORY.md (high-level facts stay there, details in MCP).

## Context (from discovery)
- **Project path:** `/Users/sanjarusmanov/Documents/AI_PROJECTS/CC-Memory/`
- **Python:** 3.12 via uv (system has 3.9.6, uv 0.10.0 manages Python download)
- **Existing hooks:** plannotator (PermissionRequest), log-claude-actions (PostToolUse, Stop), skill-forced-eval (UserPromptSubmit)
- **JSONL location:** `~/.claude/projects/[project-hash]/[uuid].jsonl`
- **No MCP servers configured yet**
- **Existing files:** CLAUDE.md, GUARDRAILS.md, .gitignore, docs/research/

## Development Approach
- **Testing approach:** TDD (RED → GREEN → REFACTOR)
- Complete each task fully before moving to the next
- Make small, focused changes
- **CRITICAL: every task MUST include new/updated tests** for code changes
- **CRITICAL: all tests must pass before starting next task**
- **CRITICAL: update this plan file when scope changes during implementation**
- Run tests after each change: `cd /Users/sanjarusmanov/Documents/AI_PROJECTS/CC-Memory && uv run pytest tests/ -v`

## Testing Strategy
- **Unit tests:** pytest, required for every task
- **Integration tests:** test MCP server via stdio (subprocess)
- **Test fixtures:** in-memory SQLite (`:memory:`) for speed, no cleanup needed

## Progress Tracking
- Mark completed items with `[x]` immediately when done
- Add newly discovered tasks with ➕ prefix
- Document issues/blockers with ⚠️ prefix
- Update plan if implementation deviates from original scope

---

## Implementation Steps

### Task 0: Verify assumptions (JSONL format, hook I/O)

**Files:**
- Create: `docs/verified-jsonl-format.md`

- [x] Read 2-3 real JSONL transcripts from `~/.claude/projects/` — document actual message structure
- [x] Verify: is message type `"human"` or `"user"`? How are tool_results structured?
- [x] Verify: does PreCompact hook input include `transcript_path`? Does it point to `.jsonl` or `.txt`?
- [x] Verify: what is the correct hook output field — `additionalContext` or `systemMessage` or other?
- [x] ~~Test minimal hook~~ — verified from existing hooks (superpowers session-start.sh, skill-forced-eval-hook.sh) and official docs
- [x] Document all findings in `docs/verified-jsonl-format.md`
- [x] Update this plan's Technical Details section with verified format

### Task 1: Project scaffolding with uv

**Files:**
- Create: `pyproject.toml`
- Create: `src/cc_memory/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [x] Initialize uv project: `uv init --python 3.12` with project name `cc-memory`
- [x] Configure `pyproject.toml`: dependencies (mcp>=1.0), dev-dependencies (pytest, pytest-asyncio)
- [x] Create package structure: `src/cc_memory/__init__.py`, `src/cc_memory/hooks/__init__.py`
- [x] Create test infrastructure: `tests/__init__.py`, `tests/conftest.py` with shared fixtures
- [x] Verify setup: `uv run pytest tests/ -v` (empty test suite passes)
- [x] Run `uv run python -c "import cc_memory"` to verify package imports

### Task 2: Storage layer (SQLite + FTS5)

**Files:**
- Create: `src/cc_memory/storage.py`
- Create: `tests/test_storage.py`

- [x] Write tests for `Storage.init_db()` — creates tables and FTS5 index
- [x] Write tests for `Storage.save()` — insert memory with all fields (session_id, project, type, content, metadata)
- [x] Write tests for `Storage.search()` — FTS5 full-text search with optional project/type filters
- [x] Write tests for `Storage.recent()` — last N memories for a project, ordered by created_at desc
- [x] Write tests for `Storage.by_project()` — all memories for project, optional type filter
- [x] Write tests for `Storage.by_session()` — all memories for a session_id
- [x] Write tests for `Storage.delete()` — delete by id
- [x] Write tests for FTS5 query sanitizer: escapes special chars (`AND`, `OR`, `NOT`, `*`, `"`, `'`, `C++`)
- [x] Write tests for edge cases: empty search results, Cyrillic text, JSON metadata
- [x] Implement `Storage` class in `src/cc_memory/storage.py` (42 tests, all pass)
- [x] Run tests — 42 passed in 0.04s

### Task 3: MCP Server (stdio transport, 6 tools)

**Files:**
- Create: `src/cc_memory/server.py`
- Create: `tests/test_server.py`

- [x] Write tests for `memory_save` tool — saves a memory, returns confirmation with id
- [x] Write tests for `memory_search` tool — FTS5 search with query, optional project/type/limit params
- [x] Write tests for `memory_recent` tool — returns recent memories for project
- [x] Write tests for `memory_project` tool — returns project memories with optional type filter
- [x] Write tests for `memory_session` tool — returns session memories by session_id
- [x] Write tests for `memory_forget` tool — deletes a memory by id
- [x] Write tests for error handling: missing required params, invalid type, empty query
- [x] Implement MCP server in `src/cc_memory/server.py` (FastMCP + 6 tools, stdio transport)
- [x] Run tests — 22 passed in 1.56s

### Task 4: JSONL Transcript Extractor

**Files:**
- Create: `src/cc_memory/extractor.py`
- Create: `tests/test_extractor.py`
- Create: `tests/fixtures/sample_transcript.jsonl`

- [x] Create sample JSONL fixture (18 messages: Write, Edit, Bash, AskUserQuestion, errors, sensitive .env)
- [x] Write tests for `extract_file_changes()` — finds Write/Edit, skips .env
- [x] Write tests for `extract_decisions()` — finds AskUserQuestion answers
- [x] Write tests for `extract_tasks()` — finds TODO/NEXT patterns
- [x] Write tests for `extract_errors()` — finds tool_result with is_error
- [x] Write tests for `extract_learnings()` — finds insight/learned/оказалось patterns
- [x] Write tests for privacy filtering — .env, credentials, private tags, API keys
- [x] Write tests for `extract_all()` — combines all, no sensitive content
- [x] Implement `Extractor` class (23 tests, all pass)
- [x] Run tests — 23 passed in 0.03s

### Task 5: PreCompact Hook

**Files:**
- Create: `src/cc_memory/hooks/pre_compact.py`
- Create: `tests/test_pre_compact.py`

- [x] Write tests for hook: reads transcript, extracts memories, saves to DB
- [x] Write tests for project detection from cwd (git root or dirname)
- [x] Write tests for session_id from hook input
- [x] Write tests for output format (systemMessage field)
- [x] Implement `pre_compact.py` (reads stdin JSON, extracts via Extractor, saves via Storage)
- [x] Run tests — 11 passed in 0.42s

### Task 6: SessionStart Hook

**Files:**
- Create: `src/cc_memory/hooks/session_start.py`
- Create: `tests/test_session_start.py`

- [x] Write tests for hook: detects project, queries recent memories, formats as additionalContext
- [x] Write tests for context formatting (markdown sections: decisions, files, tasks, learnings, errors)
- [x] Write tests for empty state (no memories → empty dict)
- [x] Write tests for all SessionStart sources (startup, resume, clear, compact)
- [x] Implement `session_start.py` (hookSpecificOutput.additionalContext with structured markdown)
- [x] Run tests — 13 passed in 0.18s

### Task 7: UserPromptSubmit Hook

**Files:**
- Create: `src/cc_memory/hooks/user_prompt.py`
- Create: `tests/test_user_prompt.py`

- [x] Write tests for prompt counter (tracks per session, triggers every 10 prompts)
- [x] Write tests for keyword detection (decision: решили/decided/chose, task: нужно/TODO/сделай)
- [x] Write tests for auto-save when keywords detected
- [x] Write tests for counter persistence (temp file per session)
- [x] Implement `user_prompt.py` (non-blocking, keyword detection + periodic checkpoint)
- [x] Run tests — 14 passed in 0.17s

### Task 8: Installation and Integration

**Files:**
- Create: `scripts/install.sh`
- Modify: `pyproject.toml` (add entry points)
- Create: `.env.example`

- [x] Write tests for install script (--dry-run and --uninstall --dry-run)
- [x] Entry points already in pyproject.toml (added in Task 1)
- [x] Create `scripts/install.sh` (install, --dry-run, --uninstall, jq-based settings merge)
- [x] Create `.env.example`
- [x] Run tests — 3 passed in 0.63s

### Task 9: Verify acceptance criteria

- [x] Verify: MCP server tools work (tested via unit tests — 22 tool tests pass)
- [x] Verify: `memory_save` + `memory_search` round-trip works (test_server.py)
- [x] Verify: FTS5 search returns relevant results, including Cyrillic (test_storage.py)
- [x] Verify: JSONL extractor correctly parses transcript (test_extractor.py with fixture)
- [x] Verify: PreCompact hook saves memories from transcript (test_pre_compact.py)
- [x] Verify: SessionStart hook injects context on startup (test_session_start.py)
- [x] Verify: UserPromptSubmit hook tracks prompts and auto-saves (test_user_prompt.py)
- [x] Verify: Privacy filter skips .env, credentials, API keys, private tags
- [x] Existing hooks unmodified (install.sh preserves existing hooks via jq merge)
- [x] Run full test suite: **134 passed in 1.63s**

### Task 10: [Final] Documentation and cleanup

- [x] Update `CLAUDE.md` with actual file paths, commands, test counts
- [x] Update `README.md` with installation and development instructions
- [x] All tests pass: **134 passed in 1.63s**
- [ ] Move this plan to `docs/plans/completed/` (after merge)

## Technical Details

### Data Model
```sql
CREATE TABLE memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    project TEXT NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('decision','file_change','task','learning','error','brainstorm')),
    content TEXT NOT NULL,
    metadata JSON,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE VIRTUAL TABLE memories_fts USING fts5(
    content, project, type,
    content=memories,
    content_rowid=id
);

-- Sync triggers for FTS5
CREATE TRIGGER memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, content, project, type)
    VALUES (new.id, new.content, new.project, new.type);
END;

CREATE TRIGGER memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content, project, type)
    VALUES('delete', old.id, old.content, old.project, old.type);
END;

CREATE TRIGGER memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content, project, type)
    VALUES('delete', old.id, old.content, old.project, old.type);
    INSERT INTO memories_fts(rowid, content, project, type)
    VALUES (new.id, new.content, new.project, new.type);
END;

-- Performance indexes
CREATE INDEX idx_memories_project_date ON memories(project, created_at DESC);
CREATE INDEX idx_memories_session ON memories(session_id);
CREATE INDEX idx_memories_type ON memories(type);
```

### MCP Tool Schemas

```python
# memory_save
params: {
    "session_id": str,        # current session ID
    "project": str,           # project name
    "type": str,              # decision|file_change|task|learning|error|brainstorm
    "content": str,           # the memory text
    "metadata": dict | None   # optional structured data
}

# memory_search
params: {
    "query": str,             # FTS5 search query
    "project": str | None,    # optional project filter
    "type": str | None,       # optional type filter
    "limit": int = 20         # max results
}

# memory_recent
params: {
    "project": str,           # project name
    "limit": int = 20         # max results
}

# memory_project
params: {
    "project": str,           # project name
    "type": str | None,       # optional type filter
    "limit": int = 50         # max results
}

# memory_session
params: {
    "session_id": str,        # session ID
    "limit": int = 50         # max results
}

# memory_forget
params: {
    "memory_id": int          # memory ID to delete
}
```

### Hook Integration (settings.json merge)

```json
{
  "hooks": {
    "PreCompact": [{
      "matcher": "",
      "hooks": [{
        "type": "command",
        "command": "uv run --directory /Users/sanjarusmanov/Documents/AI_PROJECTS/CC-Memory cc-memory-pre-compact",
        "timeout": 30000
      }]
    }],
    "SessionStart": [{
      "matcher": "",
      "hooks": [{
        "type": "command",
        "command": "uv run --directory /Users/sanjarusmanov/Documents/AI_PROJECTS/CC-Memory cc-memory-session-start",
        "timeout": 10000
      }]
    }],
    "UserPromptSubmit": [{
      "matcher": "",
      "hooks": [{
        "type": "command",
        "command": "uv run --directory /Users/sanjarusmanov/Documents/AI_PROJECTS/CC-Memory cc-memory-user-prompt",
        "timeout": 5000
      }]
    }]
  }
}
```

### JSONL Transcript Format (PRELIMINARY — must verify in Task 0)

> **WARNING:** This format is an assumption. Task 0 MUST verify against real transcripts before Task 4.

```jsonl
{"type": "user", "message": {"content": "..."}}
{"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Write", "input": {"file_path": "..."}}]}}
{"type": "user", "toolUseResult": {"content": [...]}}
{"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "AskUserQuestion", "input": {"questions": [...]}}]}}
```

### Privacy Patterns (skip list)

```python
SENSITIVE_PATTERNS = [
    r'\.env', r'credentials', r'secret', r'token',
    r'password', r'api.key', r'private.key',
    r'<private>.*?</private>'
]
```

## Post-Completion

**Manual verification:**
- Test with a real session: trigger compact, verify memories saved
- Verify SessionStart injects relevant context in new session
- Test FTS5 search with Russian text
- Verify no interference with existing hooks

**Future enhancements (not in scope):**
- Embeddings for semantic search (evolution to Approach C)
- AI-powered session compression via Haiku
- VPS deployment for remote access
- Integration with Second Brain
- Web UI for browsing memories
