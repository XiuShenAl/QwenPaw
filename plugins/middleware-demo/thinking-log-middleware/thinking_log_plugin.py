# -*- coding: utf-8 -*-
"""Thinking Log Middleware Demo Plugin.

Demonstrates `on_reasoning` middleware that captures and prints the
model's chain-of-thought reasoning steps to stdout.

This middleware is always active (the factory unconditionally returns
an instance), showing the simplest possible registration pattern.
"""

import logging
import sys
from typing import Any, AsyncGenerator, Callable

from agentscope.middleware import MiddlewareBase
from agentscope.message import TextBlock

from qwenpaw.plugins.api import PluginApi

logger = logging.getLogger(__name__)


class ThinkingLogMiddleware(MiddlewareBase):
    """Prints each reasoning step to stdout with a [THINKING] prefix."""

    async def on_reasoning(  # pylint: disable=unused-argument
        self,
        agent: Any,
        input_kwargs: dict[str, Any],
        next_handler: Callable[..., AsyncGenerator[Any, None]],
    ) -> AsyncGenerator[Any, None]:
        events = []
        async for item in next_handler():
            events.append(item)
            yield item

        for event in events:
            if isinstance(event, TextBlock):
                text = getattr(event, "text", str(event))
                if text.strip():
                    print(
                        f"[THINKING] {text[:200]}",
                        file=sys.stdout,
                        flush=True,
                    )


def _thinking_log_factory(
    ctx: Any,
    agent_config: Any,
) -> ThinkingLogMiddleware:
    """Always create the middleware (unconditional activation)."""
    del ctx, agent_config  # unused — always active
    return ThinkingLogMiddleware()


class ThinkingLogPlugin:
    """Plugin entry point."""

    def register(self, api: PluginApi) -> None:
        api.register_middleware(_thinking_log_factory, priority=80)


plugin = ThinkingLogPlugin()
