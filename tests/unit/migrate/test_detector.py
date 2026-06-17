# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from qwenpaw.migrate.openclaw.detector import (
    _find_config,
    _find_root,
    _parse_dotenv,
    _resolve_cron_path,
    _resolve_workspace,
    detect,
)


class TestFindRoot:
    def test_explicit_source_path(self, tmp_path):
        root = _find_root(tmp_path)
        assert root == tmp_path.resolve()

    def test_explicit_source_nonexistent_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            _find_root(tmp_path / "nonexistent")

    def test_auto_detect_from_candidates(self, tmp_path, monkeypatch):
        fake_home = tmp_path / "home"
        fake_openclaw = fake_home / ".openclaw"
        fake_openclaw.mkdir(parents=True)

        monkeypatch.setattr(
            "qwenpaw.migrate.openclaw.detector._CANDIDATE_ROOTS",
            [str(fake_openclaw)],
        )
        result = _find_root(None)
        assert result == fake_openclaw.resolve()

    def test_no_candidates_found_raises(self, monkeypatch):
        monkeypatch.setattr(
            "qwenpaw.migrate.openclaw.detector._CANDIDATE_ROOTS",
            ["/nonexistent_abc123"],
        )
        with pytest.raises(FileNotFoundError):
            _find_root(None)


class TestFindConfig:
    def test_finds_openclaw_json(self, tmp_path):
        config = tmp_path / "openclaw.json"
        config.write_text("{}")
        path, flavor = _find_config(tmp_path)
        assert path == config
        assert flavor == "openclaw"

    def test_finds_clawdbot_json(self, tmp_path):
        config = tmp_path / "clawdbot.json"
        config.write_text("{}")
        path, flavor = _find_config(tmp_path)
        assert path == config
        assert flavor == "clawdbot"

    def test_no_config_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            _find_config(tmp_path)


class TestParseDotenv:
    def test_simple_key_value(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("KEY=value\n")
        assert _parse_dotenv(env_file) == {"KEY": "value"}

    def test_quoted_values_stripped(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("SINGLE='hello'\nDOUBLE=\"world\"\n")
        result = _parse_dotenv(env_file)
        assert result == {"SINGLE": "hello", "DOUBLE": "world"}

    def test_comments_and_blank_lines_skipped(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("# comment\n\nKEY=val\n  # indented comment\n")
        assert _parse_dotenv(env_file) == {"KEY": "val"}

    def test_missing_file_returns_empty(self, tmp_path):
        assert not _parse_dotenv(tmp_path / ".env")

    def test_line_without_equals_skipped(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("NOEQUALS\nGOOD=yes\n")
        assert _parse_dotenv(env_file) == {"GOOD": "yes"}


class TestResolveWorkspace:
    def test_config_workspace_used_if_exists(self, tmp_path):
        ws = tmp_path / "custom_ws"
        ws.mkdir()
        config = {"agents": {"defaults": {"workspace": str(ws)}}}
        result = _resolve_workspace(tmp_path, config, "main")
        assert result == ws.resolve()

    def test_fallback_to_per_agent_workspace(self, tmp_path):
        ws = tmp_path / "agents" / "myagent" / "workspace"
        ws.mkdir(parents=True)
        result = _resolve_workspace(tmp_path, {}, "myagent")
        assert result == ws

    def test_fallback_to_default_workspace(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        result = _resolve_workspace(tmp_path, {}, "other")
        assert result == ws

    def test_fallback_to_workspace(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        result = _resolve_workspace(tmp_path, {}, "main")
        assert result == ws

    def test_returns_last_candidate_if_none_exist(self, tmp_path):
        result = _resolve_workspace(tmp_path, {}, "main")
        assert result == tmp_path / "workspace"


class TestDetect:
    def test_full_detection(self, tmp_path):
        config_content = (
            '{"agents": {"defaults":'
            ' {"model": "anthropic/claude-sonnet-4-6"}}}'
        )
        (tmp_path / "openclaw.json").write_text(config_content)

        env_content = "OPENAI_API_KEY=test-key\n"
        (tmp_path / ".env").write_text(env_content)

        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / "SOUL.md").write_text("# Soul")

        info = detect(source=tmp_path)

        assert info.root == tmp_path.resolve()
        assert info.flavor == "openclaw"
        assert (
            info.config["agents"]["defaults"]["model"]
            == "anthropic/claude-sonnet-4-6"
        )
        assert info.env == {"OPENAI_API_KEY": "test-key"}
        assert info.workspace == ws
        assert info.agent_id == "main"
        assert info.sessions_dir is None
        assert info.cron_path is None

    def test_detect_with_sessions_and_cron(self, tmp_path):
        (tmp_path / "openclaw.json").write_text('{"agents": {}}')
        (tmp_path / "workspace").mkdir()

        sessions = tmp_path / "agents" / "main" / "sessions"
        sessions.mkdir(parents=True)

        cron_dir = tmp_path / "cron"
        cron_dir.mkdir()
        (cron_dir / "store.json").write_text("[]")

        info = detect(source=tmp_path)
        assert info.sessions_dir == sessions
        assert info.cron_path == cron_dir / "store.json"


class TestResolveCronPath:
    def test_custom_store_from_config(self, tmp_path):
        store = tmp_path / "custom" / "cron.json"
        store.parent.mkdir(parents=True)
        store.write_text("[]")
        result = _resolve_cron_path(tmp_path, {"cron": {"store": str(store)}})
        assert result == store.resolve()

    def test_default_store_json(self, tmp_path):
        store = tmp_path / "cron" / "store.json"
        store.parent.mkdir(parents=True)
        store.write_text("[]")
        result = _resolve_cron_path(tmp_path, {})
        assert result == store

    def test_fallback_cron_json(self, tmp_path):
        store = tmp_path / "cron" / "cron.json"
        store.parent.mkdir(parents=True)
        store.write_text("[]")
        result = _resolve_cron_path(tmp_path, {})
        assert result == store

    def test_returns_none_if_missing(self, tmp_path):
        result = _resolve_cron_path(tmp_path, {})
        assert result is None
