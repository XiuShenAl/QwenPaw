# -*- coding: utf-8 -*-
"""Auto-detect OpenClaw installation and parse configuration."""
from __future__ import annotations

import logging
from pathlib import Path

from ..models import SourceInfo
from ._json5 import parse_json5

logger = logging.getLogger(__name__)

_CANDIDATE_ROOTS = ["~/.openclaw", "~/.clawdbot", "~/.moltbot"]
_CONFIG_NAMES = ["openclaw.json", "clawdbot.json", "moltbot.json"]
_FLAVOR_MAP = {
    "openclaw.json": "openclaw",
    "clawdbot.json": "clawdbot",
    "moltbot.json": "clawdbot",
}


def detect(source: Path | None = None, agent_id: str = "main") -> SourceInfo:
    root = _find_root(source)
    config_path, flavor = _find_config(root)
    logger.info("Found %s config at %s", flavor, config_path)

    config = parse_json5(config_path.read_text(encoding="utf-8"))
    env = _parse_dotenv(root / ".env")
    workspace = _resolve_workspace(root, config, agent_id)

    sessions_dir = root / "agents" / agent_id / "sessions"
    if not sessions_dir.is_dir():
        sessions_dir = None

    cron_path = _resolve_cron_path(root, config)

    env_from_config = _parse_config_env(config)
    merged_env = {**env_from_config, **env}

    auth_keys = _parse_auth_profiles(root, agent_id)
    for k, v in auth_keys.items():
        merged_env.setdefault(k, v)

    return SourceInfo(
        root=root,
        flavor=flavor,
        config=config,
        env=merged_env,
        workspace=workspace,
        agent_id=agent_id,
        sessions_dir=sessions_dir,
        cron_path=cron_path,
    )


def _find_root(source: Path | None) -> Path:
    if source is not None:
        resolved = Path(source).expanduser().resolve()
        if resolved.is_dir():
            return resolved
        raise FileNotFoundError(
            f"OpenClaw directory not found: {resolved}",
        )
    for candidate in _CANDIDATE_ROOTS:
        path = Path(candidate).expanduser().resolve()
        if path.is_dir():
            logger.debug("Auto-detected root: %s", path)
            return path
    raise FileNotFoundError(
        f"No OpenClaw installation found. Tried: {_CANDIDATE_ROOTS}",
    )


def _find_config(root: Path) -> tuple[Path, str]:
    for name in _CONFIG_NAMES:
        path = root / name
        if path.is_file():
            return path, _FLAVOR_MAP[name]
    raise FileNotFoundError(
        f"No config file found in {root}. Tried: {_CONFIG_NAMES}",
    )


def _parse_dotenv(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        if not _:
            continue
        value = value.strip()
        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in ('"', "'")
        ):
            value = value[1:-1]
        env[key.strip()] = value
    return env


def _resolve_cron_path(root: Path, config: dict) -> Path | None:
    custom_store = (config.get("cron") or {}).get("store")
    if custom_store:
        p = Path(custom_store).expanduser().resolve()
        if p.is_file():
            return p

    candidates = [
        root / "cron" / "store.json",
        root / "cron" / "cron.json",
        root / "state" / "cron" / "store.json",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _parse_config_env(config: dict) -> dict[str, str]:
    """Extract env vars from openclaw.json ``env`` / ``env.vars``."""
    json_env = config.get("env")
    if not isinstance(json_env, dict):
        return {}
    result: dict[str, str] = {}
    sources = [json_env]
    env_vars = json_env.get("vars")
    if isinstance(env_vars, dict):
        sources.append(env_vars)
    for src in sources:
        for key, val in src.items():
            if key == "vars":
                continue
            if isinstance(val, str) and val.strip():
                result.setdefault(key, val.strip())
    return result


def _parse_auth_profiles(root: Path, agent_id: str) -> dict[str, str]:
    """Extract API keys from ``agents/<id>/agent/auth-profiles.json``."""
    auth_path = root / "agents" / agent_id / "agent" / "auth-profiles.json"
    if not auth_path.is_file():
        return {}
    result: dict[str, str] = {}
    _name_to_env = {
        "openrouter": "OPENROUTER_API_KEY",
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "gemini": "GEMINI_API_KEY",
    }
    try:
        import json

        data = json.loads(auth_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return result
        profiles = (
            data.get("profiles", data)
            if isinstance(data.get("profiles"), dict)
            else data
        )
        for name, entry in profiles.items():
            if not isinstance(entry, dict):
                continue
            api_key = entry.get("key", "") or entry.get("apiKey", "")
            if not isinstance(api_key, str) or not api_key.strip():
                continue
            for pattern, env_var in _name_to_env.items():
                if pattern in name.lower():
                    result.setdefault(env_var, api_key.strip())
                    break
    except (json.JSONDecodeError, OSError):
        pass
    return result


def _resolve_workspace(root: Path, config: dict, agent_id: str) -> Path:
    try:
        ws = config["agents"]["defaults"]["workspace"]
        path = Path(ws).expanduser().resolve()
        if path.is_dir():
            return path
    except (KeyError, TypeError):
        pass

    candidates = [
        root / "agents" / agent_id / "workspace",
        root / f"workspace-{agent_id}",
        root / "workspace-main",
        root / "workspace",
        root / "workspace.default",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return root / "workspace"
