# Verified JSONL & Hook Format — CC-Memory

Verified: 2026-02-25, Claude Code v2.1.47

## JSONL Transcript Format

**Location:** `~/.claude/projects/[project-hash]/[uuid].jsonl`

### Message Types

| Type | Description |
|------|-------------|
| `user` | User messages and tool results |
| `assistant` | Claude's responses (text, thinking, tool_use) |
| `progress` | Hook execution progress |
| `file-history-snapshot` | File state snapshots |

### User Message

```json
{
  "type": "user",
  "message": {"role": "user", "content": "user text"},
  "sessionId": "uuid",
  "cwd": "/path/to/project",
  "uuid": "msg-uuid",
  "timestamp": "2026-02-24T18:18:07.665Z"
}
```

Content can be a **string** (plain text) or **array** (tool results):

```json
{
  "type": "user",
  "message": {
    "role": "user",
    "content": [
      {
        "type": "tool_result",
        "tool_use_id": "toolu_01ABC...",
        "content": "result text",
        "is_error": false
      }
    ]
  }
}
```

### Assistant Message

```json
{
  "type": "assistant",
  "message": {
    "role": "assistant",
    "content": [
      {"type": "thinking", "thinking": "..."},
      {"type": "text", "text": "response text"},
      {"type": "tool_use", "id": "toolu_01ABC...", "name": "Bash", "input": {"command": "ls"}}
    ]
  }
}
```

### Tool Use Input Keys (observed)

| Tool | Input Keys |
|------|------------|
| Bash | `command`, `description` |
| Read | `file_path` |
| Write | `file_path`, `content` |
| Edit | `file_path`, `old_string`, `new_string` |
| Glob | `pattern`, `path` |
| Grep | `pattern`, `path`, `output_mode` |
| Skill | `skill` |
| TaskList | (none) |
| TaskCreate | `subject`, `description`, `activeForm` |

---

## Hook I/O Format

### Common Input (all hooks receive via stdin)

```json
{
  "session_id": "abc123",
  "transcript_path": "/path/to/transcript.jsonl",
  "cwd": "/current/working/dir",
  "permission_mode": "default",
  "hook_event_name": "EventName"
}
```

### PreCompact Hook

**Input (additional fields):**
- `trigger`: `"manual"` or `"auto"`
- `custom_instructions`: user text for `/compact` (empty for auto)

**Output:** No decision control. Used for **side effects only** (save memories).
Can output `{"systemMessage": "text"}` as user warning.

### SessionStart Hook

**Input (additional fields):**
- `source`: `"startup"` | `"resume"` | `"clear"` | `"compact"`
- `model`: model ID string

**Output options:**
1. Plain text stdout → added as context for Claude
2. JSON with `hookSpecificOutput.additionalContext`:
```json
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "context text here"
  }
}
```

### UserPromptSubmit Hook

**Input (additional fields):**
- `prompt`: the user's submitted text

**Output options:**
1. Plain text stdout → added as context
2. JSON with `additionalContext`:
```json
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "context text"
  }
}
```
3. Block prompt: `{"decision": "block", "reason": "explanation"}`

### Exit Codes (all hooks)

| Code | Meaning |
|------|---------|
| 0 | Success, parse stdout as JSON |
| 2 | Blocking error (stderr fed to Claude) |
| Other | Non-blocking error (shown in verbose mode) |
