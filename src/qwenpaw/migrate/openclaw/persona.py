# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import shutil
from datetime import date
from pathlib import Path

from ..models import ItemStatus, MigrationItem, SourceInfo

logger = logging.getLogger(__name__)


def _make_copy_fn(src: Path, dst: Path):
    def _do():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    return _do


def _build_imported_block(identity_md: str | None, user_md: str | None) -> str:
    parts = [p for p in (identity_md, user_md) if p]
    return "\n\n".join(parts)


def _write_profile(
    target: Path,
    identity_md: str | None,
    user_md: str | None,
    overwrite: bool,
) -> ItemStatus:
    imported_block = _build_imported_block(identity_md, user_md)
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(imported_block, encoding="utf-8")
        return ItemStatus.OK
    if overwrite:
        target.write_text(imported_block, encoding="utf-8")
        return ItemStatus.OK
    existing = target.read_text(encoding="utf-8")
    separator = (
        "\n\n---\n\n"
        f"<!-- Imported from OpenClaw ({date.today().isoformat()}) -->"
        "\n\n"
    )
    target.write_text(existing + separator + imported_block, encoding="utf-8")
    return ItemStatus.WARN


def plan_persona_migration(
    source: SourceInfo,
    target_workspace: Path,
    archive_dir: Path,
    overwrite: bool,
) -> list[MigrationItem]:
    items: list[MigrationItem] = []
    ws = source.workspace

    for name in ("SOUL.md", "AGENTS.md"):
        src = ws / name
        dst = target_workspace / name
        if not src.exists():
            items.append(
                MigrationItem(
                    category="persona",
                    source_path=str(src),
                    target_path=str(dst),
                    status=ItemStatus.SKIP,
                    detail=f"{name} not found in source",
                ),
            )
            continue
        if dst.exists() and not overwrite:
            items.append(
                MigrationItem(
                    category="persona",
                    source_path=str(src),
                    target_path=str(dst),
                    status=ItemStatus.CONFLICT,
                    detail=f"{name} already exists at target",
                ),
            )
            continue
        items.append(
            MigrationItem(
                category="persona",
                source_path=str(src),
                target_path=str(dst),
                status=ItemStatus.OK,
                detail=f"copy {name}",
                write_fn=_make_copy_fn(src, dst),
            ),
        )

    # IDENTITY.md + USER.md → PROFILE.md
    identity_src = ws / "IDENTITY.md"
    user_src = ws / "USER.md"
    profile_dst = target_workspace / "PROFILE.md"
    identity_md = (
        identity_src.read_text(encoding="utf-8")
        if identity_src.exists()
        else None
    )
    user_md = (
        user_src.read_text(encoding="utf-8") if user_src.exists() else None
    )

    if identity_md or user_md:
        if profile_dst.exists() and not overwrite:
            status = ItemStatus.WARN
            detail = "PROFILE.md exists; will append imported content"
        else:
            status = ItemStatus.OK
            detail = "merge IDENTITY.md + USER.md → PROFILE.md"

        items.append(
            MigrationItem(
                category="persona",
                source_path=str(identity_src if identity_md else user_src),
                target_path=str(profile_dst),
                status=status,
                detail=detail,
                write_fn=lambda: _write_profile(
                    profile_dst,
                    identity_md,
                    user_md,
                    overwrite,
                ),
            ),
        )
    else:
        items.append(
            MigrationItem(
                category="persona",
                source_path=str(identity_src),
                target_path=str(profile_dst),
                status=ItemStatus.SKIP,
                detail="neither IDENTITY.md nor USER.md found",
            ),
        )

    # TOOLS.md, BOOTSTRAP.md → archive
    for name in ("TOOLS.md", "BOOTSTRAP.md", "HEARTBEAT.md"):
        src = ws / name
        if not src.exists():
            continue
        dst = archive_dir / name
        items.append(
            MigrationItem(
                category="persona",
                source_path=str(src),
                target_path=str(dst),
                status=ItemStatus.ARCHIVED,
                detail=f"{name} archived (no direct equivalent)",
                write_fn=_make_copy_fn(src, dst),
            ),
        )

    return items
