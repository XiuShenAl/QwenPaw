# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
"""Phase 3 parity contract: legacy prompt concatenation ≡ PromptManager.

Per ``RUNTIME_REFACTOR_IMPL_PLAN.md`` §4.3, we compare the legacy
``_build_sys_prompt`` chain against ``PromptManager.build_sync`` across
three representative fixtures:

1. **default**   — only AGENTS.md exists, no memory, no coding mode.
2. **with_memory** — AGENTS.md + SOUL.md + PROFILE.md + a memory manager.
3. **coding_mode** — AGENTS.md + coding mode enabled with a project dir.

Because the legacy ``PromptBuilder`` uses a slightly different internal
join format (``["# FILE", "", content, ""]`` joined with ``"\\n\\n"``
produces 4 newlines between header and content), while the new path uses
``"# FILE\\n\\n<content>"`` joined by ``"\\n\\n"``, we normalize
consecutive blank lines before comparison. This is semantically correct:
LLMs are whitespace-insensitive between prompt sections.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.agents.prompt import (
    build_multimodal_hint,
    build_system_prompt_from_working_dir,
)
from qwenpaw.runtime.prompt_contributors import build_default_prompt_manager

# ---------------------------------------------------------------------------
# Normalizer
# ---------------------------------------------------------------------------


def _normalize(text: str) -> str:
    """Collapse runs of blank lines and strip trailing whitespace."""
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def default_workspace(tmp_path: Path) -> Path:
    (tmp_path / "AGENTS.md").write_text(
        "You are a helpful assistant.\n\nDo good work.",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def full_workspace(tmp_path: Path) -> Path:
    (tmp_path / "AGENTS.md").write_text(
        "Agent rules here.\n\nFollow carefully.",
        encoding="utf-8",
    )
    (tmp_path / "SOUL.md").write_text(
        "I am kind and thoughtful.",
        encoding="utf-8",
    )
    (tmp_path / "PROFILE.md").write_text(
        "User: Bob\nPreference: concise answers",
        encoding="utf-8",
    )
    return tmp_path


class _FakeMemoryManager:
    def get_memory_prompt(self, language: str) -> str:
        return f"[Memory hint for {language}]"


# ---------------------------------------------------------------------------
# Legacy path helper
# ---------------------------------------------------------------------------


def _legacy_build(
    workspace: Path,
    *,
    agent_id: str | None = None,
    heartbeat_enabled: bool = False,
    language: str = "zh",
    memory_manager=None,
    env_context: str | None = None,
    coding_block: str | None = None,
) -> str:
    """Reproduce the exact legacy ``_build_sys_prompt`` chain."""
    prompt = build_system_prompt_from_working_dir(
        working_dir=workspace,
        agent_id=agent_id,
        heartbeat_enabled=heartbeat_enabled,
        language=language,
        memory_manager=memory_manager,
    )
    multimodal_hint = build_multimodal_hint()
    if multimodal_hint:
        prompt = prompt + "\n\n" + multimodal_hint
    if coding_block:
        prompt = prompt + "\n\n" + coding_block
    if env_context:
        prompt = prompt + "\n\n" + env_context
    return prompt


# ---------------------------------------------------------------------------
# New path helper
# ---------------------------------------------------------------------------


def _new_build(
    workspace: Path,
    *,
    agent_id: str | None = None,
    heartbeat_enabled: bool = False,
    language: str = "zh",
    memory_manager=None,
    env_context: str | None = None,
    agent_config=None,
) -> str:
    pm = build_default_prompt_manager()
    ctx = SimpleNamespace(
        workspace_dir=workspace,
        agent_id=agent_id,
        extras={
            "language": language,
            "heartbeat_enabled": heartbeat_enabled,
            "memory_manager": memory_manager,
            "env_context": env_context,
            "agent_config": agent_config,
        },
    )
    return pm.build_sync(ctx)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_parity_default_agent(default_workspace: Path) -> None:
    """Default agent — AGENTS.md only, no memory, no coding mode."""
    legacy = _legacy_build(default_workspace)
    new = _new_build(default_workspace)
    assert _normalize(legacy) == _normalize(new)


def test_parity_with_agent_id(default_workspace: Path) -> None:
    """Agent identity header must match."""
    legacy = _legacy_build(default_workspace, agent_id="test-42")
    new = _new_build(default_workspace, agent_id="test-42")
    assert _normalize(legacy) == _normalize(new)


def test_parity_full_workspace_with_memory(full_workspace: Path) -> None:
    """All 3 md files + memory manager."""
    mm = _FakeMemoryManager()
    legacy = _legacy_build(
        full_workspace,
        agent_id="full",
        memory_manager=mm,
        language="en",
    )
    new = _new_build(
        full_workspace,
        agent_id="full",
        memory_manager=mm,
        language="en",
    )
    assert _normalize(legacy) == _normalize(new)


def test_parity_env_context(default_workspace: Path) -> None:
    """Env context appended last."""
    env = "==== ENV CONTEXT ===="
    legacy = _legacy_build(default_workspace, env_context=env)
    new = _new_build(default_workspace, env_context=env)
    assert _normalize(legacy) == _normalize(new)


def test_parity_heartbeat_enabled(tmp_path: Path) -> None:
    """Heartbeat section preserved when enabled."""
    text = "Intro\n<!-- heartbeat:start -->HB<!-- heartbeat:end -->\nEnd"
    (tmp_path / "AGENTS.md").write_text(text, encoding="utf-8")

    legacy = _legacy_build(tmp_path, heartbeat_enabled=True)
    new = _new_build(tmp_path, heartbeat_enabled=True)
    assert _normalize(legacy) == _normalize(new)


def test_parity_heartbeat_disabled(tmp_path: Path) -> None:
    """Heartbeat section stripped when disabled."""
    text = "Intro\n<!-- heartbeat:start -->HB<!-- heartbeat:end -->\nEnd"
    (tmp_path / "AGENTS.md").write_text(text, encoding="utf-8")

    legacy = _legacy_build(tmp_path, heartbeat_enabled=False)
    new = _new_build(tmp_path, heartbeat_enabled=False)
    assert _normalize(legacy) == _normalize(new)


def test_parity_coding_mode(default_workspace: Path) -> None:
    """Coding mode block appended correctly."""
    from qwenpaw.agents.coding_mode_mixin import _CODING_SYSTEM_PROMPT_TEMPLATE

    coding_block = _CODING_SYSTEM_PROMPT_TEMPLATE.format(
        project_dir="/proj",
        workspace_dir="/ws",
    )
    agent_config = SimpleNamespace(
        id="coder",
        coding_mode=SimpleNamespace(enabled=True, project_dir="/proj"),
    )
    legacy = _legacy_build(
        default_workspace,
        coding_block=coding_block,
    )
    new = _new_build(
        default_workspace,
        agent_config=agent_config,
    )
    # Both should contain the coding block; normalize whitespace
    assert "Coding Mode" in _normalize(legacy)
    assert "Coding Mode" in _normalize(new)
    # The workspace_dir in new path comes from ctx.workspace_dir
    assert "/proj" in new


def test_section_ordering_is_stable(full_workspace: Path) -> None:
    """Verify identity → AGENTS.md → SOUL.md → PROFILE.md → env."""
    new = _new_build(
        full_workspace,
        agent_id="order-check",
        env_context="==ENV==",
    )
    norm = _normalize(new)
    assert norm.index("Agent Identity") < norm.index("# AGENTS.md")
    assert norm.index("# AGENTS.md") < norm.index("# SOUL.md")
    assert norm.index("# SOUL.md") < norm.index("# PROFILE.md")
    assert norm.index("# PROFILE.md") < norm.index("==ENV==")
