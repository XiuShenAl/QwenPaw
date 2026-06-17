# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from qwenpaw.migrate.models import ItemStatus, SourceInfo
from qwenpaw.migrate.openclaw.memory import plan_memory_migration


def _make_source(workspace: Path) -> SourceInfo:
    return SourceInfo(
        root=workspace.parent,
        flavor="openclaw",
        config={},
        env={},
        workspace=workspace,
        agent_id="main",
    )


class TestPlanMemoryMigration:
    def test_memory_md_copy(self, tmp_path: Path):
        src_ws = tmp_path / "source" / "ws"
        src_ws.mkdir(parents=True)
        (src_ws / "MEMORY.md").write_text("remember this")
        target_ws = tmp_path / "target" / "ws"
        target_ws.mkdir(parents=True)
        archive = tmp_path / "archive"

        items = plan_memory_migration(
            _make_source(src_ws),
            target_ws,
            archive,
            overwrite=False,
        )
        mem_items = [i for i in items if "MEMORY.md" in i.source_path]
        assert len(mem_items) == 1
        assert mem_items[0].status == ItemStatus.OK

        mem_items[0].write_fn()
        assert (target_ws / "MEMORY.md").read_text() == "remember this"

    def test_memory_dir_bulk_copy(self, tmp_path: Path):
        src_ws = tmp_path / "source" / "ws"
        mem_dir = src_ws / "memory"
        mem_dir.mkdir(parents=True)
        (mem_dir / "topic_a.md").write_text("topic a")
        (mem_dir / "topic_b.md").write_text("topic b")
        target_ws = tmp_path / "target" / "ws"
        target_ws.mkdir(parents=True)
        archive = tmp_path / "archive"

        items = plan_memory_migration(
            _make_source(src_ws),
            target_ws,
            archive,
            overwrite=False,
        )
        dir_items = [
            i
            for i in items
            if "memory/" in i.source_path or "memory\\" in i.source_path
        ]
        assert len(dir_items) == 2
        assert all(i.status == ItemStatus.OK for i in dir_items)

        for item in dir_items:
            item.write_fn()
        assert (target_ws / "memory" / "topic_a.md").read_text() == "topic a"
        assert (target_ws / "memory" / "topic_b.md").read_text() == "topic b"

    def test_dreams_archived(self, tmp_path: Path):
        src_ws = tmp_path / "source" / "ws"
        src_ws.mkdir(parents=True)
        (src_ws / "DREAMS.md").write_text("dreams")
        target_ws = tmp_path / "target" / "ws"
        target_ws.mkdir(parents=True)
        archive = tmp_path / "archive"

        items = plan_memory_migration(
            _make_source(src_ws),
            target_ws,
            archive,
            overwrite=False,
        )
        archived = [i for i in items if i.status == ItemStatus.ARCHIVED]
        assert len(archived) == 1
        assert "DREAMS.md" in archived[0].source_path

        archived[0].write_fn()
        assert (archive / "DREAMS.md").read_text() == "dreams"

    def test_conflict_existing_memory_md(self, tmp_path: Path):
        src_ws = tmp_path / "source" / "ws"
        src_ws.mkdir(parents=True)
        (src_ws / "MEMORY.md").write_text("new memory")
        target_ws = tmp_path / "target" / "ws"
        target_ws.mkdir(parents=True)
        (target_ws / "MEMORY.md").write_text("existing")
        archive = tmp_path / "archive"

        items = plan_memory_migration(
            _make_source(src_ws),
            target_ws,
            archive,
            overwrite=False,
        )
        mem_items = [i for i in items if "MEMORY.md" in i.source_path]
        assert mem_items[0].status == ItemStatus.CONFLICT

    def test_empty_source(self, tmp_path: Path):
        src_ws = tmp_path / "source" / "ws"
        src_ws.mkdir(parents=True)
        target_ws = tmp_path / "target" / "ws"
        target_ws.mkdir(parents=True)
        archive = tmp_path / "archive"

        items = plan_memory_migration(
            _make_source(src_ws),
            target_ws,
            archive,
            overwrite=False,
        )
        assert not items
