# -*- coding: utf-8 -*-
from __future__ import annotations

import json

from qwenpaw.migrate.openclaw.history import (
    plan_history_migration,
    _convert_session_to_dialog,
)
from qwenpaw.migrate.models import SourceInfo, ItemStatus


def _make_source(
    root,
    workspace,
    config=None,
    env=None,
    sessions_dir=None,
    cron_path=None,
):
    return SourceInfo(
        root=root,
        flavor="openclaw",
        config=config or {},
        env=env or {},
        workspace=workspace,
        agent_id="main",
        sessions_dir=sessions_dir,
        cron_path=cron_path,
    )


class TestConvertSessionToDialog:
    def test_basic_conversion(self, tmp_path):
        session = tmp_path / "sess.jsonl"
        session.write_text(
            '{"timestamp":"2026-02-19T10:00:00.000Z",'
            '"message":{"role":"user","content":"Hello!"}}\n'
            '{"timestamp":"2026-02-19T10:00:05.000Z",'
            '"message":{"role":"assistant","content":"Hi!"}}\n',
        )
        dialog_dir = tmp_path / "dialog"
        dialog_dir.mkdir()

        _convert_session_to_dialog(session, dialog_dir)

        out_file = dialog_dir / "2026-02-19.jsonl"
        assert out_file.exists()
        lines = [json.loads(ln) for ln in out_file.read_text().splitlines()]
        assert len(lines) == 2
        assert lines[0]["role"] == "user"
        assert lines[0]["content"] == "Hello!"
        assert lines[1]["role"] == "assistant"
        assert lines[1]["content"] == "Hi!"

    def test_malformed_lines_skipped(self, tmp_path):
        session = tmp_path / "bad.jsonl"
        session.write_text(
            "NOT_JSON\n"
            '{"timestamp":"2026-02-19T10:00:00.000Z",'
            '"message":{"role":"user","content":"ok"}}\n'
            "{broken\n",
        )
        dialog_dir = tmp_path / "dialog"
        dialog_dir.mkdir()

        _convert_session_to_dialog(session, dialog_dir)

        out_file = dialog_dir / "2026-02-19.jsonl"
        assert out_file.exists()
        lines = out_file.read_text().strip().splitlines()
        assert len(lines) == 1

    def test_missing_timestamp_uses_unknown(self, tmp_path):
        session = tmp_path / "no_ts.jsonl"
        session.write_text('{"message":{"role":"user","content":"hi"}}\n')
        dialog_dir = tmp_path / "dialog"
        dialog_dir.mkdir()

        _convert_session_to_dialog(session, dialog_dir)

        assert (dialog_dir / "unknown.jsonl").exists()

    def test_blank_lines_ignored(self, tmp_path):
        session = tmp_path / "blanks.jsonl"
        session.write_text(
            "\n"
            '{"timestamp":"2026-01-01T00:00:00.000Z",'
            '"message":{"role":"user","content":"x"}}\n'
            "   \n",
        )
        dialog_dir = tmp_path / "dialog"
        dialog_dir.mkdir()

        _convert_session_to_dialog(session, dialog_dir)

        lines = (
            (dialog_dir / "2026-01-01.jsonl").read_text().strip().splitlines()
        )
        assert len(lines) == 1


class TestPlanHistoryMigration:
    def test_valid_sessions_dir(self, tmp_path):
        sessions = tmp_path / "sessions"
        sessions.mkdir()
        (sessions / "a.jsonl").write_text(
            '{"timestamp":"2026-01-01T00:00:00Z",'
            '"message":{"role":"user","content":"x"}}\n',
        )

        ws = tmp_path / "workspace"
        ws.mkdir()
        source = _make_source(tmp_path, ws, sessions_dir=sessions)

        items = plan_history_migration(source, ws, overwrite=False)
        assert len(items) == 1
        assert items[0].status == ItemStatus.OK
        assert items[0].category == "history"

    def test_none_sessions_dir_returns_empty(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        source = _make_source(tmp_path, ws, sessions_dir=None)

        items = plan_history_migration(source, ws, overwrite=False)
        assert not items

    def test_nonexistent_sessions_dir_returns_empty(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        source = _make_source(tmp_path, ws, sessions_dir=tmp_path / "nope")

        items = plan_history_migration(source, ws, overwrite=False)
        assert not items

    def test_empty_sessions_dir_returns_empty(self, tmp_path):
        sessions = tmp_path / "sessions"
        sessions.mkdir()
        ws = tmp_path / "workspace"
        ws.mkdir()
        source = _make_source(tmp_path, ws, sessions_dir=sessions)

        items = plan_history_migration(source, ws, overwrite=False)
        assert not items

    def test_conflict_when_dialog_exists(self, tmp_path):
        sessions = tmp_path / "sessions"
        sessions.mkdir()
        (sessions / "a.jsonl").write_text("{}\n")

        ws = tmp_path / "workspace"
        dialog = ws / "dialog"
        dialog.mkdir(parents=True)
        (dialog / "old.jsonl").write_text("existing\n")

        source = _make_source(tmp_path, ws, sessions_dir=sessions)

        items = plan_history_migration(source, ws, overwrite=False)
        assert len(items) == 1
        assert items[0].status == ItemStatus.CONFLICT

    def test_overwrite_bypasses_conflict(self, tmp_path):
        sessions = tmp_path / "sessions"
        sessions.mkdir()
        (sessions / "a.jsonl").write_text("{}\n")

        ws = tmp_path / "workspace"
        dialog = ws / "dialog"
        dialog.mkdir(parents=True)
        (dialog / "old.jsonl").write_text("existing\n")

        source = _make_source(tmp_path, ws, sessions_dir=sessions)

        items = plan_history_migration(source, ws, overwrite=True)
        assert len(items) == 1
        assert items[0].status == ItemStatus.OK
