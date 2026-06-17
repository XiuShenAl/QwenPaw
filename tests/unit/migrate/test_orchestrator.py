# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from qwenpaw.migrate.models import (
    ItemStatus,
    MigrationItem,
    MigrationPlan,
    SourceInfo,
)
from qwenpaw.migrate.openclaw.orchestrator import (
    _build_report,
    _create_pre_migration_backup,
    run_migration,
)


def _make_source(root: Path, workspace: Path, **kwargs) -> SourceInfo:
    return SourceInfo(
        root=root,
        flavor="openclaw",
        config=kwargs.get("config", {}),
        env=kwargs.get("env", {}),
        workspace=workspace,
        agent_id="main",
    )


class TestBuildReport:
    def test_counts_statuses(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        source = _make_source(tmp_path, ws)
        plan = MigrationPlan(
            source=source,
            target_agent_id="default",
            target_workspace=ws,
            items=[
                MigrationItem("a", "s", "t", ItemStatus.OK, "ok"),
                MigrationItem("b", "s", "t", ItemStatus.OK, "ok"),
                MigrationItem("c", "s", "t", ItemStatus.SKIP, "skip"),
                MigrationItem("d", "s", "t", ItemStatus.CONFLICT, "conflict"),
                MigrationItem("e", "s", "t", ItemStatus.WARN, "warn"),
                MigrationItem("f", "s", "t", ItemStatus.ERROR, "error"),
            ],
        )
        report = _build_report(plan, applied=2, backup_path=None)
        assert report.applied == 2
        assert report.skipped == 1
        assert report.conflicts == 1
        assert report.warnings == 1
        assert report.errors == 1
        assert report.backup_path is None


class TestCreatePreMigrationBackup:
    def test_creates_zip(self, tmp_path, monkeypatch):
        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / "test.txt").write_text("hello")
        import qwenpaw.constant

        monkeypatch.setattr(qwenpaw.constant, "WORKING_DIR", tmp_path)
        result = _create_pre_migration_backup(ws, "20260617-120000")
        assert result is not None
        assert result.exists()
        assert result.suffix == ".zip"

    def test_nonexistent_workspace_returns_none(self, tmp_path, monkeypatch):
        ws = tmp_path / "nonexistent"
        import qwenpaw.constant

        monkeypatch.setattr(qwenpaw.constant, "WORKING_DIR", tmp_path)
        result = _create_pre_migration_backup(ws, "20260617-120000")
        assert result is None


class TestRunMigrationDryRun:
    def test_dry_run_does_not_write(self, tmp_path, monkeypatch):
        ws = tmp_path / "workspace"
        ws.mkdir()
        source = _make_source(tmp_path, ws)

        monkeypatch.setattr(
            "qwenpaw.migrate.openclaw.orchestrator.detect",
            lambda *a, **kw: source,
        )
        mock_config = MagicMock()
        mock_config.agents.profiles = {
            "default": MagicMock(workspace_dir=str(ws)),
        }
        monkeypatch.setattr(
            "qwenpaw.migrate.openclaw.orchestrator.load_config",
            lambda: mock_config,
        )

        converters = [
            "plan_persona_migration",
            "plan_memory_migration",
            "plan_provider_migration",
            "plan_mcp_migration",
            "plan_channel_migration",
            "plan_cron_migration",
            "plan_history_migration",
            "plan_skill_report",
        ]
        for name in converters:
            monkeypatch.setattr(
                f"qwenpaw.migrate.openclaw.orchestrator.{name}",
                lambda *_a, **_kw: [],
            )

        report = run_migration(
            source_path=tmp_path,
            target_agent_id="default",
            openclaw_agent_id="main",
            dry_run=True,
            include=None,
            exclude={"history"},
            migrate_secrets=False,
            overwrite=False,
            no_backup=False,
            yes=True,
        )
        assert report.applied == 0

    def test_include_filter(self, tmp_path, monkeypatch):
        ws = tmp_path / "workspace"
        ws.mkdir()
        source = _make_source(tmp_path, ws)

        monkeypatch.setattr(
            "qwenpaw.migrate.openclaw.orchestrator.detect",
            lambda *_a, **_kw: source,
        )
        mock_config = MagicMock()
        mock_config.agents.profiles = {
            "default": MagicMock(workspace_dir=str(ws)),
        }
        monkeypatch.setattr(
            "qwenpaw.migrate.openclaw.orchestrator.load_config",
            lambda: mock_config,
        )

        called = set()

        def _track(name):
            def _fn(*_a, **_kw):
                called.add(name)
                return []

            return _fn

        converters = [
            "plan_persona_migration",
            "plan_memory_migration",
            "plan_provider_migration",
            "plan_mcp_migration",
            "plan_channel_migration",
            "plan_cron_migration",
            "plan_history_migration",
        ]
        for name in converters:
            monkeypatch.setattr(
                f"qwenpaw.migrate.openclaw.orchestrator.{name}",
                _track(name),
            )
        monkeypatch.setattr(
            "qwenpaw.migrate.openclaw.orchestrator.plan_skill_report",
            lambda *_a, **_kw: [],
        )

        run_migration(
            source_path=tmp_path,
            target_agent_id="default",
            openclaw_agent_id="main",
            dry_run=True,
            include={"persona"},
            exclude=set(),
            migrate_secrets=False,
            overwrite=False,
            no_backup=False,
            yes=True,
        )
        assert "plan_persona_migration" in called
        assert "plan_mcp_migration" not in called
        assert "plan_cron_migration" not in called
