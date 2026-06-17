# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import date
from pathlib import Path

from qwenpaw.migrate.models import ItemStatus, SourceInfo
from qwenpaw.migrate.openclaw.persona import (
    _build_imported_block,
    _write_profile,
    plan_persona_migration,
)


def _make_source(workspace: Path) -> SourceInfo:
    return SourceInfo(
        root=workspace.parent,
        flavor="openclaw",
        config={},
        env={},
        workspace=workspace,
        agent_id="main",
    )


class TestPlanPersonaMigration:
    def test_soul_md_copy(self, tmp_path: Path):
        src_ws = tmp_path / "source" / "ws"
        src_ws.mkdir(parents=True)
        (src_ws / "SOUL.md").write_text("soul content")
        target_ws = tmp_path / "target" / "ws"
        target_ws.mkdir(parents=True)
        archive = tmp_path / "archive"

        items = plan_persona_migration(
            _make_source(src_ws),
            target_ws,
            archive,
            overwrite=False,
        )
        soul_items = [i for i in items if "SOUL.md" in i.source_path]
        assert len(soul_items) == 1
        assert soul_items[0].status == ItemStatus.OK

        soul_items[0].write_fn()
        assert (target_ws / "SOUL.md").read_text() == "soul content"

    def test_agents_md_copy(self, tmp_path: Path):
        src_ws = tmp_path / "source" / "ws"
        src_ws.mkdir(parents=True)
        (src_ws / "AGENTS.md").write_text("agents content")
        target_ws = tmp_path / "target" / "ws"
        target_ws.mkdir(parents=True)
        archive = tmp_path / "archive"

        items = plan_persona_migration(
            _make_source(src_ws),
            target_ws,
            archive,
            overwrite=False,
        )
        agents_items = [i for i in items if "AGENTS.md" in i.source_path]
        assert len(agents_items) == 1
        assert agents_items[0].status == ItemStatus.OK

        agents_items[0].write_fn()
        assert (target_ws / "AGENTS.md").read_text() == "agents content"

    def test_profile_merge_from_identity_and_user(self, tmp_path: Path):
        src_ws = tmp_path / "source" / "ws"
        src_ws.mkdir(parents=True)
        (src_ws / "IDENTITY.md").write_text("I am an assistant")
        (src_ws / "USER.md").write_text("User prefs")
        target_ws = tmp_path / "target" / "ws"
        target_ws.mkdir(parents=True)
        archive = tmp_path / "archive"

        items = plan_persona_migration(
            _make_source(src_ws),
            target_ws,
            archive,
            overwrite=False,
        )
        profile_items = [i for i in items if "PROFILE.md" in i.target_path]
        assert len(profile_items) == 1
        assert profile_items[0].status == ItemStatus.OK

        profile_items[0].write_fn()
        content = (target_ws / "PROFILE.md").read_text()
        assert "I am an assistant" in content
        assert "User prefs" in content

    def test_conflict_detection(self, tmp_path: Path):
        src_ws = tmp_path / "source" / "ws"
        src_ws.mkdir(parents=True)
        (src_ws / "SOUL.md").write_text("soul content")
        target_ws = tmp_path / "target" / "ws"
        target_ws.mkdir(parents=True)
        (target_ws / "SOUL.md").write_text("existing")
        archive = tmp_path / "archive"

        items = plan_persona_migration(
            _make_source(src_ws),
            target_ws,
            archive,
            overwrite=False,
        )
        soul_items = [i for i in items if "SOUL.md" in i.source_path]
        assert soul_items[0].status == ItemStatus.CONFLICT

    def test_overwrite_mode(self, tmp_path: Path):
        src_ws = tmp_path / "source" / "ws"
        src_ws.mkdir(parents=True)
        (src_ws / "SOUL.md").write_text("new soul")
        target_ws = tmp_path / "target" / "ws"
        target_ws.mkdir(parents=True)
        (target_ws / "SOUL.md").write_text("old soul")
        archive = tmp_path / "archive"

        items = plan_persona_migration(
            _make_source(src_ws),
            target_ws,
            archive,
            overwrite=True,
        )
        soul_items = [i for i in items if "SOUL.md" in i.source_path]
        assert soul_items[0].status == ItemStatus.OK

        soul_items[0].write_fn()
        assert (target_ws / "SOUL.md").read_text() == "new soul"

    def test_archive_tools_and_bootstrap(self, tmp_path: Path):
        src_ws = tmp_path / "source" / "ws"
        src_ws.mkdir(parents=True)
        (src_ws / "TOOLS.md").write_text("tools")
        (src_ws / "BOOTSTRAP.md").write_text("bootstrap")
        target_ws = tmp_path / "target" / "ws"
        target_ws.mkdir(parents=True)
        archive = tmp_path / "archive"

        items = plan_persona_migration(
            _make_source(src_ws),
            target_ws,
            archive,
            overwrite=False,
        )
        archived = [i for i in items if i.status == ItemStatus.ARCHIVED]
        assert len(archived) == 2
        names = {Path(i.source_path).name for i in archived}
        assert names == {"TOOLS.md", "BOOTSTRAP.md"}

        for item in archived:
            item.write_fn()
        assert (archive / "TOOLS.md").read_text() == "tools"
        assert (archive / "BOOTSTRAP.md").read_text() == "bootstrap"


class TestWriteProfile:
    def test_append_mode_with_existing(self, tmp_path: Path):
        profile = tmp_path / "PROFILE.md"
        profile.write_text("existing content")

        status = _write_profile(
            profile,
            "identity",
            "user prefs",
            overwrite=False,
        )
        assert status == ItemStatus.WARN

        content = profile.read_text()
        assert content.startswith("existing content")
        assert "Imported from OpenClaw" in content
        assert date.today().isoformat() in content
        assert "identity" in content
        assert "user prefs" in content

    def test_creates_new_file(self, tmp_path: Path):
        profile = tmp_path / "sub" / "PROFILE.md"
        status = _write_profile(profile, "id text", None, overwrite=False)
        assert status == ItemStatus.OK
        assert profile.read_text() == "id text"

    def test_overwrite_existing(self, tmp_path: Path):
        profile = tmp_path / "PROFILE.md"
        profile.write_text("old")
        status = _write_profile(profile, "new id", "new user", overwrite=True)
        assert status == ItemStatus.OK
        assert "old" not in profile.read_text()
        assert "new id" in profile.read_text()


class TestBuildImportedBlock:
    def test_both_present(self):
        result = _build_imported_block("identity", "user")
        assert result == "identity\n\nuser"

    def test_identity_only(self):
        assert _build_imported_block("identity", None) == "identity"

    def test_user_only(self):
        assert _build_imported_block(None, "user") == "user"

    def test_neither(self):
        assert _build_imported_block(None, None) == ""
