# -*- coding: utf-8 -*-
"""Unit tests for CronContextHook."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from qwenpaw.hooks.cron.cron_hook import CronContextHook, IS_CRON_KEY
from qwenpaw.runtime.hooks import HookContext


def _make_ctx(**overrides) -> HookContext:
    defaults = {
        "request": SimpleNamespace(channel="console", user_id="u1"),
        "session_id": "s1",
        "agent_id": "default",
        "root_session_id": "s1",
        "root_agent_id": "default",
        "workspace_dir": None,
        "workspace": None,
        "app_services": None,
    }
    defaults.update(overrides)
    return HookContext(**defaults)


class TestCronContextHook:
    @pytest.mark.asyncio
    async def test_marks_cron_request(self):
        hook = CronContextHook()
        req = SimpleNamespace(
            channel="console",
            user_id="u1",
            session_source="cron",
        )
        ctx = _make_ctx(request=req)
        r = await hook.run(ctx)
        assert r.action.value == "continue"
        assert ctx.extras[IS_CRON_KEY] is True

    @pytest.mark.asyncio
    async def test_skips_non_cron_request(self):
        hook = CronContextHook()
        ctx = _make_ctx()
        r = await hook.run(ctx)
        assert r.action.value == "continue"
        assert IS_CRON_KEY not in ctx.extras

    @pytest.mark.asyncio
    async def test_skips_when_no_session_source(self):
        hook = CronContextHook()
        req = SimpleNamespace(channel="console", user_id="u1")
        ctx = _make_ctx(request=req)
        r = await hook.run(ctx)
        assert r.action.value == "continue"
        assert IS_CRON_KEY not in ctx.extras
