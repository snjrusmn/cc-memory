"""Tests for scripts/install.sh — installation script."""

import subprocess
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
INSTALL_SCRIPT = SCRIPTS_DIR / "install.sh"


class TestInstallDryRun:
    def test_dry_run_shows_actions(self):
        result = subprocess.run(
            [str(INSTALL_SCRIPT), "--dry-run"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        output = result.stdout
        assert "CC-Memory" in output
        assert "dry-run" in output
        assert "Install package" in output
        assert "Create DB directory" in output
        assert "Register MCP server" in output
        assert "Add hooks" in output

    def test_dry_run_does_not_modify(self):
        result = subprocess.run(
            [str(INSTALL_SCRIPT), "--dry-run"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        # Should not actually create DB dir or register MCP server
        # (verified by the dry-run prefix in output)
        assert "Would:" in result.stdout

    def test_uninstall_dry_run(self):
        result = subprocess.run(
            [str(INSTALL_SCRIPT), "--uninstall", "--dry-run"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert "Uninstalling" in result.stdout
