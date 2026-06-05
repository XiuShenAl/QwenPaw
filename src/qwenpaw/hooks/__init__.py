# -*- coding: utf-8 -*-
"""Business-layer hook base class (Phase 1 skeleton).

Concrete hooks (session load/save, bootstrap, skill env, cron triggers
…) arrive in Phase 5. This package exists in Phase 1 so future authors
have a stable import path (``qwenpaw.hooks.LifecycleHook``).
"""

from __future__ import annotations

from .base import LifecycleHook

__all__ = ["LifecycleHook"]
