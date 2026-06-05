# -*- coding: utf-8 -*-
"""QwenPaw runtime — agent lifecycle, streaming, and tool guard."""

from .stream_query import Runner
from .tool_guard import GuardedFunctionTool

__all__ = ["Runner", "GuardedFunctionTool"]

# Phase 5: new Runtime class (gated by experimental_runtime_v2 feature flag)
# Importing here for discoverability; actual usage goes
# through _app.py routing.
