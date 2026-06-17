# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
from functools import partial
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from ..models import ItemStatus, MigrationItem, SourceInfo

logger = logging.getLogger(__name__)


def _make_job_id(oc_job: dict) -> str:
    oc_id = oc_job.get("id", oc_job.get("name", ""))
    if oc_id:
        return f"oc-{oc_id}"
    content_hash = uuid5(NAMESPACE_URL, json.dumps(oc_job, sort_keys=True))
    return f"oc-{content_hash}"


def _extract_schedule(oc_job: dict) -> dict:
    """Extract schedule from OpenClaw's formats into a QwenPaw schedule dict.

    OpenClaw supports three schedule kinds:
      - {kind: "cron", expr: "0 9 * * *", tz: "UTC"}
      - {kind: "every", everyMs: 60000}
      - {kind: "at", at: "2024-01-01T00:00:00Z"}
    Legacy flat format: {"schedule": "0 9 * * *", "timezone": "UTC"}
    """
    raw = oc_job.get("schedule", "0 0 * * *")
    if isinstance(raw, dict):
        kind = raw.get("kind", "cron")
        if kind == "every":
            interval_ms = raw.get("everyMs", 60000)
            return {
                "type": "interval",
                "interval_seconds": max(1, interval_ms // 1000),
            }
        if kind == "at":
            return {"type": "once", "at": raw.get("at", "")}
        return {
            "type": "cron",
            "cron": raw.get("expr", "0 0 * * *"),
            "timezone": raw.get("tz", "UTC"),
        }
    return {
        "type": "cron",
        "cron": raw,
        "timezone": oc_job.get("timezone", "UTC"),
    }


def _extract_prompt(oc_job: dict) -> tuple[str, str]:
    """Extract prompt and payload kind from OpenClaw's formats.

    OpenClaw payload kinds:
      - {kind: "agentTurn", message: "..."}
      - {kind: "systemEvent", text: "..."}
      - {kind: "command", argv: [...]}
    Legacy flat format: {"prompt": "..."}

    Returns (prompt_text, payload_kind).
    """
    payload = oc_job.get("payload", {})
    if isinstance(payload, dict):
        kind = payload.get("kind", "")
        if kind == "agentTurn":
            return payload.get("message", ""), "agentTurn"
        if kind == "systemEvent":
            return payload.get("text", ""), "systemEvent"
        if kind == "command":
            argv = payload.get("argv", [])
            return " ".join(argv) if argv else "", "command"
        if payload.get("message"):
            return payload["message"], "agentTurn"
    return oc_job.get("prompt", ""), "agentTurn"


def _extract_delivery(oc_job: dict) -> tuple[str, str]:
    """Extract channel and target from OpenClaw's two formats.

    Format 1 (legacy): {"channel": "telegram", "to": "123"}
    Format 2 (current): {"delivery": {"channel": "telegram", "to": "123"}}
    """
    delivery = oc_job.get("delivery", {})
    if isinstance(delivery, dict) and (
        delivery.get("channel") or delivery.get("to")
    ):
        return delivery.get("channel", ""), delivery.get("to", "")
    return oc_job.get("channel", ""), oc_job.get("to", "")


def _convert_cron_job(oc_job: dict) -> dict:
    schedule = _extract_schedule(oc_job)
    prompt, payload_kind = _extract_prompt(oc_job)
    channel, to = _extract_delivery(oc_job)
    session_target = oc_job.get("sessionTarget", oc_job.get("session", "main"))

    result: dict = {
        "id": _make_job_id(oc_job),
        "name": oc_job.get("name", oc_job.get("id", "Imported job")),
        "enabled": oc_job.get("enabled", True),
        "schedule": schedule,
        "task_type": "command" if payload_kind == "command" else "agent",
        "request": {
            "input": prompt,
        },
        "dispatch": {
            "channel": channel,
            "target": {
                "user_id": to,
                "session_id": f"{channel}:{to}" if channel and to else "",
            },
        },
        "runtime": {
            "share_session": session_target != "isolated",
        },
    }
    if oc_job.get("agentId"):
        result["agent_id"] = oc_job["agentId"]
    if oc_job.get("deleteAfterRun"):
        result["one_shot"] = True
    return result


def _write_cron_jobs(target_workspace: Path, new_jobs: list[dict]):
    jobs_json = target_workspace / "jobs.json"
    existing: list[dict] = []
    if jobs_json.exists():
        data = json.loads(jobs_json.read_text(encoding="utf-8"))
        existing = data.get("jobs", []) if isinstance(data, dict) else data
    existing_ids = {j.get("id") for j in existing}
    for job in new_jobs:
        if job["id"] not in existing_ids:
            existing.append(job)
    jobs_json.parent.mkdir(parents=True, exist_ok=True)
    jobs_json.write_text(
        json.dumps({"jobs": existing}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def plan_cron_migration(
    source: SourceInfo,
    target_workspace: Path,
    overwrite: bool,
) -> list[MigrationItem]:
    if source.cron_path is None or not source.cron_path.exists():
        return []

    try:
        raw = json.loads(source.cron_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(
            "Failed to parse cron file %s: %s",
            source.cron_path,
            exc,
        )
        return [
            MigrationItem(
                category="cron",
                source_path=str(source.cron_path),
                target_path="jobs.json",
                status=ItemStatus.ERROR,
                detail=f"Cannot parse cron: {exc}",
            ),
        ]

    oc_jobs: list[dict] = raw if isinstance(raw, list) else raw.get("jobs", [])

    existing_ids: set[str] = set()
    target_jobs_json = target_workspace / "jobs.json"
    if target_jobs_json.exists():
        try:
            tdata = json.loads(target_jobs_json.read_text(encoding="utf-8"))
            t_jobs = (
                tdata.get("jobs", []) if isinstance(tdata, dict) else tdata
            )
            existing_ids = {j.get("id") for j in t_jobs}
        except (json.JSONDecodeError, OSError):
            pass

    items: list[MigrationItem] = []
    converted_batch: list[dict] = []

    for oc_job in oc_jobs:
        converted = _convert_cron_job(oc_job)
        job_id = converted["id"]
        oc_label = oc_job.get(
            "id",
            oc_job.get("name", "?"),
        )

        if not overwrite and job_id in existing_ids:
            items.append(
                MigrationItem(
                    category="cron",
                    source_path=f"cron#{oc_label}",
                    target_path=f"jobs.json#{job_id}",
                    status=ItemStatus.CONFLICT,
                    detail=(f"Job '{job_id}' already exists"),
                ),
            )
            continue

        converted_batch.append(converted)
        items.append(
            MigrationItem(
                category="cron",
                source_path=f"cron#{oc_label}",
                target_path=f"jobs.json#{job_id}",
                status=ItemStatus.OK,
                detail=(f"Migrate cron '{converted['name']}'"),
            ),
        )

    if converted_batch:
        batch_snapshot = list(converted_batch)
        items_ok = [i for i in items if i.status == ItemStatus.OK]
        if items_ok:
            last_ok = items_ok[-1]
            last_ok.write_fn = partial(
                _write_cron_jobs,
                target_workspace,
                batch_snapshot,
            )

    return items
