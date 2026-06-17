# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable


class ItemStatus(str, Enum):
    OK = "ok"
    SKIP = "skip"
    CONFLICT = "conflict"
    WARN = "warn"
    ERROR = "error"
    ARCHIVED = "archived"


@dataclass
class SourceInfo:
    root: Path
    flavor: str
    config: dict
    env: dict[str, str]
    workspace: Path
    agent_id: str
    sessions_dir: Path | None = field(default=None)
    cron_path: Path | None = field(default=None)


@dataclass
class MigrationItem:
    category: str
    source_path: str
    target_path: str
    status: ItemStatus
    detail: str
    write_fn: Callable | None = field(default=None)


@dataclass
class MigrationPlan:
    source: SourceInfo
    target_agent_id: str
    target_workspace: Path
    items: list[MigrationItem] = field(default_factory=list)


@dataclass
class MigrationReport:
    plan: MigrationPlan
    applied: int
    skipped: int
    conflicts: int
    warnings: int
    errors: int
    backup_path: Path | None = field(default=None)
