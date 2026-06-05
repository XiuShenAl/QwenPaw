# -*- coding: utf-8 -*-
"""Phase 6 — auto-register HTTP routes and slash commands from ``@api_action``.

``register_http_routes`` scans every :class:`ManagerBase` subclass in a
:class:`ManagerRegistry` and creates FastAPI endpoints for actions whose
``methods`` include ``"http"``.

``collect_slash_specs_from_api_actions`` does the same for ``"slash"``
methods, returning :class:`CommandSpec` instances for the per-Kernel
:class:`SlashCommandRegistry`.

See ``RUNTIME_REFACTOR_PSEUDOCODE.md`` §7.2 / §7.4.
"""

from __future__ import annotations

import inspect
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import FastAPI

    from ..api_action import ApiActionSpec, ManagerRegistry
    from ..runtime.slash_command_registry import CommandSpec

logger = logging.getLogger(__name__)


# ======================================================================
# HTTP route auto-registration
# ======================================================================


def _make_endpoint(
    spec: "ApiActionSpec",
    instance_getter: Any,
    app: "FastAPI",
) -> Any:
    """Build a FastAPI endpoint closure with a clean signature.

    D1 (pseudocode §7.2): closure vars must be hidden from
    ``inspect.signature`` so FastAPI doesn't treat them as query params.
    """
    request_model = spec.request_model

    if request_model is None:

        async def endpoint() -> Any:
            mgr = instance_getter(app)
            return await getattr(mgr, spec.name)()

        return endpoint

    async def endpoint_with_body(body: Any) -> Any:  # type: ignore[override]
        mgr = instance_getter(app)
        data = body.dict() if hasattr(body, "dict") else dict(body)
        return await getattr(mgr, spec.name)(**data)

    endpoint_with_body.__signature__ = inspect.Signature(
        parameters=[
            inspect.Parameter(
                "body",
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=request_model,
            ),
        ],
    )
    return endpoint_with_body


def register_http_routes(
    app: "FastAPI",
    registry: "ManagerRegistry",
) -> int:
    """Scan *registry* and mount auto-generated HTTP routes on *app*.

    Returns the number of routes registered.
    """
    count = 0
    for mgr_cls, instance_getter in registry.iter_managers():
        prefix = getattr(mgr_cls, "endpoint_prefix", "") or ""
        for spec in getattr(mgr_cls, "_api_actions", []):
            if "http" not in spec.methods:
                continue
            path = spec.http_path or f"/{prefix}/{spec.name}"
            try:
                app.add_api_route(
                    path,
                    _make_endpoint(spec, instance_getter, app),
                    methods=[spec.http_method],
                    response_model=spec.response_model,
                    name=f"auto_{mgr_cls.__name__}_{spec.name}",
                )
                count += 1
                logger.info(
                    "auto-registered HTTP %s %s",
                    spec.http_method,
                    path,
                )
            except Exception:
                logger.exception(
                    "Failed to register HTTP route %s %s",
                    spec.http_method,
                    path,
                )
    return count


# ======================================================================
# Slash command auto-collection
# ======================================================================


def collect_slash_specs_from_api_actions(
    registry: "ManagerRegistry",
) -> "list[CommandSpec]":
    """Convert ``@api_action(methods={..., "slash"})`` specs to CommandSpecs.

    Each CommandSpec adapter calls ``instance_getter(app_state)`` at
    dispatch time then invokes the manager method with parsed args.
    """
    from ..runtime.slash_command_registry import CommandSpec

    specs: list[CommandSpec] = []
    for mgr_cls, instance_getter in registry.iter_managers():
        for action_spec in getattr(mgr_cls, "_api_actions", []):
            if "slash" not in action_spec.methods:
                continue

            cmd_name = action_spec.slash_command or action_spec.name

            async def _adapter(
                ctx: Any,
                args: str,
                _spec: Any = action_spec,
                _get: Any = instance_getter,
            ) -> Any:
                from agentscope.message import Msg
                from agentscope.message._block import TextBlock

                app_state = getattr(ctx, "app_services", None)
                mgr = _get(app_state)
                method = getattr(mgr, _spec.name)
                if args.strip():
                    result = await method(args.strip())
                else:
                    result = await method()
                if isinstance(result, Msg):
                    return result
                return Msg(
                    name="assistant",
                    role="assistant",
                    content=[TextBlock(type="text", text=str(result))],
                )

            specs.append(
                CommandSpec(
                    name=cmd_name,
                    handler=_adapter,
                    category="auto",
                    help_text=(
                        f"Auto-generated from "
                        f"{mgr_cls.__name__}.{action_spec.name}"
                    ),
                ),
            )
    return specs


__all__ = [
    "collect_slash_specs_from_api_actions",
    "register_http_routes",
]
