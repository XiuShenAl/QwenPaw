# -*- coding: utf-8 -*-
"""Native AgentScope 2.0 middleware implementations for QwenPaw.

Most per-request setup (ContextVars,
bootstrap injection, skill env overrides, file/media processing) is
handled by lifecycle hooks.  The only middleware that remains is
``context_manager`` (a MiddlewareBase that intercepts each reasoning
turn for dialog-path resolution and tool-result pruning).

This module is retained as a namespace for any future middleware that
must wrap the agent's inner reasoning loop (as opposed to pre/post
execution hooks).
"""
