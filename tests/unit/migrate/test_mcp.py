# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

from qwenpaw.migrate.models import ItemStatus, SourceInfo
from qwenpaw.migrate.openclaw.mcp import plan_mcp_migration


def _make_source(root: Path, workspace: Path, config=None, env=None):
    return SourceInfo(
        root=root,
        flavor="openclaw",
        config=config or {},
        env=env or {},
        workspace=workspace,
        agent_id="main",
    )


class TestPlanMcpMigration:
    def test_stdio_transport_inference(self, tmp_path: Path):
        source_ws = tmp_path / "source"
        source_ws.mkdir()
        target_ws = tmp_path / "target"
        target_ws.mkdir()

        config = {
            "mcp": {
                "servers": {
                    "filesystem": {
                        "command": "npx",
                        "args": [
                            "-y",
                            "@modelcontextprotocol/server-filesystem",
                        ],
                    },
                },
            },
        }
        source = _make_source(source_ws, source_ws, config=config)
        items = plan_mcp_migration(source, target_ws, overwrite=False)

        assert len(items) == 1
        assert items[0].status == ItemStatus.OK
        assert "stdio" in items[0].detail

    def test_streamable_http_transport_inference(self, tmp_path: Path):
        source_ws = tmp_path / "source"
        source_ws.mkdir()
        target_ws = tmp_path / "target"
        target_ws.mkdir()

        config = {
            "mcp": {
                "servers": {
                    "remote": {"url": "https://example.com/mcp"},
                },
            },
        }
        source = _make_source(source_ws, source_ws, config=config)
        items = plan_mcp_migration(source, target_ws, overwrite=False)

        assert len(items) == 1
        assert items[0].status == ItemStatus.OK
        assert "streamable_http" in items[0].detail

    def test_conflict_detection(self, tmp_path: Path):
        source_ws = tmp_path / "source"
        source_ws.mkdir()
        target_ws = tmp_path / "target"
        target_ws.mkdir()

        agent_json = target_ws / "agent.json"
        agent_json.write_text(
            json.dumps(
                {
                    "mcp": {"clients": {"filesystem": {"transport": "stdio"}}},
                },
            ),
        )

        config = {
            "mcp": {
                "servers": {
                    "filesystem": {
                        "command": "npx",
                        "args": ["-y", "fs-server"],
                    },
                },
            },
        }
        source = _make_source(source_ws, source_ws, config=config)
        items = plan_mcp_migration(source, target_ws, overwrite=False)

        assert len(items) == 1
        assert items[0].status == ItemStatus.CONFLICT

    def test_write_fn_updates_agent_json(self, tmp_path: Path):
        source_ws = tmp_path / "source"
        source_ws.mkdir()
        target_ws = tmp_path / "target"
        target_ws.mkdir()

        config = {
            "mcp": {
                "servers": {
                    "filesystem": {
                        "command": "npx",
                        "args": ["-y", "fs-server"],
                    },
                },
            },
        }
        source = _make_source(source_ws, source_ws, config=config)
        items = plan_mcp_migration(source, target_ws, overwrite=False)

        assert items[0].write_fn is not None
        items[0].write_fn()

        agent_json = target_ws / "agent.json"
        data = json.loads(agent_json.read_text())
        assert "filesystem" in data["mcp"]["clients"]
        assert data["mcp"]["clients"]["filesystem"]["transport"] == "stdio"
        assert data["mcp"]["clients"]["filesystem"]["command"] == "npx"

    def test_empty_mcp_config_returns_empty(self, tmp_path: Path):
        source_ws = tmp_path / "source"
        source_ws.mkdir()
        target_ws = tmp_path / "target"
        target_ws.mkdir()

        source = _make_source(source_ws, source_ws, config={})
        items = plan_mcp_migration(source, target_ws, overwrite=False)
        assert not items

    def test_working_directory_alias(self, tmp_path: Path):
        source_ws = tmp_path / "source"
        source_ws.mkdir()
        target_ws = tmp_path / "target"
        target_ws.mkdir()

        config = {
            "mcp": {
                "servers": {
                    "myserver": {
                        "command": "node",
                        "args": ["server.js"],
                        "workingDirectory": "/opt/mcp",
                    },
                },
            },
        }
        source = _make_source(source_ws, source_ws, config=config)
        items = plan_mcp_migration(source, target_ws, overwrite=False)
        assert items[0].status == ItemStatus.OK
        items[0].write_fn()
        data = json.loads((target_ws / "agent.json").read_text())
        assert data["mcp"]["clients"]["myserver"]["cwd"] == "/opt/mcp"

    def test_disabled_server_preserved(self, tmp_path: Path):
        source_ws = tmp_path / "source"
        source_ws.mkdir()
        target_ws = tmp_path / "target"
        target_ws.mkdir()

        config = {
            "mcp": {
                "servers": {
                    "disabled-srv": {
                        "command": "node",
                        "enabled": False,
                    },
                },
            },
        }
        source = _make_source(source_ws, source_ws, config=config)
        items = plan_mcp_migration(source, target_ws, overwrite=False)
        assert items[0].status == ItemStatus.OK
        items[0].write_fn()
        data = json.loads((target_ws / "agent.json").read_text())
        assert data["mcp"]["clients"]["disabled-srv"]["enabled"] is False

    def test_headers_transferred(self, tmp_path: Path):
        source_ws = tmp_path / "source"
        source_ws.mkdir()
        target_ws = tmp_path / "target"
        target_ws.mkdir()

        config = {
            "mcp": {
                "servers": {
                    "auth-server": {
                        "url": "https://example.com/mcp",
                        "headers": {"Authorization": "Bearer tok"},
                    },
                },
            },
        }
        source = _make_source(source_ws, source_ws, config=config)
        items = plan_mcp_migration(source, target_ws, overwrite=False)
        items[0].write_fn()
        data = json.loads((target_ws / "agent.json").read_text())
        assert (
            data["mcp"]["clients"]["auth-server"]["headers"]["Authorization"]
            == "Bearer tok"
        )

    def test_tool_filter_migration(self, tmp_path: Path):
        """OpenClaw uses ``toolFilter`` for MCP tool filtering."""
        source_ws = tmp_path / "source"
        source_ws.mkdir()
        target_ws = tmp_path / "target"
        target_ws.mkdir()

        config = {
            "mcp": {
                "servers": {
                    "filtered": {
                        "command": "node",
                        "args": ["server.js"],
                        "toolFilter": {
                            "include": ["search_*"],
                            "exclude": ["admin_*"],
                        },
                    },
                },
            },
        }
        source = _make_source(source_ws, source_ws, config=config)
        items = plan_mcp_migration(source, target_ws, overwrite=False)
        assert len(items) == 1
        items[0].write_fn()
        data = json.loads((target_ws / "agent.json").read_text())
        client = data["mcp"]["clients"]["filtered"]
        assert client["tools"]["include"] == ["search_*"]
        assert client["tools"]["exclude"] == ["admin_*"]
