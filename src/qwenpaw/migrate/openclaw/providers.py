# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
from functools import partial
from pathlib import Path

from ..models import ItemStatus, MigrationItem, SourceInfo

logger = logging.getLogger(__name__)

_PROVIDER_MAP = {
    "anthropic": "anthropic",
    "openai": "openai",
    "google": "google",
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
}


def _resolve_secret_input(value, env: dict[str, str]) -> str | None:
    """Resolve OpenClaw SecretInput to a plain string.

    SecretInput can be a plain string or {source: "env", id: "VAR_NAME"}.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and value.get("source") == "env":
        return env.get(value.get("id", ""))
    return None


def _parse_model_ref(model_str: str) -> tuple[str, str]:
    parts = model_str.split("/", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return "", parts[0]


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
    api_key: str | None,
):
    """Record custom provider config. API key is stored in plaintext here;
    the orchestrator should ideally use ProviderManager for encryption."""
    agent_json = target_workspace / "agent.json"
    data = {}
    if agent_json.exists():
        data = json.loads(agent_json.read_text(encoding="utf-8"))
    providers = data.setdefault("custom_providers", {})
    providers[provider_id] = {"base_url": base_url}
    if api_key:
        providers[provider_id]["api_key"] = api_key
    agent_json.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def plan_provider_migration(
    source: SourceInfo,
    target_workspace: Path,
    migrate_secrets: bool,
    overwrite: bool,
) -> list[MigrationItem]:
    del overwrite  # reserved for future conflict handling
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
            mapped = _PROVIDER_MAP.get(provider)
            if mapped:
                items.append(
                    MigrationItem(
                        category="provider",
                        source_path="config.agents.defaults.model",
                        target_path="agent.json#active_model",
                        status=ItemStatus.OK,
                        detail=(f"{provider}/{model}" f" -> {mapped}/{model}"),
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
                        write_fn=None,
                    ),
                )

    # --- Custom providers ---
    providers_cfg = source.config.get("models", {}).get("providers", {})
    for pid, pcfg in providers_cfg.items():
        if not isinstance(pcfg, dict):
            continue
        base_url = pcfg.get("baseUrl", pcfg.get("base_url", ""))
        raw_key = pcfg.get("apiKey", pcfg.get("api_key"))
        api_key = _resolve_secret_input(raw_key, source.env)
        items.append(
            MigrationItem(
                category="provider",
                source_path=f"config.models.providers.{pid}",
                target_path=f"agent.json#custom_providers.{pid}",
                status=ItemStatus.OK,
                detail=(f"Custom provider '{pid}'" f" base_url={base_url}"),
                write_fn=partial(
                    _write_custom_provider,
                    target_workspace,
                    pid,
                    base_url,
                    api_key,
                ),
            ),
        )

    # --- API keys ---
    if migrate_secrets:
        for env_var, target_provider in _ALLOWED_KEY_TARGETS.items():
            if env_var in source.env:
                items.append(
                    MigrationItem(
                        category="secret",
                        source_path=f"env.{env_var}",
                        target_path=f"provider_secret:{target_provider}",
                        status=ItemStatus.OK,
                        detail=(f"API key {env_var}" f" -> {target_provider}"),
                        write_fn=None,
                    ),
                )

    return items
