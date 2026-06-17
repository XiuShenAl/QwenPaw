# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from ..models import ItemStatus, MigrationItem, SourceInfo

logger = logging.getLogger(__name__)


def _make_copy_fn(src: Path, dst: Path):
    def _do():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    return _do


def plan_memory_migration(
    source: SourceInfo,
    target_workspace: Path,
    archive_dir: Path,
    overwrite: bool,
) -> list[MigrationItem]:
    items: list[MigrationItem] = []
    ws = source.workspace

    memory_src = ws / "MEMORY.md"
    memory_dst = target_workspace / "MEMORY.md"
    if memory_src.exists():
        if memory_dst.exists() and not overwrite:
            items.append(
                MigrationItem(
                    category="memory",
                    source_path=str(memory_src),
                    target_path=str(memory_dst),
                    status=ItemStatus.CONFLICT,
                    detail="MEMORY.md already exists at target",
                ),
            )
        else:
            items.append(
                MigrationItem(
                    category="memory",
                    source_path=str(memory_src),
                    target_path=str(memory_dst),
                    status=ItemStatus.OK,
                    detail="copy MEMORY.md",
                    write_fn=_make_copy_fn(memory_src, memory_dst),
                ),
            )

    memory_dir = ws / "memory"
    if memory_dir.is_dir():
        for md_file in sorted(memory_dir.glob("*.md")):
            dst = target_workspace / "memory" / md_file.name
            if dst.exists() and not overwrite:
                items.append(
                    MigrationItem(
                        category="memory",
                        source_path=str(md_file),
                        target_path=str(dst),
                        status=ItemStatus.CONFLICT,
                        detail=f"{md_file.name} already exists at target",
                    ),
                )
            else:
                items.append(
                    MigrationItem(
                        category="memory",
                        source_path=str(md_file),
                        target_path=str(dst),
                        status=ItemStatus.OK,
                        detail=f"copy memory/{md_file.name}",
                        write_fn=_make_copy_fn(md_file, dst),
                    ),
                )

    dreams_src = ws / "DREAMS.md"
    if dreams_src.exists():
        dreams_dst = archive_dir / "DREAMS.md"
        items.append(
            MigrationItem(
                category="memory",
                source_path=str(dreams_src),
                target_path=str(dreams_dst),
                status=ItemStatus.ARCHIVED,
                detail=("DREAMS.md archived " "(QwenPaw ReMe manages dreams)"),
                write_fn=_make_copy_fn(dreams_src, dreams_dst),
            ),
        )

    return items
