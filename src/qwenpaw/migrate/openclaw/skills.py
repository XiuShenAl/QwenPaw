# -*- coding: utf-8 -*-
"""Skill migration: copy OpenClaw skills into QwenPaw workspace."""
from __future__ import annotations

import shutil
from functools import partial
from pathlib import Path

from ..models import ItemStatus, MigrationItem, SourceInfo

SKILL_IMPORT_DIRNAME = "openclaw-imports"


def _collect_skill_dirs(source: SourceInfo) -> list[tuple[Path, str]]:
    """Find skill directories from all OpenClaw skill sources."""
    candidates: list[tuple[Path, str]] = []

    ws_skills = source.workspace / "skills"
    if ws_skills.is_dir():
        for d in sorted(ws_skills.iterdir()):
            if d.is_dir() and (d / "SKILL.md").exists():
                candidates.append((d, "workspace"))

    global_skills = source.root / "skills"
    if global_skills.is_dir():
        for d in sorted(global_skills.iterdir()):
            if d.is_dir() and (d / "SKILL.md").exists():
                candidates.append((d, "managed"))

    personal = Path.home() / ".agents" / "skills"
    if personal.is_dir():
        for d in sorted(personal.iterdir()):
            if d.is_dir() and (d / "SKILL.md").exists():
                candidates.append((d, "personal"))

    return candidates


def _copy_skill(src: Path, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def plan_skill_migration(
    source: SourceInfo,
    target_workspace: Path,
    overwrite: bool,
) -> list[MigrationItem]:
    items: list[MigrationItem] = []
    skill_dirs = _collect_skill_dirs(source)

    if not skill_dirs:
        items.append(
            MigrationItem(
                category="skills",
                source_path="(none)",
                target_path="(no skills found)",
                status=ItemStatus.SKIP,
                detail="No OpenClaw skills found",
            ),
        )
        return items

    import_dir = target_workspace / "skills" / SKILL_IMPORT_DIRNAME
    seen: set[str] = set()

    for skill_dir, origin in skill_dirs:
        name = skill_dir.name
        if name in seen:
            continue
        seen.add(name)

        dst = import_dir / name
        if dst.exists() and not overwrite:
            items.append(
                MigrationItem(
                    category="skills",
                    source_path=str(skill_dir),
                    target_path=str(dst),
                    status=ItemStatus.CONFLICT,
                    detail=f"Skill '{name}' already exists at target",
                ),
            )
            continue

        items.append(
            MigrationItem(
                category="skills",
                source_path=str(skill_dir),
                target_path=str(dst),
                status=ItemStatus.OK,
                detail=f"Copy {origin} skill '{name}'",
                write_fn=partial(_copy_skill, skill_dir, dst),
            ),
        )

    return items


def plan_skill_report(source: SourceInfo) -> list[MigrationItem]:
    """Legacy report-only: kept for backward compatibility."""
    return plan_skill_migration(source, Path("/dev/null"), overwrite=False)
