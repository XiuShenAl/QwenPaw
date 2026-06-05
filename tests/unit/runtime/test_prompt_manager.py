# -*- coding: utf-8 -*-
"""Unit tests for ``qwenpaw.runtime.prompt_manager``."""

from __future__ import annotations

import pytest

from qwenpaw.runtime.prompt_manager import (
    PROMPT_SEPARATOR,
    PromptContributor,
    PromptManager,
    SyncPromptContributor,
)


class _Static(PromptContributor):
    def __init__(
        self,
        name: str,
        fragment: str | None,
        priority: int = 100,
    ) -> None:
        self.name = name
        self.priority = priority
        self._frag = fragment

    async def contribute(self, ctx):
        return self._frag


class _Sync(SyncPromptContributor):
    def __init__(
        self,
        name: str,
        fragment: str | None,
        priority: int = 100,
    ) -> None:
        self.name = name
        self.priority = priority
        self._frag = fragment

    def contribute_sync(self, ctx):
        return self._frag


@pytest.mark.asyncio
async def test_build_orders_by_priority_and_joins_with_separator() -> None:
    pm = PromptManager()
    pm.register(_Static("late", "LATE", priority=300))
    pm.register(_Static("first", "FIRST", priority=10))
    pm.register(_Static("mid", "MID", priority=100))

    out = await pm.build(ctx=None)

    assert out == f"FIRST{PROMPT_SEPARATOR}MID{PROMPT_SEPARATOR}LATE"


@pytest.mark.asyncio
async def test_build_skips_none_and_empty_fragments() -> None:
    pm = PromptManager()
    pm.register(_Static("a", "A"))
    pm.register(_Static("b", None, priority=200))
    pm.register(_Static("c", "", priority=300))
    pm.register(_Static("d", "D", priority=400))

    out = await pm.build(ctx=None)
    assert out == f"A{PROMPT_SEPARATOR}D"


@pytest.mark.asyncio
async def test_build_strips_fragments_before_joining() -> None:
    pm = PromptManager()
    pm.register(_Static("a", "  AAA \n"))
    pm.register(_Static("b", "\nBBB  ", priority=200))

    out = await pm.build(ctx=None)
    assert out == f"AAA{PROMPT_SEPARATOR}BBB"


@pytest.mark.asyncio
async def test_sync_contributor_runs_through_async_build() -> None:
    pm = PromptManager()
    pm.register(_Sync("s", "SYNC"))

    out = await pm.build(ctx=None)
    assert out == "SYNC"


@pytest.mark.asyncio
async def test_exception_is_logged_and_skipped() -> None:
    class _Boom(PromptContributor):
        name = "boom"
        priority = 50

        async def contribute(self, ctx):
            raise RuntimeError("kaboom")

    pm = PromptManager()
    pm.register(_Boom())
    pm.register(_Static("ok", "OK", priority=100))

    out = await pm.build(ctx=None)
    assert out == "OK"


def test_register_rejects_duplicate_name() -> None:
    pm = PromptManager()
    pm.register(_Static("dup", "x"))
    with pytest.raises(ValueError, match="already registered"):
        pm.register(_Static("dup", "y"))


def test_register_rejects_non_contributor() -> None:
    pm = PromptManager()
    with pytest.raises(TypeError):
        pm.register("not a contributor")  # type: ignore[arg-type]


def test_prompt_separator_is_locked_for_golden_tests() -> None:
    # If you intentionally change this, the Phase 3 golden tests must
    # be regenerated. Don't relax this assertion casually.
    assert PROMPT_SEPARATOR == "\n\n"
