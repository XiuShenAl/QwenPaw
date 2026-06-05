# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for KernelRegistry."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

from qwenpaw.app.kernel_registry import KernelRegistry


class TestKernelRegistry:
    def test_inherits_multi_agent_manager(self):
        from qwenpaw.app.multi_agent_manager import MultiAgentManager

        assert issubclass(KernelRegistry, MultiAgentManager)

    def test_create_workspace_produces_kernel(self):
        reg = KernelRegistry(app_services=None)
        with patch(
            "qwenpaw.app.kernel.kernel.Workspace.__init__",
            return_value=None,
        ):
            ws = reg._create_workspace("test", "/tmp/test")
            from qwenpaw.app.kernel.kernel import Kernel

            assert isinstance(ws, Kernel)

    def test_stores_app_services(self):
        svc = MagicMock()
        reg = KernelRegistry(app_services=svc)
        assert reg.app_services is svc
