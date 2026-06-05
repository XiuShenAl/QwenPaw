# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
"""Unit tests for ``qwenpaw.runtime.prompt_contributors``.

Each contributor is tested in isolation with a temp workspace directory
and a :class:`SimpleNamespace` stub standing in for ``HookContext``.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.runtime.prompt_contributors import (
    AgentIdentityContributor,
    AgentsMdContributor,
    CodingModeContributor,
    EnvContextContributor,
    MultimodalHintContributor,
    ProfileMdContributor,
    SoulMdContributor,
    build_default_prompt_manager,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ctx(
    workspace_dir: Path | None = None,
    agent_id: str | None = None,
    **extras,
) -> SimpleNamespace:
    return SimpleNamespace(
        workspace_dir=workspace_dir,
        agent_id=agent_id,
        extras=extras,
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path


# ---------------------------------------------------------------------------
# AgentIdentityContributor
# ---------------------------------------------------------------------------


def test_agent_identity_with_id() -> None:
    c = AgentIdentityContributor()
    out = c.contribute_sync(_ctx(agent_id="abc123"))
    assert out is not None
    assert "Your agent id is `abc123`" in out
    assert out.startswith("# Agent Identity")


def test_agent_identity_without_id() -> None:
    c = AgentIdentityContributor()
    assert c.contribute_sync(_ctx()) is None


# ---------------------------------------------------------------------------
# AgentsMdContributor
# ---------------------------------------------------------------------------


def test_agents_md_basic(workspace: Path) -> None:
    (workspace / "AGENTS.md").write_text("Be helpful.", encoding="utf-8")
    c = AgentsMdContributor()
    out = c.contribute_sync(_ctx(workspace_dir=workspace))
    assert out is not None
    assert out.startswith("# AGENTS.md")
    assert "Be helpful." in out


def test_agents_md_strips_frontmatter(workspace: Path) -> None:
    (workspace / "AGENTS.md").write_text(
        "---\ntitle: test\n---\nReal content.",
        encoding="utf-8",
    )
    c = AgentsMdContributor()
    out = c.contribute_sync(_ctx(workspace_dir=workspace))
    assert out is not None
    assert "title: test" not in out
    assert "Real content." in out


def test_agents_md_heartbeat_enabled(workspace: Path) -> None:
    text = "Intro\n<!-- heartbeat:start -->HB<!-- heartbeat:end -->\nEnd"
    (workspace / "AGENTS.md").write_text(text, encoding="utf-8")
    c = AgentsMdContributor()
    out = c.contribute_sync(
        _ctx(workspace_dir=workspace, heartbeat_enabled=True),
    )
    assert "HB" in out
    assert "<!-- heartbeat" not in out


def test_agents_md_heartbeat_disabled(workspace: Path) -> None:
    text = "Intro\n<!-- heartbeat:start -->HB<!-- heartbeat:end -->\nEnd"
    (workspace / "AGENTS.md").write_text(text, encoding="utf-8")
    c = AgentsMdContributor()
    out = c.contribute_sync(
        _ctx(workspace_dir=workspace, heartbeat_enabled=False),
    )
    assert "HB" not in out


def test_agents_md_memory_injection(workspace: Path) -> None:
    (workspace / "AGENTS.md").write_text("Content.", encoding="utf-8")

    class _FakeMemMgr:
        def get_memory_prompt(self, lang):
            return f"Memory hint ({lang})"

    c = AgentsMdContributor()
    out = c.contribute_sync(
        _ctx(
            workspace_dir=workspace,
            memory_manager=_FakeMemMgr(),
            language="en",
        ),
    )
    assert "Content." in out
    assert "Memory hint (en)" in out


def test_agents_md_missing_file(workspace: Path) -> None:
    c = AgentsMdContributor()
    assert c.contribute_sync(_ctx(workspace_dir=workspace)) is None


def test_agents_md_no_workspace() -> None:
    c = AgentsMdContributor()
    assert c.contribute_sync(_ctx()) is None


# ---------------------------------------------------------------------------
# SoulMdContributor
# ---------------------------------------------------------------------------


def test_soul_md_basic(workspace: Path) -> None:
    (workspace / "SOUL.md").write_text("I am kind.", encoding="utf-8")
    c = SoulMdContributor()
    out = c.contribute_sync(_ctx(workspace_dir=workspace))
    assert out is not None
    assert out.startswith("# SOUL.md")
    assert "I am kind." in out


def test_soul_md_missing(workspace: Path) -> None:
    c = SoulMdContributor()
    assert c.contribute_sync(_ctx(workspace_dir=workspace)) is None


# ---------------------------------------------------------------------------
# ProfileMdContributor
# ---------------------------------------------------------------------------


def test_profile_md_basic(workspace: Path) -> None:
    (workspace / "PROFILE.md").write_text("User: Alice", encoding="utf-8")
    c = ProfileMdContributor()
    out = c.contribute_sync(_ctx(workspace_dir=workspace))
    assert out is not None
    assert out.startswith("# PROFILE.md")
    assert "User: Alice" in out


def test_profile_md_missing(workspace: Path) -> None:
    c = ProfileMdContributor()
    assert c.contribute_sync(_ctx(workspace_dir=workspace)) is None


# ---------------------------------------------------------------------------
# MultimodalHintContributor
# ---------------------------------------------------------------------------


def test_multimodal_hint_returns_string_or_none() -> None:
    c = MultimodalHintContributor()
    out = c.contribute_sync(_ctx())
    # When no model info is available, build_multimodal_hint returns "".
    assert out is None or isinstance(out, str)


# ---------------------------------------------------------------------------
# CodingModeContributor
# ---------------------------------------------------------------------------


def test_coding_mode_enabled(workspace: Path) -> None:
    agent_config = SimpleNamespace(
        id="test-agent",
        coding_mode=SimpleNamespace(enabled=True, project_dir="/tmp/proj"),
    )
    c = CodingModeContributor()
    out = c.contribute_sync(
        _ctx(workspace_dir=workspace, agent_config=agent_config),
    )
    assert out is not None
    assert "Coding Mode" in out
    assert "/tmp/proj" in out


def test_coding_mode_disabled() -> None:
    agent_config = SimpleNamespace(
        id="test-agent",
        coding_mode=SimpleNamespace(enabled=False, project_dir=None),
    )
    c = CodingModeContributor()
    assert c.contribute_sync(_ctx(agent_config=agent_config)) is None


def test_coding_mode_no_config() -> None:
    c = CodingModeContributor()
    assert c.contribute_sync(_ctx()) is None


# ---------------------------------------------------------------------------
# EnvContextContributor
# ---------------------------------------------------------------------------


def test_env_context_with_value() -> None:
    c = EnvContextContributor()
    out = c.contribute_sync(_ctx(env_context="==ENV=="))
    assert out == "==ENV=="


def test_env_context_none() -> None:
    c = EnvContextContributor()
    assert c.contribute_sync(_ctx()) is None


# ---------------------------------------------------------------------------
# build_default_prompt_manager
# ---------------------------------------------------------------------------


def test_build_default_prompt_manager_has_7_contributors() -> None:
    pm = build_default_prompt_manager()
    assert len(pm) == 7


def test_build_default_prompt_manager_priority_order() -> None:
    pm = build_default_prompt_manager()
    names = pm.names()
    assert names == [
        "agent_identity",
        "agents_md",
        "soul_md",
        "profile_md",
        "multimodal_hint",
        "coding_mode",
        "env_context",
    ]


def test_full_build_sync_with_files(workspace: Path) -> None:
    (workspace / "AGENTS.md").write_text("Agent rules.", encoding="utf-8")
    (workspace / "SOUL.md").write_text("Soul text.", encoding="utf-8")

    pm = build_default_prompt_manager()
    ctx = _ctx(
        workspace_dir=workspace,
        agent_id="a1",
        env_context="==ENV==",
    )
    prompt = pm.build_sync(ctx)

    assert "Your agent id is `a1`" in prompt
    assert "# AGENTS.md" in prompt
    assert "Agent rules." in prompt
    assert "# SOUL.md" in prompt
    assert "Soul text." in prompt
    assert "==ENV==" in prompt
    # Order: identity before agents_md before soul_md before env_context
    assert prompt.index("Agent Identity") < prompt.index("AGENTS.md")
    assert prompt.index("AGENTS.md") < prompt.index("SOUL.md")
    assert prompt.index("SOUL.md") < prompt.index("==ENV==")
