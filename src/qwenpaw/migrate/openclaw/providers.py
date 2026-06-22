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

_PROVIDER_MAP = {
    "anthropic": "anthropic",
    "anthropic-messages": "anthropic",
    "openai": "openai",
    "openai-completions": "openai",
    "google": "google",
    "google-generative-ai": "google",
    "gemini": "google",
    "openrouter": "openrouter",
    "ollama": "ollama",
    "lmstudio": "lmstudio",
    "deepseek": "deepseek",
    "groq": "groq",
}

_ALLOWED_KEY_TARGETS = {
    "OPENAI_API_KEY": "openai",
    "ANTHROPIC_API_KEY": "anthropic",
    "OPENROUTER_API_KEY": "openrouter",
    "DEEPSEEK_API_KEY": "deepseek",
    "GEMINI_API_KEY": "google",
    "GROQ_API_KEY": "groq",
    "ZAI_API_KEY": "zai",
    "MINIMAX_API_KEY": "minimax",
}


def _resolve_secret_input(value: Any, env: dict[str, str]) -> str | None:
    """Resolve OpenClaw SecretInput to a plain string.

    SecretInput can be:
      - A plain string: "sk-..."
      - An env template: "${VAR_NAME}"
      - A SecretRef object: {"source": "env", "id": "VAR_NAME"}
    """
    if isinstance(value, str):
        m = re.fullmatch(r"\$\{(\w+)}", value.strip())
        if m:
            return env.get(m.group(1))
        return value.strip() or None
    if isinstance(value, dict):
        source = value.get("source", "")
        ref_id = value.get("id", "")
        if source == "env" and ref_id:
            return env.get(ref_id)
        return None
    return None


def _parse_model_ref(model_str: str) -> tuple[str, str]:
    parts = model_str.split("/", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return "", parts[0]


def _map_provider(raw_provider: str, api_type: str = "") -> str | None:
    """Resolve OpenClaw provider name or apiType to QwenPaw provider id."""
    mapped = _PROVIDER_MAP.get(raw_provider)
    if mapped:
        return mapped
    if api_type:
        mapped = _PROVIDER_MAP.get(api_type)
        if mapped:
            return mapped
    lower = raw_provider.lower()
    for key, val in _PROVIDER_MAP.items():
        if key in lower:
            return val
    return None


def _write_default_model(target_workspace: Path, provider_id: str, model: str):
    agent_json = target_workspace / "agent.json"
    data = {}
    if agent_json.exists():
        data = json.loads(agent_json.read_text(encoding="utf-8"))
    data.setdefault("active_model", {})
    data["active_model"]["provider_id"] = provider_id
    data["active_model"]["model"] = model
    agent_json.parent.mkdir(parents=True, exist_ok=True)
    agent_json.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _write_custom_provider(
    target_workspace: Path,
    provider_id: str,
    base_url: str,
    api_type: str,
):
    agent_json = target_workspace / "agent.json"
    data = {}
    if agent_json.exists():
        data = json.loads(agent_json.read_text(encoding="utf-8"))
    providers = data.setdefault("custom_providers", {})
    entry: dict[str, Any] = {"base_url": base_url}
    if api_type:
        entry["api_type"] = api_type
    providers[provider_id] = entry
    agent_json.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _write_api_keys(target_workspace: Path, keys: dict[str, str]):
    """Write migrated API keys into the agent's env file."""
    env_path = target_workspace / ".env"
    existing: dict[str, str] = {}
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            k, _, v = line.partition("=")
            if _:
                existing[k.strip()] = v.strip()
    existing.update(keys)
    env_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{k}={v}" for k, v in sorted(existing.items())]
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# pylint: disable=too-many-branches,too-many-return-statements
def plan_provider_migration(
    source: SourceInfo,
    target_workspace: Path,
    migrate_secrets: bool,
    overwrite: bool,
) -> list[MigrationItem]:
    del overwrite
    items: list[MigrationItem] = []

    # --- Default model ---
    defaults = source.config.get("agents", {}).get("defaults", {})
    model_raw = defaults.get("model")
    if not model_raw:
        model_raw = source.config.get("agent", {}).get("model")
    if model_raw:
        model_str = (
            model_raw
            if isinstance(model_raw, str)
            else model_raw.get("primary", "")
        )
        if model_str:
            provider, model = _parse_model_ref(model_str)
            api_type = (
                source.config.get("models", {})
                .get("providers", {})
                .get(provider, {})
                .get("api", "")
                if provider
                else ""
            )
            mapped = _map_provider(provider, api_type)
            if mapped:
                items.append(
                    MigrationItem(
                        category="provider",
                        source_path="config.agents.defaults.model",
                        target_path="agent.json#active_model",
                        status=ItemStatus.OK,
                        detail=f"{provider}/{model} -> {mapped}/{model}",
                        write_fn=partial(
                            _write_default_model,
                            target_workspace,
                            mapped,
                            model,
                        ),
                    ),
                )
            else:
                items.append(
                    MigrationItem(
                        category="provider",
                        source_path="config.agents.defaults.model",
                        target_path="agent.json#active_model",
                        status=ItemStatus.WARN,
                        detail=(
                            f"Unknown provider '{provider}',"
                            " skipping default model"
                        ),
                    ),
                )

    # --- Custom providers ---
    providers_cfg = source.config.get("models", {}).get("providers", {})
    for pid, pcfg in providers_cfg.items():
        if not isinstance(pcfg, dict):
            continue
        base_url = pcfg.get("baseUrl", pcfg.get("base_url", ""))
        api_type = pcfg.get("api", pcfg.get("apiType", ""))
        items.append(
            MigrationItem(
                category="provider",
                source_path=f"config.models.providers.{pid}",
                target_path=f"agent.json#custom_providers.{pid}",
                status=ItemStatus.OK,
                detail=f"Custom provider '{pid}' base_url={base_url}",
                write_fn=partial(
                    _write_custom_provider,
                    target_workspace,
                    pid,
                    base_url,
                    api_type,
                ),
            ),
        )

    # --- API keys ---
    if migrate_secrets:
        collected_keys: dict[str, str] = {}
        for env_var, _ in _ALLOWED_KEY_TARGETS.items():
            val = source.env.get(env_var)
            if val:
                collected_keys[env_var] = val

        for pid, pcfg in providers_cfg.items():
            if not isinstance(pcfg, dict):
                continue
            raw_key = pcfg.get("apiKey", pcfg.get("api_key"))
            api_key = _resolve_secret_input(raw_key, source.env)
            if not api_key:
                if isinstance(raw_key, dict) and raw_key.get("source") in {
                    "file",
                    "exec",
                }:
                    items.append(
                        MigrationItem(
                            category="secret",
                            source_path=f"models.providers.{pid}.apiKey",
                            target_path="(manual)",
                            status=ItemStatus.WARN,
                            detail=(
                                f"Provider '{pid}' uses a "
                                f"{raw_key['source']}-backed SecretRef; "
                                "add this key manually"
                            ),
                        ),
                    )
                continue
            base_url = pcfg.get("baseUrl", "")
            env_var = _infer_env_var(pid, base_url, pcfg.get("api", ""))
            if env_var and env_var not in collected_keys:
                collected_keys[env_var] = api_key

        if collected_keys:
            keys_snapshot = dict(collected_keys)
            items.append(
                MigrationItem(
                    category="secret",
                    source_path="env + config",
                    target_path=f"{target_workspace}/.env",
                    status=ItemStatus.OK,
                    detail=(
                        f"Migrate {len(keys_snapshot)} API key(s): "
                        + ", ".join(sorted(keys_snapshot.keys()))
                    ),
                    write_fn=partial(
                        _write_api_keys,
                        target_workspace,
                        keys_snapshot,
                    ),
                ),
            )

    return items


def _infer_env_var(  # pylint: disable=too-many-return-statements
    provider_name: str,
    base_url: str,
    api_type: str,
) -> str | None:
    """Infer the standard env var name for a provider API key."""
    lower_url = (base_url or "").lower()
    if "openrouter" in lower_url:
        return "OPENROUTER_API_KEY"
    if "openai.com" in lower_url:
        return "OPENAI_API_KEY"
    if "anthropic" in lower_url:
        return "ANTHROPIC_API_KEY"
    if "deepseek" in lower_url:
        return "DEEPSEEK_API_KEY"

    if api_type == "anthropic-messages":
        return "ANTHROPIC_API_KEY"

    name = provider_name.lower()
    env_map = {
        "openrouter": "OPENROUTER_API_KEY",
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "google": "GEMINI_API_KEY",
        "groq": "GROQ_API_KEY",
    }
    for key, var in env_map.items():
        if key in name:
            return var
    return None
