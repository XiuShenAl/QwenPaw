# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

from qwenpaw.migrate.models import ItemStatus, SourceInfo
from qwenpaw.migrate.openclaw.cron import (
    _convert_cron_job,
    _extract_delivery,
    _extract_prompt,
    _extract_schedule,
    _make_job_id,
    plan_cron_migration,
)


def _make_source(
    root: Path,
    workspace: Path,
    config=None,
    env=None,
    cron_path=None,
):
    return SourceInfo(
        root=root,
        flavor="openclaw",
        config=config or {},
        env=env or {},
        workspace=workspace,
        agent_id="main",
        cron_path=cron_path,
    )


class TestMakeJobId:
    def test_with_id_field(self):
        assert _make_job_id({"id": "daily-report"}) == "oc-daily-report"

    def test_with_name_only(self):
        assert _make_job_id({"name": "Daily"}) == "oc-Daily"

    def test_deterministic_for_same_content(self):
        job = {"schedule": "0 9 * * *", "prompt": "hello"}
        assert _make_job_id(job) == _make_job_id(job)


class TestExtractSchedule:
    def test_legacy_string_format(self):
        result = _extract_schedule(
            {"schedule": "0 9 * * *", "timezone": "Asia/Tokyo"},
        )
        assert result["type"] == "cron"
        assert result["cron"] == "0 9 * * *"
        assert result["timezone"] == "Asia/Tokyo"

    def test_current_cron_dict_format(self):
        result = _extract_schedule(
            {
                "schedule": {
                    "kind": "cron",
                    "expr": "0 7 * * *",
                    "tz": "US/Eastern",
                },
            },
        )
        assert result["type"] == "cron"
        assert result["cron"] == "0 7 * * *"
        assert result["timezone"] == "US/Eastern"

    def test_every_format(self):
        result = _extract_schedule(
            {"schedule": {"kind": "every", "everyMs": 300000}},
        )
        assert result["type"] == "interval"
        assert result["interval_seconds"] == 300

    def test_at_format(self):
        result = _extract_schedule(
            {"schedule": {"kind": "at", "at": "2024-12-25T00:00:00Z"}},
        )
        assert result["type"] == "once"
        assert result["at"] == "2024-12-25T00:00:00Z"


class TestExtractPrompt:
    def test_legacy_prompt_field(self):
        text, kind = _extract_prompt({"prompt": "hello"})
        assert text == "hello"
        assert kind == "agentTurn"

    def test_current_agent_turn(self):
        text, kind = _extract_prompt(
            {"payload": {"kind": "agentTurn", "message": "hi"}},
        )
        assert text == "hi"
        assert kind == "agentTurn"

    def test_system_event(self):
        text, kind = _extract_prompt(
            {"payload": {"kind": "systemEvent", "text": "startup"}},
        )
        assert text == "startup"
        assert kind == "systemEvent"

    def test_command_payload(self):
        text, kind = _extract_prompt(
            {"payload": {"kind": "command", "argv": ["echo", "hello"]}},
        )
        assert text == "echo hello"
        assert kind == "command"


class TestExtractDelivery:
    def test_legacy_flat_fields(self):
        ch, to = _extract_delivery({"channel": "telegram", "to": "123"})
        assert ch == "telegram"
        assert to == "123"

    def test_current_delivery_object(self):
        ch, to = _extract_delivery(
            {"delivery": {"channel": "slack", "to": "C1234"}},
        )
        assert ch == "slack"
        assert to == "C1234"


class TestConvertCronJob:
    def test_legacy_format(self):
        oc_job = {
            "id": "nightly",
            "name": "Nightly Digest",
            "enabled": True,
            "schedule": "0 22 * * *",
            "timezone": "Asia/Shanghai",
            "prompt": "Send digest",
            "channel": "telegram",
            "to": "user123",
            "session": "shared",
        }
        result = _convert_cron_job(oc_job)

        assert result["id"] == "oc-nightly"
        assert result["name"] == "Nightly Digest"
        assert result["enabled"] is True
        assert result["schedule"]["type"] == "cron"
        assert result["schedule"]["cron"] == "0 22 * * *"
        assert result["schedule"]["timezone"] == "Asia/Shanghai"
        assert result["task_type"] == "agent"
        assert result["request"]["input"] == "Send digest"
        assert result["dispatch"]["channel"] == "telegram"
        assert result["dispatch"]["target"]["user_id"] == "user123"
        assert result["runtime"]["share_session"] is True

    def test_current_format(self):
        oc_job = {
            "name": "Morning brief",
            "schedule": {
                "kind": "cron",
                "expr": "0 7 * * *",
                "tz": "America/Los_Angeles",
            },
            "sessionTarget": "isolated",
            "payload": {"kind": "agentTurn", "message": "Summarize updates."},
            "delivery": {
                "mode": "announce",
                "channel": "slack",
                "to": "channel:C1234567890",
            },
        }
        result = _convert_cron_job(oc_job)

        assert result["schedule"]["type"] == "cron"
        assert result["schedule"]["cron"] == "0 7 * * *"
        assert result["schedule"]["timezone"] == "America/Los_Angeles"
        assert result["request"]["input"] == "Summarize updates."
        assert result["dispatch"]["channel"] == "slack"
        assert result["dispatch"]["target"]["user_id"] == "channel:C1234567890"
        assert result["runtime"]["share_session"] is False

    def test_every_interval_job(self):
        oc_job = {
            "id": "heartbeat",
            "name": "Heartbeat check",
            "schedule": {"kind": "every", "everyMs": 60000},
            "payload": {"kind": "systemEvent", "text": "Heartbeat ping"},
        }
        result = _convert_cron_job(oc_job)
        assert result["schedule"]["type"] == "interval"
        assert result["schedule"]["interval_seconds"] == 60
        assert result["request"]["input"] == "Heartbeat ping"

    def test_command_payload(self):
        oc_job = {
            "id": "backup",
            "name": "Nightly backup",
            "schedule": "0 3 * * *",
            "payload": {
                "kind": "command",
                "argv": ["/usr/bin/backup", "--full"],
            },
        }
        result = _convert_cron_job(oc_job)
        assert result["task_type"] == "command"
        assert result["request"]["input"] == "/usr/bin/backup --full"

    def test_agent_id_and_delete_after_run(self):
        oc_job = {
            "id": "onetime",
            "name": "One shot",
            "schedule": {"kind": "at", "at": "2025-01-01T00:00:00Z"},
            "payload": {"kind": "agentTurn", "message": "Happy New Year!"},
            "agentId": "assistant-2",
            "deleteAfterRun": True,
        }
        result = _convert_cron_job(oc_job)
        assert result["schedule"]["type"] == "once"
        assert result["agent_id"] == "assistant-2"
        assert result["one_shot"] is True


class TestPlanCronMigration:
    def test_valid_cron_file(self, tmp_path: Path):
        source_ws = tmp_path / "source"
        source_ws.mkdir()
        target_ws = tmp_path / "target"
        target_ws.mkdir()

        cron_dir = source_ws / "cron"
        cron_dir.mkdir()
        cron_file = cron_dir / "cron.json"
        cron_file.write_text(
            json.dumps(
                {
                    "jobs": [
                        {
                            "id": "morning",
                            "schedule": "0 8 * * *",
                            "prompt": "Good morning",
                        },
                    ],
                },
            ),
        )

        source = _make_source(source_ws, source_ws, cron_path=cron_file)
        items = plan_cron_migration(source, target_ws, overwrite=False)

        assert len(items) == 1
        assert items[0].status == ItemStatus.OK
        assert "morning" in items[0].detail

    def test_conflict_detection(self, tmp_path: Path):
        source_ws = tmp_path / "source"
        source_ws.mkdir()
        target_ws = tmp_path / "target"
        target_ws.mkdir()

        cron_dir = source_ws / "cron"
        cron_dir.mkdir()
        cron_file = cron_dir / "cron.json"
        cron_file.write_text(
            json.dumps(
                {
                    "jobs": [
                        {
                            "id": "daily",
                            "schedule": "0 0 * * *",
                            "prompt": "hi",
                        },
                    ],
                },
            ),
        )

        jobs_json = target_ws / "jobs.json"
        jobs_json.write_text(
            json.dumps(
                {
                    "jobs": [{"id": "oc-daily", "name": "existing"}],
                },
            ),
        )

        source = _make_source(source_ws, source_ws, cron_path=cron_file)
        items = plan_cron_migration(source, target_ws, overwrite=False)

        assert len(items) == 1
        assert items[0].status == ItemStatus.CONFLICT

    def test_missing_cron_file_returns_empty(self, tmp_path: Path):
        source_ws = tmp_path / "source"
        source_ws.mkdir()
        target_ws = tmp_path / "target"
        target_ws.mkdir()

        missing = source_ws / "cron" / "cron.json"
        source = _make_source(source_ws, source_ws, cron_path=missing)
        items = plan_cron_migration(source, target_ws, overwrite=False)

        assert not items

    def test_none_cron_path_returns_empty(self, tmp_path: Path):
        source_ws = tmp_path / "source"
        source_ws.mkdir()
        target_ws = tmp_path / "target"
        target_ws.mkdir()

        source = _make_source(source_ws, source_ws, cron_path=None)
        items = plan_cron_migration(source, target_ws, overwrite=False)

        assert not items
