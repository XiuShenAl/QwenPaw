# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import re
import shutil
from functools import partial
from pathlib import Path

from ..models import ItemStatus, MigrationItem, SourceInfo

logger = logging.getLogger(__name__)

ENTRY_DELIMITER = "\n§\n"


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def _parse_entries(text: str) -> list[str]:
    """Parse memory entries using § delimiter, fall back to line-based."""
    if ENTRY_DELIMITER in text:
        return [e.strip() for e in text.split(ENTRY_DELIMITER) if e.strip()]
    entries: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            entries.append(line)
    return entries


def _merge_entries(
    existing: list[str],
    incoming: list[str],
) -> tuple[list[str], int, int]:
    """Merge incoming entries into existing, dedup by normalized text.

    Returns (merged_list, added_count, dup_count).
    """
    seen = {_normalize(e) for e in existing}
    merged = list(existing)
    added, dups = 0, 0
    for entry in incoming:
        norm = _normalize(entry)
        if not norm or norm in seen:
            dups += 1
            continue
        seen.add(norm)
        merged.append(entry)
        added += 1
    return merged, added, dups


def _write_merged_memory(dst: Path, merged: list[str]):
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(
        ENTRY_DELIMITER.join(merged) + ("\n" if merged else ""),
        encoding="utf-8",
    )


def _make_copy_fn(src: Path, dst: Path):
    def _do():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    return _do


def plan_memory_migration(  # pylint: disable=too-many-branches
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
        incoming = _parse_entries(
            memory_src.read_text(encoding="utf-8"),
        )
        if not incoming:
            items.append(
                MigrationItem(
                    category="memory",
                    source_path=str(memory_src),
                    target_path=str(memory_dst),
                    status=ItemStatus.SKIP,
                    detail="MEMORY.md has no importable entries",
                ),
            )
        elif memory_dst.exists() and not overwrite:
            existing = _parse_entries(
                memory_dst.read_text(encoding="utf-8"),
            )
            merged, added, dups = _merge_entries(existing, incoming)
            if added == 0:
                items.append(
                    MigrationItem(
                        category="memory",
                        source_path=str(memory_src),
                        target_path=str(memory_dst),
                        status=ItemStatus.SKIP,
                        detail=(f"All {dups} entries already exist at target"),
                    ),
                )
            else:
                snapshot = list(merged)
                items.append(
                    MigrationItem(
                        category="memory",
                        source_path=str(memory_src),
                        target_path=str(memory_dst),
                        status=ItemStatus.WARN,
                        detail=(
                            f"Merge {added} new entries into MEMORY.md"
                            f" ({dups} duplicates skipped)"
                        ),
                        write_fn=partial(
                            _write_merged_memory,
                            memory_dst,
                            snapshot,
                        ),
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
        all_daily_entries: list[str] = []
        for md_file in sorted(memory_dir.glob("*.md")):
            entries = _parse_entries(
                md_file.read_text(encoding="utf-8"),
            )
            all_daily_entries.extend(entries)

        if all_daily_entries:
            if memory_dst.exists():
                existing = _parse_entries(
                    memory_dst.read_text(encoding="utf-8"),
                )
            else:
                existing = []
            merged, added, dups = _merge_entries(existing, all_daily_entries)
            if added > 0:
                snapshot = list(merged)
                items.append(
                    MigrationItem(
                        category="memory",
                        source_path=str(memory_dir),
                        target_path=str(memory_dst),
                        status=ItemStatus.OK
                        if not memory_dst.exists()
                        else ItemStatus.WARN,
                        detail=(
                            f"Merge {added} daily memory entries"
                            f" ({dups} duplicates skipped)"
                        ),
                        write_fn=partial(
                            _write_merged_memory,
                            memory_dst,
                            snapshot,
                        ),
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
                detail="DREAMS.md archived (QwenPaw ReMe manages dreams)",
                write_fn=_make_copy_fn(dreams_src, dreams_dst),
            ),
        )

    return items
