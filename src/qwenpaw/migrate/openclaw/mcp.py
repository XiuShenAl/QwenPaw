# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
from functools import partial
from pathlib import Path

from ..models import ItemStatus, MigrationItem, SourceInfo

logger = logging.getLogger(__name__)


def _write_mcp_client(target_workspace: Path, key: str, client_config: dict):
    agent_json = target_workspace / "agent.json"
    data = {}
    if agent_json.exists():
        data = json.loads(agent_json.read_text(encoding="utf-8"))
    mcp = data.setdefault("mcp", {})
    clients = mcp.setdefault("clients", {})
    clients[key] = client_config
    agent_json.parent.mkdir(parents=True, exist_ok=True)
    agent_json.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


_FIELD_MAP = (
    ("command", "command"),
    ("args", "args"),
    ("env", "env"),
    ("url", "url"),
    ("headers", "headers"),
)


def _build_client_config(srv: dict) -> dict:
    """Build QwenPaw MCP client config from OpenClaw server config."""
    if srv.get("command"):
        transport = "stdio"
    elif srv.get("url"):
        transport = "streamable_http"
    else:
        transport = "stdio"

    enabled = srv.get("enabled", True)
    client_config: dict = {"transport": transport, "enabled": enabled}

    for src_key, dst_key in _FIELD_MAP:
        val = srv.get(src_key)
        if val:
            client_config[dst_key] = val

    cwd = srv.get("cwd") or srv.get("workingDirectory")
    if cwd:
        client_config["cwd"] = cwd

    if srv.get("timeout"):
        client_config["timeout"] = srv["timeout"]
    if srv.get("connectTimeout"):
        client_config["connect_timeout"] = srv["connectTimeout"]

    tools_cfg = srv.get("toolFilter") or srv.get("tools") or {}
    if tools_cfg.get("include") or tools_cfg.get("exclude"):
        tool_filter: dict = {}
        if tools_cfg.get("include"):
            tool_filter["include"] = tools_cfg["include"]
        if tools_cfg.get("exclude"):
            tool_filter["exclude"] = tools_cfg["exclude"]
        client_config["tools"] = tool_filter

    return client_config


def plan_mcp_migration(
    source: SourceInfo,
    target_workspace: Path,
    overwrite: bool,
) -> list[MigrationItem]:
    items: list[MigrationItem] = []

    mcp_servers = source.config.get("mcp", {}).get("servers", {})
    if not mcp_servers:
        return items

    existing_clients: dict = {}
    agent_json = target_workspace / "agent.json"
    if agent_json.exists():
        data = json.loads(agent_json.read_text(encoding="utf-8"))
        existing_clients = data.get("mcp", {}).get("clients", {})

    for key, srv in mcp_servers.items():
        if not isinstance(srv, dict):
            continue
        if key in existing_clients and not overwrite:
            items.append(
                MigrationItem(
                    category="mcp",
                    source_path=f"config.mcp.servers.{key}",
                    target_path=f"agent.json#mcp.clients.{key}",
                    status=ItemStatus.CONFLICT,
                    detail=(f"MCP client '{key}' already exists"),
                    write_fn=None,
                ),
            )
            continue

        client_config = _build_client_config(srv)
        transport = client_config["transport"]

        items.append(
            MigrationItem(
                category="mcp",
                source_path=f"config.mcp.servers.{key}",
                target_path=f"agent.json#mcp.clients.{key}",
                status=ItemStatus.OK,
                detail=f"MCP server '{key}' ({transport})",
                write_fn=partial(
                    _write_mcp_client,
                    target_workspace,
                    key,
                    client_config,
                ),
            ),
        )

    return items
