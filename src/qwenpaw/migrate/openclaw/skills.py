# -*- coding: utf-8 -*-
"""Skill mapping report: scans OpenClaw skills (no writes)."""
from __future__ import annotations

from ..models import ItemStatus, MigrationItem, SourceInfo


def plan_skill_report(source: SourceInfo) -> list[MigrationItem]:
    items: list[MigrationItem] = []
    skill_dirs = []

    ws_skills = source.workspace / "skills"
    if ws_skills.is_dir():
        skill_dirs.extend(ws_skills.iterdir())

    global_skills = source.root / "skills"
    if global_skills.is_dir():
        skill_dirs.extend(global_skills.iterdir())

    seen: set[str] = set()
    for skill_dir in skill_dirs:
        if not skill_dir.is_dir():
            continue
        name = skill_dir.name
        if name in seen:
            continue
        seen.add(name)
        items.append(
            MigrationItem(
                category="skills",
                source_path=str(skill_dir),
                target_path="(no auto-migration)",
                status=ItemStatus.ARCHIVED,
                detail=f"OpenClaw skill '{name}' — manual install needed",
                write_fn=None,
            ),
        )
    return items
