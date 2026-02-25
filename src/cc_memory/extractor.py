"""JSONL transcript extractor — parses Claude Code transcripts into memories."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# Privacy patterns: skip content matching these
SENSITIVE_PATTERNS = [
    re.compile(r"\.env\b"),
    re.compile(r"credentials", re.IGNORECASE),
    re.compile(r"\bsecret\b", re.IGNORECASE),
    re.compile(r"(?:access|auth|bearer|refresh|api)[_\s]?token", re.IGNORECASE),
    re.compile(r"\bpassword\b", re.IGNORECASE),
    re.compile(r"api[_.]?key", re.IGNORECASE),
    re.compile(r"private[_.]?key", re.IGNORECASE),
    re.compile(r"<private>.*?</private>", re.DOTALL),
    # SSH keys and certificates
    re.compile(r"\bid_rsa\b|\bid_ed25519\b|ssh_host_.*_key", re.IGNORECASE),
    re.compile(r"\.pem\b|\.p12\b|\.pfx\b", re.IGNORECASE),
    # Connection strings with embedded credentials
    re.compile(r"(?:postgresql|mysql|mongodb|redis)://[^\s]+", re.IGNORECASE),
    # AWS credentials
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
    re.compile(r"aws_secret_access_key", re.IGNORECASE),
]

# Task patterns in assistant text
_TODO_RE = re.compile(r"(?:TODO|FIXME):\s*(.+)", re.IGNORECASE)
_NEXT_RE = re.compile(r"NEXT:\s*(.+)", re.IGNORECASE)

# Learning patterns in assistant text
_INSIGHT_RE = re.compile(r"(?:Insight|★ Insight)[:\s]+(.+?)(?:\n|$)", re.IGNORECASE)
_LEARNED_RE = re.compile(r"(?:learned|I learned|оказалось)[:\s]+(.+?)(?:\n|$)", re.IGNORECASE)


class Extractor:
    """Parses JSONL transcripts and extracts structured memories."""

    def __init__(self, jsonl_path: str | Path) -> None:
        self.path = Path(jsonl_path)
        self.messages: list[dict[str, Any]] = []
        self._parse()

    def _parse(self) -> None:
        """Read and parse JSONL file."""
        with open(self.path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    self.messages.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    def _is_sensitive(self, content: str) -> bool:
        """Check if content contains sensitive information."""
        for pattern in SENSITIVE_PATTERNS:
            if pattern.search(content):
                return True
        return False

    def _get_assistant_texts(self) -> list[str]:
        """Extract all text blocks from assistant messages."""
        texts = []
        for msg in self.messages:
            if msg.get("type") != "assistant":
                continue
            message = msg.get("message", {})
            content = message.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "")
                        if text and not self._is_sensitive(text):
                            texts.append(text)
            elif isinstance(content, str) and not self._is_sensitive(content):
                texts.append(content)
        return texts

    def _get_tool_uses(self) -> list[dict[str, Any]]:
        """Extract all tool_use blocks from assistant messages."""
        tool_uses = []
        for msg in self.messages:
            if msg.get("type") != "assistant":
                continue
            message = msg.get("message", {})
            content = message.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        tool_uses.append(block)
        return tool_uses

    def _get_tool_results(self) -> dict[str, dict[str, Any]]:
        """Extract tool results keyed by tool_use_id."""
        results: dict[str, dict[str, Any]] = {}
        for msg in self.messages:
            if msg.get("type") != "user":
                continue
            message = msg.get("message", {})
            content = message.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        tid = block.get("tool_use_id", "")
                        results[tid] = block
        return results

    def extract_file_changes(self) -> list[dict[str, str]]:
        """Find Write/Edit tool uses and extract file paths."""
        changes = []
        for tu in self._get_tool_uses():
            name = tu.get("name", "")
            inp = tu.get("input", {})
            file_path = inp.get("file_path", "")

            if name not in ("Write", "Edit") or not file_path:
                continue
            if self._is_sensitive(file_path):
                continue

            if name == "Write":
                summary = f"Created {file_path}"
            else:
                old = inp.get("old_string", "")[:50]
                new = inp.get("new_string", "")[:50]
                summary = f"Edited {file_path}: '{old}' → '{new}'"

            changes.append({"type": "file_change", "content": summary})
        return changes

    def extract_decisions(self) -> list[dict[str, str]]:
        """Find AskUserQuestion answers and decision patterns."""
        decisions = []
        tool_results = self._get_tool_results()

        for tu in self._get_tool_uses():
            if tu.get("name") != "AskUserQuestion":
                continue
            tid = tu.get("id", "")
            result = tool_results.get(tid, {})
            answer = result.get("content", "")
            if isinstance(answer, str) and answer and not self._is_sensitive(answer):
                questions = tu.get("input", {}).get("questions", [])
                q_text = questions[0].get("question", "") if questions else ""
                content = f"Decision: {answer}"
                if q_text:
                    content = f"{q_text} → {answer}"
                decisions.append({"type": "decision", "content": content})

        # Also look for "decided", "chose", "выбрали" patterns in text
        for text in self._get_assistant_texts():
            for pattern in [
                r"(?:decided|chose|выбрали|решили)[:\s]+(.+?)(?:\n|$)",
            ]:
                for match in re.finditer(pattern, text, re.IGNORECASE):
                    content = match.group(1).strip()
                    if content and not self._is_sensitive(content):
                        decisions.append({"type": "decision", "content": content})

        return decisions

    def extract_tasks(self) -> list[dict[str, str]]:
        """Find TODO/NEXT patterns and TaskCreate tool uses."""
        tasks = []
        for text in self._get_assistant_texts():
            for match in _TODO_RE.finditer(text):
                tasks.append({"type": "task", "content": f"TODO: {match.group(1).strip()}"})
            for match in _NEXT_RE.finditer(text):
                tasks.append({"type": "task", "content": f"NEXT: {match.group(1).strip()}"})

        # TaskCreate tool uses
        for tu in self._get_tool_uses():
            if tu.get("name") == "TaskCreate":
                inp = tu.get("input", {})
                subject = inp.get("subject", "")
                if subject and not self._is_sensitive(subject):
                    tasks.append({"type": "task", "content": f"Task: {subject}"})

        return tasks

    def extract_errors(self) -> list[dict[str, str]]:
        """Find tool results with errors."""
        errors = []
        for result in self._get_tool_results().values():
            if not result.get("is_error"):
                continue
            content = result.get("content", "")
            if isinstance(content, str) and content and not self._is_sensitive(content):
                errors.append({"type": "error", "content": content[:500]})
        return errors

    def extract_learnings(self) -> list[dict[str, str]]:
        """Find insight/learned/оказалось patterns in assistant text."""
        learnings = []
        seen = set()
        for text in self._get_assistant_texts():
            for regex in [_INSIGHT_RE, _LEARNED_RE]:
                for match in regex.finditer(text):
                    content = match.group(0).strip()
                    if content and content not in seen and not self._is_sensitive(content):
                        seen.add(content)
                        learnings.append({"type": "learning", "content": content})
        return learnings

    def extract_all(self) -> list[dict[str, str]]:
        """Combine all extractors, return flat list of memory dicts."""
        all_memories: list[dict[str, str]] = []
        all_memories.extend(self.extract_file_changes())
        all_memories.extend(self.extract_decisions())
        all_memories.extend(self.extract_tasks())
        all_memories.extend(self.extract_errors())
        all_memories.extend(self.extract_learnings())
        return all_memories
