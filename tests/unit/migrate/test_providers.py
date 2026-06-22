# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

from qwenpaw.migrate.models import ItemStatus, SourceInfo
from qwenpaw.migrate.openclaw.providers import (
    _parse_model_ref,
    plan_provider_migration,
)


def _make_source(
    workspace: Path,
    config: dict | None = None,
    env: dict | None = None,
) -> SourceInfo:
    return SourceInfo(
        root=workspace.parent,
        flavor="openclaw",
        config=config or {},
        env=env or {},
        workspace=workspace,
        agent_id="main",
    )


class TestParseModelRef:
    def test_provider_slash_model(self):
        assert _parse_model_ref("anthropic/claude-sonnet-4-6") == (
            "anthropic",
            "claude-sonnet-4-6",
        )

    def test_nested_model_path(self):
        assert _parse_model_ref("openrouter/moonshotai/kimi-k2") == (
            "openrouter",
            "moonshotai/kimi-k2",
        )

    def test_bare_model(self):
        assert _parse_model_ref("claude-sonnet") == ("", "claude-sonnet")


class TestPlanProviderMigration:
    def test_default_model_migration(self, tmp_path: Path):
        src_ws = tmp_path / "source" / "ws"
        src_ws.mkdir(parents=True)
        target_ws = tmp_path / "target" / "ws"
        target_ws.mkdir(parents=True)

        source = _make_source(
            src_ws,
            config={
                "agents": {
                    "defaults": {"model": "anthropic/claude-sonnet-4-6"},
                },
            },
        )

        items = plan_provider_migration(
            source,
            target_ws,
            migrate_secrets=False,
            overwrite=False,
        )
        model_items = [i for i in items if i.category == "provider"]
        assert len(model_items) == 1
        assert model_items[0].status == ItemStatus.OK
        assert "anthropic" in model_items[0].detail

        model_items[0].write_fn()
        agent_json = json.loads((target_ws / "agent.json").read_text())
        assert agent_json["active_model"]["provider_id"] == "anthropic"
        assert agent_json["active_model"]["model"] == "claude-sonnet-4-6"

    def test_unknown_provider_warning(self, tmp_path: Path):
        src_ws = tmp_path / "source" / "ws"
        src_ws.mkdir(parents=True)
        target_ws = tmp_path / "target" / "ws"
        target_ws.mkdir(parents=True)

        source = _make_source(
            src_ws,
            config={
                "agents": {"defaults": {"model": "minimax/some-model"}},
            },
        )

        items = plan_provider_migration(
            source,
            target_ws,
            migrate_secrets=False,
            overwrite=False,
        )
        model_items = [i for i in items if i.category == "provider"]
        assert len(model_items) == 1
        assert model_items[0].status == ItemStatus.WARN
        assert model_items[0].write_fn is None

    def test_custom_providers(self, tmp_path: Path):
        src_ws = tmp_path / "source" / "ws"
        src_ws.mkdir(parents=True)
        target_ws = tmp_path / "target" / "ws"
        target_ws.mkdir(parents=True)

        source = _make_source(
            src_ws,
            config={
                "models": {
                    "providers": {
                        "my-llm": {
                            "base_url": "https://my-llm.example.com/v1",
                            "api_key": "sk-xxx",
                        },
                    },
                },
            },
        )

        items = plan_provider_migration(
            source,
            target_ws,
            migrate_secrets=False,
            overwrite=False,
        )
        custom_items = [
            i for i in items if "custom_providers" in i.target_path
        ]
        assert len(custom_items) == 1
        assert custom_items[0].status == ItemStatus.OK

        custom_items[0].write_fn()
        agent_json = json.loads((target_ws / "agent.json").read_text())
        assert (
            agent_json["custom_providers"]["my-llm"]["base_url"]
            == "https://my-llm.example.com/v1"
        )

    def test_api_key_migration_with_secrets(self, tmp_path: Path):
        src_ws = tmp_path / "source" / "ws"
        src_ws.mkdir(parents=True)
        target_ws = tmp_path / "target" / "ws"
        target_ws.mkdir(parents=True)

        source = _make_source(
            src_ws,
            env={
                "ANTHROPIC_API_KEY": "sk-ant-xxx",
                "OPENAI_API_KEY": "sk-oai-xxx",
            },
        )

        items = plan_provider_migration(
            source,
            target_ws,
            migrate_secrets=True,
            overwrite=False,
        )
        secret_items = [i for i in items if i.category == "secret"]
        assert len(secret_items) == 1
        assert secret_items[0].status == ItemStatus.OK
        assert "ANTHROPIC_API_KEY" in secret_items[0].detail
        assert "OPENAI_API_KEY" in secret_items[0].detail

        secret_items[0].write_fn()
        env_content = (target_ws / ".env").read_text()
        assert "ANTHROPIC_API_KEY=sk-ant-xxx" in env_content
        assert "OPENAI_API_KEY=sk-oai-xxx" in env_content

    def test_api_key_not_included_without_secrets(self, tmp_path: Path):
        src_ws = tmp_path / "source" / "ws"
        src_ws.mkdir(parents=True)
        target_ws = tmp_path / "target" / "ws"
        target_ws.mkdir(parents=True)

        source = _make_source(
            src_ws,
            env={
                "ANTHROPIC_API_KEY": "sk-ant-xxx",
            },
        )

        items = plan_provider_migration(
            source,
            target_ws,
            migrate_secrets=False,
            overwrite=False,
        )
        secret_items = [i for i in items if i.category == "secret"]
        assert not secret_items

    def test_agent_singular_model_shorthand(self, tmp_path: Path):
        """OpenClaw minimal config uses `agent.model` (singular)."""
        src_ws = tmp_path / "source" / "ws"
        src_ws.mkdir(parents=True)
        target_ws = tmp_path / "target" / "ws"
        target_ws.mkdir(parents=True)

        source = _make_source(
            src_ws,
            config={"agent": {"model": "openai/gpt-4o"}},
        )
        items = plan_provider_migration(
            source,
            target_ws,
            migrate_secrets=False,
            overwrite=False,
        )
        model_items = [i for i in items if i.category == "provider"]
        assert len(model_items) == 1
        assert model_items[0].status == ItemStatus.OK
        assert "openai" in model_items[0].detail

    def test_secret_input_object_for_api_key(self, tmp_path: Path):
        """OpenClaw apiKey can be a SecretInput object."""
        src_ws = tmp_path / "source" / "ws"
        src_ws.mkdir(parents=True)
        target_ws = tmp_path / "target" / "ws"
        target_ws.mkdir(parents=True)

        source = _make_source(
            src_ws,
            config={
                "models": {
                    "providers": {
                        "openai": {
                            "baseUrl": "https://api.openai.com/v1",
                            "apiKey": {"source": "env", "id": "MY_OPENAI_KEY"},
                        },
                    },
                },
            },
            env={"MY_OPENAI_KEY": "resolved-secret"},
        )

        items = plan_provider_migration(
            source,
            target_ws,
            migrate_secrets=True,
            overwrite=False,
        )
        secret = [i for i in items if i.category == "secret"]
        assert len(secret) == 1
        secret[0].write_fn()
        env_content = (target_ws / ".env").read_text()
        assert "resolved-secret" in env_content
