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

    return SourceInfo(
        root=root,
        flavor=flavor,
        config=config,
        env=env,
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
        root / "workspace",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return candidates[-1]
