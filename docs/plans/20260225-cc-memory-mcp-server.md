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

- [ ] Read 2-3 real JSONL transcripts from `~/.claude/projects/` — document actual message structure
- [ ] Verify: is message type `"human"` or `"user"`? How are tool_results structured?
- [ ] Verify: does PreCompact hook input include `transcript_path`? Does it point to `.jsonl` or `.txt`?
- [ ] Verify: what is the correct hook output field — `additionalContext` or `systemMessage` or other?
- [ ] Test minimal hook: write a 5-line script that outputs `{"systemMessage": "test"}`, register as SessionStart, verify Claude receives it
- [ ] Document all findings in `docs/verified-jsonl-format.md`
- [ ] Update this plan's Technical Details section with verified format

### Task 1: Project scaffolding with uv

**Files:**
- Create: `pyproject.toml`
- Create: `src/cc_memory/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] Initialize uv project: `uv init --python 3.12` with project name `cc-memory`
- [ ] Configure `pyproject.toml`: dependencies (mcp>=1.0), dev-dependencies (pytest, pytest-asyncio)
- [ ] Create package structure: `src/cc_memory/__init__.py`
- [ ] Create test infrastructure: `tests/__init__.py`, `tests/conftest.py` with shared fixtures
- [ ] Verify setup: `uv run pytest tests/ -v` (empty test suite passes)
- [ ] Run `uv run python -c "import cc_memory"` to verify package imports

### Task 2: Storage layer (SQLite + FTS5)

**Files:**
- Create: `src/cc_memory/storage.py`
- Create: `tests/test_storage.py`

- [ ] Write tests for `Storage.init_db()` — creates tables and FTS5 index
- [ ] Write tests for `Storage.save()` — insert memory with all fields (session_id, project, type, content, metadata)
- [ ] Write tests for `Storage.search()` — FTS5 full-text search with optional project/type filters
- [ ] Write tests for `Storage.recent()` — last N memories for a project, ordered by created_at desc
- [ ] Write tests for `Storage.by_project()` — all memories for project, optional type filter
- [ ] Write tests for `Storage.by_session()` — all memories for a session_id
- [ ] Write tests for `Storage.delete()` — delete by id
- [ ] Write tests for FTS5 query sanitizer: escapes special chars (`AND`, `OR`, `NOT`, `*`, `"`, `'`, `C++`)
- [ ] Write tests for edge cases: empty search results, Cyrillic text, JSON metadata
- [ ] Implement `Storage` class in `src/cc_memory/storage.py`:
  - `__init__(db_path)` — opens/creates SQLite DB
  - `init_db()` — CREATE TABLE memories + CREATE VIRTUAL TABLE memories_fts
  - `save(session_id, project, type, content, metadata=None)` → id
  - `search(query, project=None, type=None, limit=20)` → list[Memory]
  - `recent(project, limit=20)` → list[Memory]
  - `by_project(project, type=None, limit=50)` → list[Memory]
  - `by_session(session_id, limit=50)` → list[Memory]
  - `delete(memory_id)` → bool
- [ ] Run tests — must all pass before Task 3

### Task 3: MCP Server (stdio transport, 6 tools)

**Files:**
- Create: `src/cc_memory/server.py`
- Create: `tests/test_server.py`

- [ ] Write tests for `memory_save` tool — saves a memory, returns confirmation with id
- [ ] Write tests for `memory_search` tool — FTS5 search with query, optional project/type/limit params
- [ ] Write tests for `memory_recent` tool — returns recent memories for project
- [ ] Write tests for `memory_project` tool — returns project memories with optional type filter
- [ ] Write tests for `memory_session` tool — returns session memories by session_id
- [ ] Write tests for `memory_forget` tool — deletes a memory by id
- [ ] Write tests for error handling: missing required params, invalid type, empty query
- [ ] Implement MCP server in `src/cc_memory/server.py`:
  - Use `mcp` SDK with stdio transport
  - Register 6 tools with typed parameters and descriptions
  - Each tool delegates to Storage layer
  - DB path from env `CC_MEMORY_DB` or default `~/.cc-memory/memories.db`
- [ ] Run tests — must all pass before Task 4

### Task 4: JSONL Transcript Extractor

**Files:**
- Create: `src/cc_memory/extractor.py`
- Create: `tests/test_extractor.py`
- Create: `tests/fixtures/sample_transcript.jsonl`

- [ ] Create sample JSONL fixture (minimal realistic transcript with Write, Edit, Bash, AskUserQuestion, errors)
- [ ] Write tests for `extract_file_changes()` — finds Write/Edit tool_use → file paths + summary
- [ ] Write tests for `extract_decisions()` — finds AskUserQuestion answers + decision patterns in text
- [ ] Write tests for `extract_tasks()` — finds TaskCreate/TodoWrite + "TODO:"/"NEXT:" patterns
- [ ] Write tests for `extract_errors()` — finds tool_result with error + subsequent fix
- [ ] Write tests for `extract_learnings()` — finds "insight:", "learned:", "оказалось:" patterns
- [ ] Write tests for privacy filtering — skips .env content, credentials, `<private>` tags
- [ ] Write tests for `extract_all()` — combines all extractors, returns list of Memory dicts
- [ ] Implement `Extractor` class in `src/cc_memory/extractor.py`:
  - `__init__(jsonl_path)` — reads and parses JSONL file
  - `extract_file_changes()` → list[dict]
  - `extract_decisions()` → list[dict]
  - `extract_tasks()` → list[dict]
  - `extract_errors()` → list[dict]
  - `extract_learnings()` → list[dict]
  - `extract_all()` → list[dict] (combines all, deduplicates)
  - Privacy: `_is_sensitive(content)` → bool
- [ ] Run tests — must all pass before Task 5

### Task 5: PreCompact Hook

**Files:**
- Create: `src/cc_memory/hooks/pre_compact.py`
- Create: `tests/test_pre_compact.py`

- [ ] Write tests for hook script: reads transcript path from env/stdin, extracts memories, saves to DB
- [ ] Write tests for project detection from cwd
- [ ] Write tests for session_id detection from transcript filename
- [ ] Write tests for output format (use field verified in Task 0: `systemMessage` or `additionalContext`)
- [ ] Implement `pre_compact.py`:
  - Reads stdin (hook input JSON with `session_id`, `transcript_path` if available)
  - Falls back to finding latest JSONL in `~/.claude/projects/` for current project
  - Runs Extractor on transcript
  - Saves all extracted memories via Storage
  - Outputs JSON with verified field: `{"<verified_field>": "CC-Memory: saved N memories (X decisions, Y files, Z tasks)"}`
- [ ] Run tests — must all pass before Task 6

### Task 6: SessionStart Hook

**Files:**
- Create: `src/cc_memory/hooks/session_start.py`
- Create: `tests/test_session_start.py`

- [ ] Write tests for hook: detects project from cwd, queries recent memories, formats as additionalContext
- [ ] Write tests for context formatting (structured markdown with sections: decisions, files, tasks)
- [ ] Write tests for empty state (no memories yet → minimal output)
- [ ] Write tests for graceful handling of any SessionStart trigger (no reliance on undocumented `source` field)
- [ ] Implement `session_start.py`:
  - Reads stdin (hook input JSON with `session_id` and standard hook fields)
  - Detects project from cwd (basename of git root or cwd)
  - Queries Storage.recent(project, limit=20)
  - Formats as structured markdown:
    ```
    ## CC-Memory Context
    **Project:** {project} | **Memories:** {count} | **Last session:** {date}

    ### Recent Decisions
    - {decision content} ({date})

    ### Active Tasks
    - {task content} ({status})

    ### Recent File Changes
    - {file_path}: {summary}
    ```
  - Outputs JSON with verified field: `{"<verified_field>": "<formatted markdown>"}`
- [ ] Run tests — must all pass before Task 7

### Task 7: UserPromptSubmit Hook

**Files:**
- Create: `src/cc_memory/hooks/user_prompt.py`
- Create: `tests/test_user_prompt.py`

- [ ] Write tests for prompt counter (tracks per session, triggers every 10 prompts)
- [ ] Write tests for keyword detection in user messages (decision/task/learning patterns)
- [ ] Write tests for auto-save when keywords detected
- [ ] Write tests for counter persistence (temp file per session)
- [ ] Implement `user_prompt.py`:
  - Reads stdin (hook input JSON with `session_id`, `user_prompt`)
  - Increments prompt counter (stored in `/tmp/cc-memory-{session_id}.count`)
  - Every 10 prompts OR when decision/task keywords detected:
    - Saves relevant content via Storage
  - Non-blocking: outputs empty JSON `{}` (no additionalContext needed)
- [ ] Run tests — must all pass before Task 8

### Task 8: Installation and Integration

**Files:**
- Create: `scripts/install.sh`
- Modify: `pyproject.toml` (add entry points)
- Create: `.env.example`

- [ ] Write tests for install script (`--dry-run` mode shows actions without executing)
- [ ] Add entry points in `pyproject.toml`:
  - `cc-memory-server` → `cc_memory.server:main`
  - `cc-memory-pre-compact` → `cc_memory.hooks.pre_compact:main`
  - `cc-memory-session-start` → `cc_memory.hooks.session_start:main`
  - `cc-memory-user-prompt` → `cc_memory.hooks.user_prompt:main`
- [ ] Create `scripts/install.sh`:
  - Installs package: `uv pip install -e .`
  - Creates DB directory: `mkdir -p ~/.cc-memory`
  - Adds MCP server to Claude Code: `claude mcp add cc-memory -- uv run --directory {project_dir} cc-memory-server`
  - Merges hooks into `~/.claude/settings.json` using `jq` (preserving existing hooks):
    - PreCompact → `cc-memory-pre-compact`
    - SessionStart → `cc-memory-session-start`
    - UserPromptSubmit → `cc-memory-user-prompt` (alongside existing skill-forced-eval)
  - Supports `--dry-run` (show changes without applying) and `--uninstall` (remove hooks + MCP)
  - Prints confirmation
- [ ] Create `.env.example` with `CC_MEMORY_DB=~/.cc-memory/memories.db`
- [ ] Run tests — must all pass before Task 9

### Task 9: Verify acceptance criteria

- [ ] Verify: MCP server starts via stdio and responds to tool calls
- [ ] Verify: `memory_save` + `memory_search` round-trip works
- [ ] Verify: FTS5 search returns relevant results (Russian and English)
- [ ] Verify: JSONL extractor correctly parses real transcript (from ~/.claude/projects/)
- [ ] Verify: PreCompact hook saves memories from transcript
- [ ] Verify: SessionStart hook injects context on startup
- [ ] Verify: UserPromptSubmit hook tracks prompts and auto-saves
- [ ] Verify: Privacy filter skips sensitive content
- [ ] Verify: Existing hooks (plannotator, log-claude-actions, skill-eval) still work
- [ ] Run full test suite: `uv run pytest tests/ -v`

### Task 10: [Final] Documentation and cleanup

- [ ] Update `CLAUDE.md` with actual file paths and commands
- [ ] Update `README.md` with installation instructions
- [ ] Ensure all tests pass: `uv run pytest tests/ -v --tb=short`
- [ ] Move this plan to `docs/plans/completed/`

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
