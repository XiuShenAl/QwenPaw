# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
import re
from functools import partial
from pathlib import Path
from typing import Any

from ..models import ItemStatus, MigrationItem, SourceInfo

logger = logging.getLogger(__name__)

_ARCHIVED_PLATFORMS = {
    "whatsapp",
    "signal",
    "line",
    "nostr",
    "synology",
}

_NON_CHANNEL_KEYS = {"defaults", "modelByChannel"}


def _resolve_token(value: Any, env: dict[str, str]) -> str | None:
    if isinstance(value, str):
        match = re.fullmatch(r"\$\{(\w+)}", value)
        if match:
            return env.get(match.group(1))
        return value
    if isinstance(value, dict):
        if value.get("source") == "env":
            return env.get(value.get("id", ""))
        return None
    return None


def _get_channel_field(ch_cfg: dict, field_name: str) -> Any:
    """Get a field from channel config, checking flat and accounts.default."""
    val = ch_cfg.get(field_name)
    if val is not None:
        return val
    accounts = ch_cfg.get("accounts")
    if isinstance(accounts, dict):
        default = accounts.get("default")
        if isinstance(default, dict):
            return default.get(field_name)
    return None


def _map_allow_from(openclaw_allow: list[str] | None) -> list[str]:
    if not openclaw_allow:
        return []
    result: list[str] = []
    for e in openclaw_allow:
        s = str(e).strip()
        if s == "*":
            continue
        s = re.sub(r"^(telegram|tg):", "", s, flags=re.IGNORECASE)
        if s:
            result.append(s)
    return result


def _apply_access_control(result: dict, oc_cfg: dict) -> None:
    dm_cfg = oc_cfg.get("dm", {}) if isinstance(oc_cfg.get("dm"), dict) else {}
    dm_policy = oc_cfg.get("dmPolicy") or dm_cfg.get("policy", "open")
    if dm_policy in ("allowlist", "pairing"):
        result["access_control_dm"] = True
    else:
        result["access_control_dm"] = False

    group_policy = oc_cfg.get("groupPolicy")
    if group_policy == "allowlist":
        result["access_control_group"] = True
    elif group_policy == "open":
        result["access_control_group"] = False

    if oc_cfg.get("requireMention"):
        result["require_mention"] = True


def _extract_telegram(oc_cfg: dict, env: dict[str, str]) -> dict:
    token = _resolve_token(_get_channel_field(oc_cfg, "botToken"), env)
    allow_from = _map_allow_from(_get_channel_field(oc_cfg, "allowFrom"))
    result: dict[str, Any] = {"enabled": True}
    if token:
        result["bot_token"] = token
    if allow_from:
        result["allow_from"] = allow_from
    _apply_access_control(result, oc_cfg)
    return result


def _extract_discord(oc_cfg: dict, env: dict[str, str]) -> dict:
    token = _resolve_token(_get_channel_field(oc_cfg, "token"), env)
    dm_cfg = oc_cfg.get("dm", {}) if isinstance(oc_cfg.get("dm"), dict) else {}
    allow_from = _map_allow_from(
        dm_cfg.get("allowFrom") or _get_channel_field(oc_cfg, "allowFrom"),
    )
    result: dict[str, Any] = {"enabled": True}
    if token:
        result["bot_token"] = token
    if allow_from:
        result["allow_from"] = allow_from
    _apply_access_control(result, oc_cfg)
    return result


def _extract_slack(oc_cfg: dict, env: dict[str, str]) -> dict:
    bot_token = _resolve_token(_get_channel_field(oc_cfg, "botToken"), env)
    app_token = _resolve_token(_get_channel_field(oc_cfg, "appToken"), env)
    allow_from = _map_allow_from(_get_channel_field(oc_cfg, "allowFrom"))
    result: dict[str, Any] = {"enabled": True}
    if bot_token:
        result["bot_token"] = bot_token
    if app_token:
        result["app_token"] = app_token
    if allow_from:
        result["allow_from"] = allow_from
    _apply_access_control(result, oc_cfg)
    return result


def _extract_matrix(oc_cfg: dict, env: dict[str, str]) -> dict:
    token = _resolve_token(_get_channel_field(oc_cfg, "accessToken"), env)
    homeserver = _get_channel_field(oc_cfg, "homeserver")
    allow_from = _map_allow_from(_get_channel_field(oc_cfg, "allowFrom"))
    result: dict[str, Any] = {"enabled": True}
    if token:
        result["access_token"] = token
    if homeserver:
        result["homeserver"] = homeserver
    if allow_from:
        result["allow_from"] = allow_from
    _apply_access_control(result, oc_cfg)
    return result


def _extract_mattermost(oc_cfg: dict, env: dict[str, str]) -> dict:
    token = _resolve_token(_get_channel_field(oc_cfg, "botToken"), env)
    url = _get_channel_field(oc_cfg, "baseUrl") or _get_channel_field(
        oc_cfg,
        "url",
    )
    allow_from = _map_allow_from(_get_channel_field(oc_cfg, "allowFrom"))
    result: dict[str, Any] = {"enabled": True}
    if token:
        result["bot_token"] = token
    if url:
        result["url"] = url
    if allow_from:
        result["allow_from"] = allow_from
    _apply_access_control(result, oc_cfg)
    return result


def _extract_imessage(oc_cfg: dict, env: dict[str, str]) -> dict:
    del env
    allow_from = _map_allow_from(_get_channel_field(oc_cfg, "allowFrom"))
    result: dict[str, Any] = {"enabled": True}
    if allow_from:
        result["allow_from"] = allow_from
    _apply_access_control(result, oc_cfg)
    return result


_CHANNEL_EXTRACTORS = {
    "telegram": _extract_telegram,
    "discord": _extract_discord,
    "slack": _extract_slack,
    "matrix": _extract_matrix,
    "mattermost": _extract_mattermost,
    "imessage": _extract_imessage,
}


def _write_channel(
    target_workspace: Path,
    channel_name: str,
    channel_config: dict,
):
    agent_json = target_workspace / "agent.json"
    data = {}
    if agent_json.exists():
        data = json.loads(agent_json.read_text(encoding="utf-8"))
    channels = data.setdefault("channels", {})
    channels[channel_name] = channel_config
    agent_json.parent.mkdir(parents=True, exist_ok=True)
    agent_json.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def plan_channel_migration(
    source: SourceInfo,
    target_workspace: Path,
    overwrite: bool,
) -> list[MigrationItem]:
    items: list[MigrationItem] = []
    oc_channels: dict = source.config.get("channels", {})

    for name, oc_cfg in oc_channels.items():
        if name in _NON_CHANNEL_KEYS:
            continue
        if not isinstance(oc_cfg, dict):
            oc_cfg = {}

        if name in _ARCHIVED_PLATFORMS:
            items.append(
                MigrationItem(
                    category="channel",
                    source_path=f"channels.{name}",
                    target_path=f"agent.json#channels/{name}",
                    status=ItemStatus.ARCHIVED,
                    detail=f"Platform '{name}' is not supported in QwenPaw",
                ),
            )
            continue

        extractor = _CHANNEL_EXTRACTORS.get(name)
        if extractor is None:
            items.append(
                MigrationItem(
                    category="channel",
                    source_path=f"channels.{name}",
                    target_path=f"agent.json#channels/{name}",
                    status=ItemStatus.WARN,
                    detail=f"Unknown channel '{name}', skipped",
                ),
            )
            continue

        channel_config = extractor(oc_cfg, source.env)

        target_agent_json = target_workspace / "agent.json"
        if not overwrite and target_agent_json.exists():
            existing = json.loads(
                target_agent_json.read_text(encoding="utf-8"),
            )
            if name in existing.get("channels", {}):
                items.append(
                    MigrationItem(
                        category="channel",
                        source_path=f"channels.{name}",
                        target_path=f"agent.json#channels/{name}",
                        status=ItemStatus.CONFLICT,
                        detail=f"Channel '{name}' already exists in target",
                    ),
                )
                continue

        cfg_snapshot = channel_config.copy()
        items.append(
            MigrationItem(
                category="channel",
                source_path=f"channels.{name}",
                target_path=f"agent.json#channels/{name}",
                status=ItemStatus.OK,
                detail=f"Migrate channel '{name}'",
                write_fn=partial(
                    _write_channel,
                    target_workspace,
                    name,
                    cfg_snapshot,
                ),
            ),
        )

    return items
