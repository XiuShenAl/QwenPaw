# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for KernelRegistry."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

from qwenpaw.app.kernel_registry import KernelRegistry
from qwenpaw.app.workspace.workspace import Workspace


class TestKernelRegistry:
    def test_inherits_multi_agent_manager(self):
        from qwenpaw.app.multi_agent_manager import MultiAgentManager

        assert issubclass(KernelRegistry, MultiAgentManager)

    def test_create_workspace_produces_kernel(self):
        reg = KernelRegistry(app_services=None)

        def _stub_workspace_init(self_obj, agent_id, workspace_dir):
            # Set the minimal attrs that Kernel.__init__ reads
            # after super().__init__.
            self_obj.agent_id = agent_id
            self_obj.workspace_dir = Path(workspace_dir)

        with patch.object(Workspace, "__init__", _stub_workspace_init), patch(
            "qwenpaw.app.kernel.kernel.QwenPawLocalWorkspace",
        ):
            ws = reg._create_workspace("test", "/tmp/test")
            from qwenpaw.app.kernel.kernel import Kernel

            assert isinstance(ws, Kernel)

    def test_stores_app_services(self):
        svc = MagicMock()
        reg = KernelRegistry(app_services=svc)
        assert reg.app_services is svc
