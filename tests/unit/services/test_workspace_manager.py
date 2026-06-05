# -*- coding: utf-8 -*-
"""Unit tests for WorkspaceManager + Sandbox interface stubs."""

from __future__ import annotations

from pathlib import Path

import pytest

from qwenpaw.services.workspace_manager import (
    Sandbox,
    SandboxViolationError,
    WorkspaceManager,
)


def test_workspace_manager_instantiates() -> None:
    wm = WorkspaceManager(working_dir=Path("/tmp/test"))
    assert wm.working_dir == Path("/tmp/test")
    assert wm.sandbox is None


def test_workspace_manager_with_sandbox() -> None:
    sb = Sandbox(allowed_paths=[Path("/tmp")])
    wm = WorkspaceManager(working_dir=Path("/tmp"), sandbox=sb)
    assert wm.sandbox is sb


@pytest.mark.asyncio
async def test_workspace_manager_start_stop_are_no_op() -> None:
    wm = WorkspaceManager(working_dir=Path("/tmp/test"))
    await wm.start()
    await wm.stop()


def test_sandbox_instantiates_with_defaults() -> None:
    sb = Sandbox()
    assert sb.allowed_paths == []
    assert sb.denied_tools == set()
    assert sb.shell_executable == "/bin/sh"
    assert sb.shell_timeout == 60


def test_sandbox_check_path_raises_not_implemented() -> None:
    sb = Sandbox()
    with pytest.raises(NotImplementedError):
        sb.check_path("/tmp/foo", "read")


def test_sandbox_check_tool_raises_not_implemented() -> None:
    sb = Sandbox()
    with pytest.raises(NotImplementedError):
        sb.check_tool("shell")


def test_sandbox_violation_error_is_exception() -> None:
    assert issubclass(SandboxViolationError, Exception)
    err = SandboxViolationError("path violation")
    assert str(err) == "path violation"
