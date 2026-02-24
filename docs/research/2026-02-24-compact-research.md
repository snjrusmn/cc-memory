# Research: Improving /compact in Claude Code

**Date:** 2026-02-24
**Status:** Research complete, approach selected (B: MCP Memory Server)

---

## Problem

Built-in `/compact` (and auto-compact at ~83.5% context) **summarizes old messages**, losing:
- Specific file paths and line numbers
- Error messages
- Architectural decisions and their rationale
- CLAUDE.md instructions (bug, documented in 5+ issues)
- Task status and progress

Documented in issues: [#4017](https://github.com/anthropics/claude-code/issues/4017), [#4517](https://github.com/anthropics/claude-code/issues/4517), [#13919](https://github.com/anthropics/claude-code/issues/13919), [#19471](https://github.com/anthropics/claude-code/issues/19471), [#23063](https://github.com/anthropics/claude-code/issues/23063).

---

## Category 1: Quick Settings (0-5 min)

### 1.1 `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE`
```bash
export CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=70
```
Triggers compaction earlier (70% vs 83.5%), leaving more room for quality summarization.

### 1.2 `/compact` with custom instructions
```
/compact Preserve all file paths, function names, error messages, debugging steps, architectural decisions.
```
Works for manual compact only. **Auto-compact ignores these.**

### 1.3 CLAUDE.md instructions
```markdown
# Compact Instructions
When compacting, always preserve: modified file list, active git branch,
test commands, architectural decisions, and current task status.
```
Unofficial, not guaranteed to be respected during auto-compaction.

### 1.4 Disable auto-compact
```
/config -> disable autocompact
```
Then manual `/compact` at strategic moments.

---

## Category 2: Hooks and Lightweight Solutions (15-30 min)

### 2.1 PreCompact hook (built-in, v1.0.48+)
```json
{
  "hooks": {
    "PreCompact": [{
      "hooks": [{
        "type": "command",
        "command": "node .claude/hooks/save-context.mjs"
      }]
    }]
  }
}
```
Official mechanism. What the hook injects also gets summarized. No PostCompact hook yet ([#17237](https://github.com/anthropics/claude-code/issues/17237)).

### 2.2 ContextRecoveryHook (ClaudeFa.st)
- Source: [claudefa.st/blog/tools/hooks/context-recovery-hook](https://claudefa.st/blog/tools/hooks/context-recovery-hook)
- 3-file system: StatusLine monitoring -> backup at 50K, 60K, 70K, 80K tokens -> PreCompact safety net
- Parses JSONL transcript, extracts requests, modifications, decisions -> structured markdown

### 2.3 c0ntextKeeper
- Repo: [github.com/Capnjbrown/c0ntextKeeper](https://github.com/Capnjbrown/c0ntextKeeper)
- `npm install -g c0ntextkeeper && c0ntextkeeper setup`
- 7 hooks, 187 semantic patterns, 3 MCP tools
- Auto-redacts API keys, PII. <10ms per operation, 483 tests

---

## Category 3: Full Memory Systems (30-60 min)

### 3.1 Claude-Mem
- Repo: [github.com/thedotmack/claude-mem](https://github.com/thedotmack/claude-mem)
- 5 lifecycle hooks + SQLite + ChromaDB (vectors) + HTTP worker on port 37777
- ~10x token savings through progressive disclosure
- AGPL license

### 3.2 MCP Memory Keeper
- Repo: [github.com/mkreyman/mcp-memory-keeper](https://github.com/mkreyman/mcp-memory-keeper)
- `claude mcp add memory-keeper npx mcp-memory-keeper`
- Checkpoint/restore, channels (by git branch), FTS search, shared board
- MIT license

### 3.3 Claude Code CMV (Contextual Memory Virtualisation)
- Repo: [github.com/CosmoNaught/claude-code-cmv](https://github.com/CosmoNaught/claude-code-cmv)
- Version control for context: snapshot, branch, trim
- **85% reduction** (152K -> 23K) by trimming tool bloat while keeping conversation verbatim
- Most elegant approach to compact

### 3.4 memory-mcp (claude-code-memory)
- Repo: [github.com/yuvalsuede/memory-mcp](https://github.com/yuvalsuede/memory-mcp)
- Two-tier: CLAUDE.md (auto-generated ~150 lines) + `.memory/state.json` (searchable)
- Git snapshot on every update, LLM extraction via Haiku (~$0.001)

### 3.5 claude-cognitive
- Repo: [github.com/GMaN1911/claude-cognitive](https://github.com/GMaN1911/claude-cognitive)
- Working memory with attention-based file injection
- HOT (>0.8, full file) -> WARM (0.25-0.8, headers) -> COLD (<0.25, evicted)
- 64-95% token savings, tested on 1M+ lines with 8 concurrent instances

### 3.6 Cozempic
- Repo: [github.com/Ruya-AI/cozempic](https://github.com/Ruya-AI/cozempic)
- 13 composable strategies for context cleaning
- Guard daemon with tiered pruning
- Python, zero dependencies

---

## Category 4: Full Frameworks (hours to set up)

### 4.1 Continuous-Claude v3
- Repo: [github.com/parcadei/Continuous-Claude-v3](https://github.com/parcadei/Continuous-Claude-v3)
- Philosophy: "Compound, don't compact"
- 32 agents, 109 skills, 30 hooks, PostgreSQL + pgvector
- Continuity Ledgers, YAML Handoffs, TLDR Code Analysis (95% token savings)

### 4.2 Meridian
- Repo: [github.com/markmdev/meridian](https://github.com/markmdev/meridian)
- 10 hooks, WORKSPACE.md as persistent state
- `pre_compaction_sync` at 150K tokens forces Claude to save decisions
- `context-acknowledgment-gate` blocks tools until agent acknowledges context

---

## Category 5: Official Anthropic Improvements

| Feature | Version | Effect |
|---------|---------|--------|
| **Session Memory** | v2.0.64+ | Background summaries, instant `/compact` |
| **Plan Mode persistence** | v2.1.3+ | Plans and To-Do survive compact |
| **PreCompact hook** | v1.0.48+ | Hook before compaction |
| **Buffer reduction** | early 2026 | +12K usable tokens (167K vs 155K) |
| **`/fork`** | recent | New session preserving history |

---

## Official GitHub Issues

| Issue | Title | Status |
|-------|-------|--------|
| [#19877](https://github.com/anthropics/claude-code/issues/19877) | Claude-invocable conditional /compact | OPEN |
| [#17237](https://github.com/anthropics/claude-code/issues/17237) | PreCompact and PostCompact hooks | OPEN (9+) |
| [#23966](https://github.com/anthropics/claude-code/issues/23966) | Auto-compact and continue when limit reached | OPEN |
| [#26317](https://github.com/anthropics/claude-code/issues/26317) | Compact fails with "too long" | OPEN |
| [#15923](https://github.com/anthropics/claude-code/issues/15923) | Pre-compaction hook | CLOSED (implemented) |
| [#14160](https://github.com/anthropics/claude-code/issues/14160) | Custom instructions for auto-compact | CLOSED |
| [#6390](https://github.com/anthropics/claude-code/issues/6390) | Context Pruning alternative | OPEN |
| [#14258](https://github.com/anthropics/claude-code/issues/14258) | PostCompact Hook Event | OPEN |

---

## Comparison Table

| Solution | Complexity | Quality | Setup Time | Approach |
|----------|-----------|---------|------------|----------|
| Built-in `/compact` | - | Low | 0 | Lossy summarization |
| `/compact` + instructions | Low | Medium | 0 | Guided summarization |
| AUTOCOMPACT_PCT=70 | Low | Medium- | 1 min | Early trigger |
| c0ntextKeeper | Medium | High | 10 min | Auto-archive + MCP search |
| CMV (trim) | Medium | **Very High** | 30 min | Trim bloat, keep verbatim |
| MCP Memory Keeper | Medium | High | 15 min | Checkpoint/restore |
| ContextRecoveryHook | Medium | High | 30 min | Incremental backup |
| claude-mem | Medium | High | 10 min | AI compression + vector search |
| Meridian | High | Very High | 1 hour | WORKSPACE.md evolution |
| Continuous-Claude v3 | Very High | Maximum | Hours | "Compound, don't compact" |

---

## Key Insight

**Root cause:** Built-in compact is **lossy summarization**. AI summarizes AI conversation, inevitably losing details. Good solutions use one of two approaches:

1. **Trim, not summarize** (CMV) -- removes bloat (tool output, thinking blocks), keeps conversation verbatim. 85% reduction without meaning loss.
2. **Compound, don't compact** (Continuous-Claude) -- extracts knowledge to persistent files before compact, then `/clear` and loads structured context.

---

## Curated Lists

- [awesome-claude-code](https://github.com/hesreallyhim/awesome-claude-code)
- [awesome-claude-code-toolkit](https://github.com/rohitg00/awesome-claude-code-toolkit) (135 agents, 35 skills, 42 commands, 19 hooks)
- [claude-code-hooks-mastery](https://github.com/disler/claude-code-hooks-mastery)
- [Official Hooks Reference](https://code.claude.com/docs/en/hooks)
- [Official Best Practices](https://code.claude.com/docs/en/best-practices)
- [Effective Context Engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) (Anthropic official)

---

## Selected Approach

**B: Custom MCP Memory Server**
- Python (FastAPI/stdio) + SQLite + FTS5
- Hooks: PreCompact (auto-save), SessionStart (auto-inject)
- MCP Tools: `memory_save`, `memory_search`, `memory_recent`, `memory_project`
- MEMORY.md remains for high-level facts, MCP for details
- Cross-session, cross-project knowledge accumulation
