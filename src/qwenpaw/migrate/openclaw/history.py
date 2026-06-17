# -*- coding: utf-8 -*-
"""Conversation history migration (opt-in).

OpenClaw JSONL sessions → QwenPaw dialog/ logs.
"""
from __future__ import annotations

import json
from datetime import datetime
from functools import partial
from pathlib import Path

from ..models import ItemStatus, MigrationItem, SourceInfo


def plan_history_migration(
    source: SourceInfo,
    target_workspace: Path,
    overwrite: bool,
) -> list[MigrationItem]:
    if source.sessions_dir is None or not source.sessions_dir.is_dir():
        return []

    session_count = 0
    sessions_meta = source.sessions_dir / "sessions.json"
    if sessions_meta.is_file():
        try:
            meta = json.loads(sessions_meta.read_text(encoding="utf-8"))
            session_count = (
                len(meta)
                if isinstance(meta, list)
                else len(meta.get("sessions", []))
            )
        except (json.JSONDecodeError, OSError):
            pass

    jsonl_files = sorted(source.sessions_dir.glob("*.jsonl"))
    if not jsonl_files:
        return []

    detail = f"{len(jsonl_files)} session file(s)"
    if session_count:
        detail += f" ({session_count} in sessions.json)"

    dialog_dir = target_workspace / "dialog"
    status = ItemStatus.OK
    if dialog_dir.is_dir() and any(dialog_dir.iterdir()) and not overwrite:
        status = ItemStatus.CONFLICT
        detail += " — dialog/ already has files (use --overwrite)"

    return [
        MigrationItem(
            category="history",
            source_path=str(source.sessions_dir),
            target_path=str(dialog_dir),
            status=status,
            detail=detail,
            write_fn=partial(
                _convert_all_sessions,
                source.sessions_dir,
                target_workspace,
            ),
        ),
    ]


def _convert_all_sessions(sessions_dir: Path, target_workspace: Path) -> None:
    dialog_dir = target_workspace / "dialog"
    dialog_dir.mkdir(parents=True, exist_ok=True)
    for jsonl_file in sorted(sessions_dir.glob("*.jsonl")):
        _convert_session_to_dialog(jsonl_file, dialog_dir)


def _convert_session_to_dialog(session_path: Path, dialog_dir: Path) -> None:
    for line in session_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts_str = entry.get("timestamp", "")
        msg = entry.get("message", {})
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            date_str = ts.strftime("%Y-%m-%d")
        except (ValueError, AttributeError):
            date_str = "unknown"
        out = {
            "role": msg.get("role", "unknown"),
            "content": msg.get("content", "")
            if isinstance(msg.get("content"), str)
            else str(msg.get("content", "")),
            "timestamp": ts_str,
        }
        dialog_file = dialog_dir / f"{date_str}.jsonl"
        with open(dialog_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(out, ensure_ascii=False) + "\n")
