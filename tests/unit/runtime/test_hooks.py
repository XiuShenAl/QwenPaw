# -*- coding: utf-8 -*-
# pylint: disable=unused-argument
"""Unit tests for ``qwenpaw.runtime.hooks``."""

from __future__ import annotations

import pytest

from qwenpaw.runtime.hooks import (
    HookAction,
    HookBase,
    HookContext,
    HookCycleError,
    HookRegistry,
    HookResult,
)
from qwenpaw.runtime.phases import Phase


def _make_ctx() -> HookContext:
    """Build a barebones ``HookContext`` — fields irrelevant to these tests."""
    return HookContext(
        request=None,  # type: ignore[arg-type]
        session_id="s",
        agent_id="a",
        root_session_id="s",
        root_agent_id="a",
        workspace_dir=None,
        kernel=None,
        app_services=None,
    )


class _Recording(HookBase):
    """Hook that appends its name to a shared list when run."""

    phase = Phase.PRE_DISPATCH

    def __init__(
        self,
        name: str,
        log: list[str],
        *,
        priority: int = 100,
        before: tuple[str, ...] = (),
        after: tuple[str, ...] = (),
        action: HookAction = HookAction.CONTINUE,
    ) -> None:
        self.name = name
        self.priority = priority
        self.before = before
        self.after = after
        self._log = log
        self._action = action

    async def run(self, ctx: HookContext) -> HookResult:
        self._log.append(self.name)
        return HookResult(action=self._action)


@pytest.mark.asyncio
async def test_priority_orders_hooks_ascending() -> None:
    log: list[str] = []
    reg = HookRegistry()
    reg.register(_Recording("c", log, priority=300))
    reg.register(_Recording("a", log, priority=100))
    reg.register(_Recording("b", log, priority=200))

    await reg.run(Phase.PRE_DISPATCH, _make_ctx())

    assert log == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_before_after_constraints_force_order() -> None:
    log: list[str] = []
    reg = HookRegistry()
    # 'last' runs after both 'first' and 'middle' regardless of priority.
    reg.register(
        _Recording("last", log, priority=1, after=("first", "middle")),
    )
    reg.register(_Recording("first", log, priority=500))
    reg.register(_Recording("middle", log, priority=500, before=("last",)))

    await reg.run(Phase.PRE_DISPATCH, _make_ctx())

    assert log.index("first") < log.index("last")
    assert log.index("middle") < log.index("last")


@pytest.mark.asyncio
async def test_short_circuit_stops_phase_immediately() -> None:
    log: list[str] = []
    reg = HookRegistry()
    reg.register(_Recording("first", log, priority=1))
    reg.register(
        _Recording(
            "blocker",
            log,
            priority=2,
            action=HookAction.SHORT_CIRCUIT,
        ),
    )
    reg.register(_Recording("never", log, priority=3))

    result = await reg.run(Phase.PRE_DISPATCH, _make_ctx())

    assert result.action == HookAction.SHORT_CIRCUIT
    assert log == ["first", "blocker"]


@pytest.mark.asyncio
async def test_skip_agent_is_sticky_but_lets_phase_finish() -> None:
    log: list[str] = []
    reg = HookRegistry()
    reg.register(
        _Recording("a", log, priority=1, action=HookAction.SKIP_AGENT),
    )
    reg.register(_Recording("b", log, priority=2))

    result = await reg.run(Phase.PRE_DISPATCH, _make_ctx())

    assert result.action == HookAction.SKIP_AGENT
    assert log == ["a", "b"]


def test_cycle_detection_raises_hookcycleerror() -> None:
    log: list[str] = []
    reg = HookRegistry()
    reg.register(_Recording("a", log, after=("b",)))
    reg.register(_Recording("b", log, after=("a",)))

    with pytest.raises(HookCycleError):
        reg.hooks_for(Phase.PRE_DISPATCH)


@pytest.mark.asyncio
async def test_exception_propagates_not_swallowed() -> None:
    class _Boom(HookBase):
        phase = Phase.PRE_DISPATCH
        name = "boom"

        async def run(self, ctx: HookContext) -> HookResult:
            raise RuntimeError("nope")

    reg = HookRegistry()
    reg.register(_Boom())

    with pytest.raises(RuntimeError, match="nope"):
        await reg.run(Phase.PRE_DISPATCH, _make_ctx())


def test_register_validates_inputs() -> None:
    reg = HookRegistry()

    with pytest.raises(TypeError):
        reg.register("not a hook")  # type: ignore[arg-type]

    class _NoName(HookBase):
        phase = Phase.PRE_DISPATCH
        name = ""

    with pytest.raises(ValueError, match="non-empty"):
        reg.register(_NoName())


def test_merge_combines_registries() -> None:
    log: list[str] = []
    r1 = HookRegistry()
    r1.register(_Recording("x", log))
    r2 = HookRegistry()
    r2.register(_Recording("y", log))

    merged = HookRegistry.merge(r1, r2)
    names = [h.name for h in merged.hooks_for(Phase.PRE_DISPATCH)]

    assert set(names) == {"x", "y"}


def test_register_invalidates_sorted_cache() -> None:
    log: list[str] = []
    reg = HookRegistry()
    reg.register(_Recording("a", log, priority=10))
    first = reg.hooks_for(Phase.PRE_DISPATCH)
    assert [h.name for h in first] == ["a"]

    reg.register(_Recording("b", log, priority=5))
    second = reg.hooks_for(Phase.PRE_DISPATCH)
    assert [h.name for h in second] == ["b", "a"]
