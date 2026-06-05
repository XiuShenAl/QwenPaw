# -*- coding: utf-8 -*-
"""Unit tests for ``qwenpaw.runtime.slash_command_registry``."""

from __future__ import annotations

import pytest

from qwenpaw.runtime.slash_command_registry import (
    CommandSpec,
    SlashCommandRegistry,
)


async def _make_handler(name: str, sink: list[tuple[str, str]]):
    async def _h(_ctx, args):
        sink.append((name, args))
        return None

    return _h


@pytest.mark.asyncio
async def test_resolve_returns_spec_and_args() -> None:
    reg = SlashCommandRegistry()
    sink: list[tuple[str, str]] = []
    handler = await _make_handler("help", sink)
    reg.register(CommandSpec(name="help", handler=handler))

    match = reg.resolve("/help me please")
    assert match is not None
    spec, args = match
    assert spec.name == "help"
    assert args == "me please"


@pytest.mark.asyncio
async def test_resolve_is_case_insensitive_and_strips_whitespace() -> None:
    reg = SlashCommandRegistry()
    sink: list[tuple[str, str]] = []
    handler = await _make_handler("foo", sink)
    reg.register(CommandSpec(name="Foo", handler=handler))

    match = reg.resolve("   /FOO    bar baz   ")
    assert match is not None
    _, args = match
    assert args == "bar baz   "


@pytest.mark.asyncio
async def test_dispatch_invokes_handler_via_alias() -> None:
    reg = SlashCommandRegistry()
    sink: list[tuple[str, str]] = []
    handler = await _make_handler("status", sink)
    reg.register(
        CommandSpec(name="status", handler=handler, aliases=("st", "stat")),
    )

    await reg.dispatch("/st now", ctx=None)  # type: ignore[arg-type]

    assert sink == [("status", "now")]


@pytest.mark.asyncio
async def test_fallback_invoked_only_for_slash_text_without_match() -> None:
    reg = SlashCommandRegistry()
    fb_calls: list[str] = []

    async def fb(raw_text, _ctx):
        fb_calls.append(raw_text)
        return None

    reg.register_fallback(fb)

    # No-match slash → fallback.
    await reg.dispatch("/missing arg", ctx=None)  # type: ignore[arg-type]
    # Plain text → ignored (no slash prefix means no fallback).
    await reg.dispatch("hello world", ctx=None)  # type: ignore[arg-type]

    assert fb_calls == ["/missing arg"]


def test_resolve_returns_none_for_non_slash_or_empty() -> None:
    reg = SlashCommandRegistry()
    assert reg.resolve("") is None
    assert reg.resolve("plain text") is None
    assert reg.resolve("/") is None


def test_duplicate_name_or_alias_raises() -> None:
    reg = SlashCommandRegistry()

    async def h(_ctx, _args):
        return None

    reg.register(CommandSpec(name="foo", handler=h, aliases=("f",)))
    with pytest.raises(ValueError, match="already registered"):
        reg.register(CommandSpec(name="bar", handler=h, aliases=("f",)))


def test_fallback_can_only_register_once() -> None:
    reg = SlashCommandRegistry()

    async def fb(_raw_text, _ctx):
        return None

    reg.register_fallback(fb)
    with pytest.raises(ValueError, match="already registered"):
        reg.register_fallback(fb)
