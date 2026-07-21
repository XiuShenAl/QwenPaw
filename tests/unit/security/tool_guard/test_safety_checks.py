# -*- coding: utf-8 -*-
"""Tests for shared safety check primitives."""
from __future__ import annotations

import pytest

from qwenpaw.security.tool_guard.safety_checks import (
    classify_destructive_command,
    is_command_catastrophic,
    is_command_destructive,
    is_path_outside_boundary,
)


class TestIsCommandDestructive:
    """Verify destructive command pattern matching."""

    @pytest.mark.parametrize(
        "command",
        [
            "rm -rf /",
            "rm -rf /*",
            "rm -f -r /",
            "rm --force --recursive /",
            "rm -rf /./",
            "rm -rf //",
            "rm -rf /tmp/..",
            "rm -rf /tmp/../",
            "rm -rf /tmp/../etc",
            "rm -rf /home",
            "rm -rf /home/alice",
            "rm -rf /Users/alice",
            "rm -rf /root",
            "rm -rf /boot",
            "rm -rf /dev",
            "rm -rf /Applications",
            "rm -rf /var/lib",
            "rm -rf /private/etc",
            "rm -rf /etc/passwd",
            "rm -rf '/home/alice'",
            'rm -rf "/Users/alice"',
            "rm -rf '/'",
            "rm --recursive ~",
            "rm -rf '~'",
            "rm -rf $HOME",
            "rm -rf ${HOME}",
            'rm -rf "$HOME"',
            "rm -rf %USERPROFILE%",
            "rm -rf *",
            "mkfs.ext4 /dev/sda1",
            "mke2fs /dev/sdb",
            "dd if=/dev/zero of=/dev/sda",
            "shutdown now",
            "reboot",
            "halt",
            "poweroff",
            "sudo reboot",
            "echo hi; reboot",
            ": () { : | : & } ; :",
            # Windows catastrophic patterns
            "Remove-Item -Recurse -Force C:\\",
            "Remove-Item -Recurse -Force C:\\*",
            'Remove-Item -Recurse -Force "C:\\"',
            "rm -Recurse -Force C:\\",
            'rm -Recurse -Force "C:\\"',
            "del /s /q C:\\",
            "del /s /q C:\\*",
            'del /s /q "C:\\"',
            "rd /s /q C:\\",
            'rd /s /q "C:\\"',
            "rmdir /s /q C:\\",
            "format C:",
        ],
    )
    def test_blocks_known_dangerous_commands(self, command: str) -> None:
        assert is_command_destructive(command) is True

    @pytest.mark.parametrize(
        "command",
        [
            "ls -la",
            "echo hello",
            "cat README.md",
            "git status",
            "python3 script.py",
            "rm file.txt",
            "rm -f single_file.log",
            "mkdir new_dir",
            # Must NOT treat ordinary temp / workspace trees as root wipes.
            "rm -rf /tmp",
            "rm -rf /tmp/cache",
            "rm -rf '/tmp/cache'",
            "rm -rf /var/folders/xx/workspace/build",
            "rm -rf /private/var/folders/xx/workspace/build",
            "rm -rf /homeless",
            # Substring / script-name false positives must not hard-match.
            "echo reboot later",
            "npm run reboot",
            "git checkout --orphan reboot",
            "python -c 'print(\"shutdown\")'",
            "echo mkfs later",
            # Windows non-catastrophic / non-recursive.
            "Remove-Item -Recurse -Force C:\\Users\\me\\project\\build",
            "del /s /q D:\\work\\out\\*",
            "rd /s /q C:\\Users\\me\\project",
            "del C:\\",
            "rd C:\\",
        ],
    )
    def test_allows_safe_commands(self, command: str) -> None:
        assert is_command_destructive(command) is False

    def test_case_insensitive_matching(self) -> None:
        assert is_command_destructive("SHUTDOWN now") is True
        assert is_command_destructive("ReBoot") is True
        assert is_command_destructive("RM -RF /") is True
        assert (
            is_command_destructive("remove-item -recurse -force c:\\") is True
        )

    def test_workspace_absolute_path_not_catastrophic(self, tmp_path) -> None:
        """Workspace abs paths under temp trees must not be catastrophic."""
        target = tmp_path / "build"
        target.mkdir()
        assert is_command_destructive(f"rm -rf {target}") is False

    def test_classify_separates_catastrophic_from_system_power(self) -> None:
        assert classify_destructive_command("rm -rf /") == "catastrophic"
        assert classify_destructive_command("reboot") == "system_power"
        assert classify_destructive_command("npm run reboot") is None
        assert is_command_catastrophic("rm -rf /") is True
        assert is_command_catastrophic("reboot") is False


class TestIsPathOutsideBoundary:
    """Verify path boundary checking."""

    def test_path_inside_cwd(self, tmp_path) -> None:
        cwd = str(tmp_path)
        assert is_path_outside_boundary("subdir/file.txt", cwd) is False
        assert (
            is_path_outside_boundary(str(tmp_path / "file.txt"), cwd) is False
        )

    def test_path_outside_cwd(self, tmp_path) -> None:
        cwd = str(tmp_path)
        assert is_path_outside_boundary("/etc/passwd", cwd) is True
        assert is_path_outside_boundary("/tmp/outside", cwd) is True

    def test_relative_path_resolved_inside(self, tmp_path) -> None:
        cwd = str(tmp_path)
        subdir = tmp_path / "sub"
        subdir.mkdir()
        assert is_path_outside_boundary("sub/../file.txt", cwd) is False

    def test_relative_path_traversal_outside(self, tmp_path) -> None:
        inner = tmp_path / "inner"
        inner.mkdir()
        assert is_path_outside_boundary("../outside.txt", str(inner)) is True

    def test_tilde_expansion(self, tmp_path) -> None:
        # ~ expands to home dir which is almost certainly outside tmp_path
        cwd = str(tmp_path)
        assert is_path_outside_boundary("~/some_file", cwd) is True

    def test_sibling_directory_bypass_blocked(self, tmp_path) -> None:
        """A sibling whose name shares a prefix must NOT pass the check.

        String-prefix matching (``startswith``) would incorrectly allow
        ``/tmp/project_evil/file`` when cwd is ``/tmp/project`` because
        the string starts with the cwd prefix.  ``is_relative_to``
        handles this correctly.
        """
        project = tmp_path / "project"
        project.mkdir()
        evil = tmp_path / "project_evil"
        evil.mkdir()
        target = evil / "secret.txt"
        target.touch()
        assert is_path_outside_boundary(str(target), str(project)) is True

    def test_exact_cwd_path_is_inside(self, tmp_path) -> None:
        cwd = str(tmp_path)
        assert is_path_outside_boundary(cwd, cwd) is False

    def test_nonexistent_path_inside_cwd(self, tmp_path) -> None:
        assert is_path_outside_boundary("nonexistent", str(tmp_path)) is False
