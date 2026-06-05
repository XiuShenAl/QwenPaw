# -*- coding: utf-8 -*-
"""Per-Kernel plugin layer (HTML §0 "PLUG").

``Kernel`` extends ``Workspace`` with ``KernelPlugins`` and
``bootstrap_plugins()`` for per-Kernel registry population.
"""

from __future__ import annotations

from .kernel import Kernel
from .kernel_plugins import KernelPlugins

__all__ = ["Kernel", "KernelPlugins"]
