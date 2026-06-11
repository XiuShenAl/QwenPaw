# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for WorkspaceRegistry."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

from qwenpaw.app.workspace_registry import WorkspaceRegistry
from qwenpaw.app.workspace.workspace import Workspace


class TestWorkspaceRegistry:
    def test_inherits_multi_agent_manager(self):
        from qwenpaw.app.multi_agent_manager import MultiAgentManager

        assert issubclass(WorkspaceRegistry, MultiAgentManager)

    def test_create_workspace_produces_bootstrapped_workspace(self):
        reg = WorkspaceRegistry(app_services=None)

        def _stub_workspace_init(self_obj, agent_id, workspace_dir):
            self_obj.agent_id = agent_id
            self_obj.workspace_dir = Path(workspace_dir)

        with patch.object(Workspace, "__init__", _stub_workspace_init), patch(
            "qwenpaw.app.workspace.workspace.QwenPawLocalWorkspace",
        ):
            ws = reg._create_workspace("test", "/tmp/test")
            assert isinstance(ws, Workspace)

    def test_stores_app_services(self):
        svc = MagicMock()
        reg = WorkspaceRegistry(app_services=svc)
        assert reg.app_services is svc
