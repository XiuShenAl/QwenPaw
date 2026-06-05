# -*- coding: utf-8 -*-
"""Auto-generated CLI subcommands from ``@api_action`` (Phase 6).

``auto_group`` is a Click group registered lazily in ``cli/main.py``.
``register_cli_subcommands`` scans a :class:`ManagerRegistry` and creates
one Click subcommand per action whose ``methods`` include ``"cli"``.

See ``RUNTIME_REFACTOR_PSEUDOCODE.md`` §7.3.
"""

from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING, Any

import click

from .http import client, print_json

if TYPE_CHECKING:
    from ..api_action import ManagerRegistry


def _ensure_daemon_alive(base_url: str) -> None:
    """HEAD ``/healthz`` and abort if the daemon is not reachable."""
    import httpx

    url = base_url.rstrip("/")
    try:
        r = httpx.head(f"{url}/api/version", timeout=3.0)
        r.raise_for_status()
    except Exception:
        click.echo(
            f"Error: QwenPaw daemon is not reachable at {url}. "
            "Start it with `qwenpaw app` first.",
            err=True,
        )
        sys.exit(2)


def _base_url(ctx: click.Context, base_url: str | None) -> str:
    if base_url:
        return base_url.rstrip("/")
    host = (ctx.obj or {}).get("host", "127.0.0.1")
    port = (ctx.obj or {}).get("port", 8088)
    return f"http://{host}:{port}"


@click.group("auto")
def auto_group() -> None:
    """Auto-generated commands from @api_action declarations."""


def _add_command(
    group: click.Group,
    cmd_name: str,
    help_text: str,
    spec: Any,
    prefix: str,
) -> None:
    """Register one Click subcommand for *spec*."""

    @group.command(cmd_name, help=help_text)
    @click.option(
        "--base-url",
        default=None,
        help="Override API URL.",
    )
    @click.option(
        "--data",
        default=None,
        help="JSON body for POST.",
    )
    @click.pass_context
    def _cmd(
        ctx: click.Context,
        base_url: str | None,
        data: str | None,
        _spec: Any = spec,
        _prefix: str = prefix,
    ) -> None:
        base = _base_url(ctx, base_url)
        _ensure_daemon_alive(base)
        path = _spec.http_path or f"/{_prefix}/{_spec.name}"
        with client(base) as c:
            if _spec.http_method.upper() == "GET":
                r = c.get(path)
            else:
                body = json.loads(data) if data else {}
                r = c.request(
                    _spec.http_method.upper(),
                    path,
                    json=body,
                )
            r.raise_for_status()
            print_json(r.json())


def register_cli_subcommands(
    group: click.Group,
    registry: "ManagerRegistry",
) -> int:
    """Create Click subcommands for @api_action."""
    count = 0
    for mgr_cls, _getter in registry.iter_managers():
        prefix = (
            getattr(
                mgr_cls,
                "endpoint_prefix",
                "",
            )
            or ""
        )
        for spec in getattr(mgr_cls, "_api_actions", []):
            if "cli" not in spec.methods:
                continue
            cmd_name = (
                spec.cli_command or f"{prefix}-{spec.name}"
                if prefix
                else spec.name
            )
            help_text = f"Auto: {mgr_cls.__name__}.{spec.name}"
            _add_command(
                group,
                cmd_name,
                help_text,
                spec,
                prefix,
            )
            count += 1
    return count


__all__ = ["auto_group", "register_cli_subcommands"]
