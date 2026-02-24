#!/usr/bin/env bash
# CC-Memory installation script
# Usage: ./scripts/install.sh [--dry-run] [--uninstall]

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SETTINGS_FILE="$HOME/.claude/settings.json"
DB_DIR="$HOME/.cc-memory"

DRY_RUN=false
UNINSTALL=false

for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=true ;;
        --uninstall) UNINSTALL=true ;;
        *) echo "Unknown option: $arg"; exit 1 ;;
    esac
done

info() { echo "[CC-Memory] $*"; }
dry() { if $DRY_RUN; then info "(dry-run) Would: $*"; else info "$*"; fi; }

if $UNINSTALL; then
    info "Uninstalling CC-Memory..."

    # Remove MCP server
    dry "Remove MCP server 'cc-memory'"
    if ! $DRY_RUN; then
        claude mcp remove cc-memory 2>/dev/null || true
    fi

    # Remove hooks from settings.json
    if [ -f "$SETTINGS_FILE" ] && command -v jq &>/dev/null; then
        dry "Remove CC-Memory hooks from $SETTINGS_FILE"
        if ! $DRY_RUN; then
            # Remove PreCompact hooks with cc-memory in command
            tmp=$(mktemp)
            jq '
                (.hooks.PreCompact // []) |= [.[] | select(.hooks | all(.command | test("cc-memory") | not))] |
                (.hooks.SessionStart // []) |= [.[] | select(.hooks | all(.command | test("cc-memory") | not))] |
                (.hooks.UserPromptSubmit // []) |= [.[] | select(.hooks | all(.command | test("cc-memory") | not))] |
                # Clean up empty arrays
                if .hooks.PreCompact == [] then del(.hooks.PreCompact) else . end |
                if .hooks.SessionStart == [] then del(.hooks.SessionStart) else . end |
                if .hooks.UserPromptSubmit == [] then del(.hooks.UserPromptSubmit) else . end
            ' "$SETTINGS_FILE" > "$tmp" && mv "$tmp" "$SETTINGS_FILE"
        fi
    fi

    info "Uninstall complete. DB files in $DB_DIR were preserved."
    exit 0
fi

# ── Install ──────────────────────────────────────────────────────

info "Installing CC-Memory..."

# 1. Install package
dry "Install package with uv"
if ! $DRY_RUN; then
    cd "$PROJECT_DIR"
    uv sync
fi

# 2. Create DB directory
dry "Create DB directory: $DB_DIR"
if ! $DRY_RUN; then
    mkdir -p "$DB_DIR"
fi

# 3. Add MCP server to Claude Code
dry "Register MCP server 'cc-memory'"
if ! $DRY_RUN; then
    claude mcp remove cc-memory 2>/dev/null || true
    claude mcp add cc-memory -- uv run --directory "$PROJECT_DIR" cc-memory-server
fi

# 4. Add hooks to settings.json
if [ -f "$SETTINGS_FILE" ] && command -v jq &>/dev/null; then
    dry "Add hooks to $SETTINGS_FILE"
    if ! $DRY_RUN; then
        tmp=$(mktemp)

        # PreCompact hook
        PRE_COMPACT_CMD="uv run --directory $PROJECT_DIR cc-memory-pre-compact"
        SESSION_START_CMD="uv run --directory $PROJECT_DIR cc-memory-session-start"
        USER_PROMPT_CMD="uv run --directory $PROJECT_DIR cc-memory-user-prompt"

        jq --arg pc "$PRE_COMPACT_CMD" --arg ss "$SESSION_START_CMD" --arg up "$USER_PROMPT_CMD" '
            # Ensure hooks object exists
            .hooks //= {} |

            # Add PreCompact if not already present
            .hooks.PreCompact //= [] |
            if (.hooks.PreCompact | map(.hooks[]?.command) | any(test("cc-memory"))) then . else
                .hooks.PreCompact += [{"matcher": "", "hooks": [{"type": "command", "command": $pc, "timeout": 30000}]}]
            end |

            # Add SessionStart if not already present
            .hooks.SessionStart //= [] |
            if (.hooks.SessionStart | map(.hooks[]?.command) | any(test("cc-memory"))) then . else
                .hooks.SessionStart += [{"matcher": "", "hooks": [{"type": "command", "command": $ss, "timeout": 10000}]}]
            end |

            # Add UserPromptSubmit if not already present
            .hooks.UserPromptSubmit //= [] |
            if (.hooks.UserPromptSubmit | map(.hooks[]?.command) | any(test("cc-memory"))) then . else
                .hooks.UserPromptSubmit += [{"matcher": "", "hooks": [{"type": "command", "command": $up, "timeout": 5000}]}]
            end
        ' "$SETTINGS_FILE" > "$tmp" && mv "$tmp" "$SETTINGS_FILE"
    fi
else
    info "WARNING: jq not found or settings.json missing. Add hooks manually."
    info "See docs/plans/20260225-cc-memory-mcp-server.md for hook configuration."
fi

info "Installation complete!"
info ""
info "MCP server: cc-memory (stdio)"
info "DB path: $DB_DIR/memories.db"
info "Hooks: PreCompact, SessionStart, UserPromptSubmit"
info ""
info "Test with: claude mcp list | grep cc-memory"
