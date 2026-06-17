# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from qwenpaw.migrate.models import ItemStatus, SourceInfo
from qwenpaw.migrate.openclaw.channels import (
    _extract_discord,
    _extract_telegram,
    _map_allow_from,
    _resolve_token,
    plan_channel_migration,
)


def _make_source(root: Path, workspace: Path, config=None, env=None):
    return SourceInfo(
        root=root,
        flavor="openclaw",
        config=config or {},
        env=env or {},
        workspace=workspace,
        agent_id="main",
    )


class TestResolveToken:
    def test_plain_string(self):
        assert _resolve_token("my-token", {}) == "my-token"

    def test_env_template(self):
        env = {"TELEGRAM_BOT_TOKEN": "abc"}
        assert _resolve_token("${TELEGRAM_BOT_TOKEN}", env) == "abc"

    def test_secret_ref_env(self):
        env = {"TELEGRAM_BOT_TOKEN": "abc"}
        ref = {"source": "env", "id": "TELEGRAM_BOT_TOKEN"}
        assert _resolve_token(ref, env) == "abc"

    def test_secret_ref_unsupported_source(self):
        ref = {"source": "file", "id": "key.txt"}
        assert _resolve_token(ref, {}) is None


class TestMapAllowFrom:
    def test_filters_wildcard(self):
        assert _map_allow_from(["123", "456", "*"]) == ["123", "456"]

    def test_empty_input(self):
        assert _map_allow_from(None) == []


class TestExtractTelegram:
    def test_full_config(self):
        oc_cfg = {
            "botToken": "tg-token-123",
            "allowFrom": ["111", "222"],
            "dmPolicy": "allowlist",
        }
        result = _extract_telegram(oc_cfg, {})
        assert result["enabled"] is True
        assert result["bot_token"] == "tg-token-123"
        assert result["allow_from"] == ["111", "222"]
        assert result["access_control_dm"] is True


class TestExtractDiscord:
    def test_token_and_dm_allow_from(self):
        oc_cfg = {
            "token": "${DISCORD_TOKEN}",
            "dm": {"allowFrom": ["u1", "u2"]},
        }
        env = {"DISCORD_TOKEN": "disc-secret"}
        result = _extract_discord(oc_cfg, env)
        assert result["bot_token"] == "disc-secret"
        assert result["allow_from"] == ["u1", "u2"]


class TestPlanChannelMigration:
    def test_archived_platform(self, tmp_path: Path):
        source_ws = tmp_path / "source"
        source_ws.mkdir()
        target_ws = tmp_path / "target"
        target_ws.mkdir()

        config = {"channels": {"slack": {"token": "xoxb-123"}}}
        source = _make_source(source_ws, source_ws, config=config)
        items = plan_channel_migration(source, target_ws, overwrite=False)

        assert len(items) == 1
        assert items[0].status == ItemStatus.ARCHIVED

    def test_unknown_platform(self, tmp_path: Path):
        source_ws = tmp_path / "source"
        source_ws.mkdir()
        target_ws = tmp_path / "target"
        target_ws.mkdir()

        config = {"channels": {"carrier_pigeon": {"speed": "slow"}}}
        source = _make_source(source_ws, source_ws, config=config)
        items = plan_channel_migration(source, target_ws, overwrite=False)

        assert len(items) == 1
        assert items[0].status == ItemStatus.WARN

    def test_skips_non_channel_keys(self, tmp_path: Path):
        source_ws = tmp_path / "source"
        source_ws.mkdir()
        target_ws = tmp_path / "target"
        target_ws.mkdir()

        config = {
            "channels": {
                "defaults": {"groupPolicy": "open"},
                "modelByChannel": {"openai": {"telegram": "gpt-4o"}},
                "telegram": {"botToken": "tok"},
            },
        }
        source = _make_source(source_ws, source_ws, config=config)
        items = plan_channel_migration(source, target_ws, overwrite=False)

        categories = [i.source_path for i in items]
        assert "channels.defaults" not in categories
        assert "channels.modelByChannel" not in categories
        assert any("telegram" in c for c in categories)

    def test_pairing_dm_policy_sets_access_control(self, tmp_path: Path):
        source_ws = tmp_path / "source"
        source_ws.mkdir()
        target_ws = tmp_path / "target"
        target_ws.mkdir()

        config = {
            "channels": {
                "telegram": {"botToken": "tok", "dmPolicy": "pairing"},
            },
        }
        source = _make_source(source_ws, source_ws, config=config)
        items = plan_channel_migration(source, target_ws, overwrite=False)
        assert items[0].status == ItemStatus.OK
        items[0].write_fn()
        import json

        agent = json.loads(
            (target_ws / "agent.json").read_text(encoding="utf-8"),
        )
        assert agent["channels"]["telegram"]["access_control_dm"] is True
