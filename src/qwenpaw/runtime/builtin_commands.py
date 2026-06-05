# -*- coding: utf-8 -*-
"""Built-in slash command adapters.

Wraps the four existing command mechanisms (daemon, control,
conversation, skill) as :class:`CommandSpec` instances registered
into a single :class:`SlashCommandRegistry`.  Each adapter reads
from :class:`HookContext` (``ctx.kernel``, ``ctx.agent``, etc.)
and delegates to the original handler.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .slash_command_registry import CommandSpec, SlashCommandRegistry

if TYPE_CHECKING:
    from agentscope.message import Msg

logger = logging.getLogger(__name__)


# ======================================================================
# Daemon command adapters
# ======================================================================


def _make_daemon_adapter(subcommand: str) -> CommandSpec:
    """Create a :class:`CommandSpec` for one daemon subcommand."""

    async def _handler(ctx: Any, args: str) -> "Msg | None":
        from ..app.runner.daemon_commands import (
            DaemonCommandHandlerMixin,
            DaemonContext,
        )
        from ..config.config import load_agent_config

        agent_id = getattr(ctx, "agent_id", None) or "default"
        kernel = getattr(ctx, "kernel", None)

        try:
            cfg = load_agent_config(agent_id)
            agent_name = cfg.name if cfg and cfg.name else "QwenPaw"
        except Exception:
            agent_name = "QwenPaw"

        daemon_ctx = DaemonContext(
            load_config_fn=lambda: load_agent_config(agent_id),
            memory_manager=getattr(kernel, "memory_manager", None),
            context_manager=getattr(
                kernel,
                "context_manager",
                None,
            ),
            manager=getattr(kernel, "_manager", None),
            agent_id=agent_id,
            session_id=getattr(ctx, "session_id", "") or "",
            agent_name=agent_name,
        )

        full_query = f"/{subcommand} {args}".strip()
        handler_mixin = DaemonCommandHandlerMixin()
        return await handler_mixin.handle_daemon_command(
            full_query,
            daemon_ctx,
        )

    return CommandSpec(
        name=subcommand,
        handler=_handler,
        category="daemon",
    )


def _make_daemon_compound_adapter() -> CommandSpec:
    """``/daemon <sub>`` compound entry.

    Delegates via ``parse_daemon_query``.
    """

    async def _handler(ctx: Any, args: str) -> "Msg | None":
        from ..app.runner.daemon_commands import (
            DaemonCommandHandlerMixin,
            DaemonContext,
            parse_daemon_query,
        )
        from ..config.config import load_agent_config

        full_query = f"/daemon {args}".strip()
        parsed = parse_daemon_query(full_query)
        if parsed is None:
            from agentscope.message import Msg, TextBlock

            return Msg(
                name="assistant",
                role="assistant",
                content=[
                    TextBlock(
                        type="text",
                        text="Unknown daemon command.",
                    ),
                ],
            )

        agent_id = getattr(ctx, "agent_id", None) or "default"
        kernel = getattr(ctx, "kernel", None)

        try:
            cfg = load_agent_config(agent_id)
            agent_name = cfg.name if cfg and cfg.name else "QwenPaw"
        except Exception:
            agent_name = "QwenPaw"

        daemon_ctx = DaemonContext(
            load_config_fn=lambda: load_agent_config(agent_id),
            memory_manager=getattr(
                kernel,
                "memory_manager",
                None,
            ),
            context_manager=getattr(
                kernel,
                "context_manager",
                None,
            ),
            manager=getattr(kernel, "_manager", None),
            agent_id=agent_id,
            session_id=getattr(ctx, "session_id", "") or "",
            agent_name=agent_name,
        )

        handler_mixin = DaemonCommandHandlerMixin()
        return await handler_mixin.handle_daemon_command(
            full_query,
            daemon_ctx,
        )

    return CommandSpec(
        name="daemon",
        handler=_handler,
        category="daemon",
    )


def _collect_daemon_specs() -> list[CommandSpec]:
    specs = [
        _make_daemon_adapter("restart"),
        _make_daemon_adapter("status"),
        _make_daemon_adapter("version"),
        _make_daemon_adapter("logs"),
    ]
    # reload-config has an underscore alias
    rc_spec = _make_daemon_adapter("reload-config")
    specs.append(
        CommandSpec(
            name=rc_spec.name,
            handler=rc_spec.handler,
            aliases=("reload_config",),
            category=rc_spec.category,
        ),
    )
    specs.append(_make_daemon_compound_adapter())
    return specs


# ======================================================================
# Control command adapters
# ======================================================================


def _make_control_adapter(
    handler: Any,
    command_name: str,
) -> CommandSpec:
    """Wrap a :class:`BaseControlCommandHandler` as
    a :class:`CommandSpec`.
    """

    async def _handler(ctx: Any, args: str) -> "Msg | None":
        from ..app.runner.control_commands import parse_args
        from ..app.runner.control_commands.base import ControlContext
        from agentscope.message import Msg, TextBlock

        kernel = getattr(ctx, "kernel", None)
        request = getattr(ctx, "request", None)

        if kernel is None:
            return Msg(
                name="assistant",
                role="assistant",
                content=[
                    TextBlock(
                        type="text",
                        text="**Error**\n\nControl command "
                        "unavailable (kernel not initialized)",
                    ),
                ],
            )

        channel = None
        channel_mgr = getattr(kernel, "channel_manager", None)
        if channel_mgr is not None:
            channel_id = getattr(request, "channel", None) or "console"
            try:
                channel = await channel_mgr.get_channel(
                    channel_id,
                )
            except Exception:
                pass

        full_query = (
            f"/{command_name} {args}".strip() if args else f"/{command_name}"
        )
        parsed_args = parse_args(
            full_query,
            f"/{command_name}",
        )

        ctrl_ctx = ControlContext(
            workspace=kernel,
            payload=request,
            channel=channel,
            session_id=getattr(ctx, "session_id", "") or "",
            user_id=(getattr(request, "user_id", "") if request else "") or "",
            agent_id=getattr(ctx, "agent_id", "") or "",
            args=parsed_args,
        )

        try:
            text = await handler.handle(ctrl_ctx)
        except Exception as e:
            logger.exception(
                "Control command failed: /%s",
                command_name,
            )
            text = f"**Command Failed**\n\n{e}"

        return Msg(
            name="assistant",
            role="assistant",
            content=[TextBlock(type="text", text=text)],
        )

    return CommandSpec(
        name=command_name,
        handler=_handler,
        category="control",
    )


def _collect_control_specs() -> list[CommandSpec]:
    from ..app.runner.control_commands import _COMMAND_REGISTRY

    specs = []
    seen_names: set[str] = set()
    for raw_name, handler in _COMMAND_REGISTRY.items():
        name = raw_name.lstrip("/")
        if name in seen_names:
            continue
        seen_names.add(name)
        specs.append(_make_control_adapter(handler, name))
    return specs


# ======================================================================
# Conversation command adapters
# ======================================================================

_CONVERSATION_COMMANDS = frozenset(
    {
        "compact",
        "new",
        "clear",
        "history",
        "compact_str",
        "summarize_status",
        "message",
        "dump_history",
        "load_history",
        "proactive",
        "plan",
    },
)


def _make_conversation_adapter(name: str) -> CommandSpec:
    """Wrap one conversation command from :class:`CommandHandler`."""

    async def _handler(ctx: Any, args: str) -> "Msg | None":
        agent = getattr(ctx, "agent", None)
        if agent is None:
            return None

        cmd_handler = getattr(agent, "command_handler", None)
        if cmd_handler is None:
            return None

        # /plan with arguments is NOT a command — fall through to model
        if name == "plan" and args.strip():
            return None

        full_query = f"/{name} {args}".strip() if args else f"/{name}"
        return await cmd_handler.handle_command(full_query)

    return CommandSpec(
        name=name,
        handler=_handler,
        category="conversation",
    )


def _collect_conversation_specs() -> list[CommandSpec]:
    return [
        _make_conversation_adapter(n) for n in sorted(_CONVERSATION_COMMANDS)
    ]


# ======================================================================
# Skill fallback handler
# ======================================================================


def _parse_skill_query(query: str) -> tuple[str, str] | None:
    """Parse ``/name [input]`` or ``/[name with spaces] [input]``."""
    stripped = query.strip()
    if not stripped.startswith("/"):
        return None
    rest = stripped[1:]
    if rest.startswith("["):
        close = rest.find("]")
        if close < 0:
            return None
        name = rest[1:close].strip().lower()
        user_input = rest[close + 1 :].strip()
        return (name, user_input) if name else None
    parts = rest.split(None, 1)
    if not parts:
        return None
    name = parts[0].lower()
    user_input = parts[1] if len(parts) > 1 else ""
    return (name, user_input) if name else None


# pylint: disable-next=too-many-return-statements
async def _skill_fallback_handler(
    raw_text: str,
    ctx: Any,
) -> "Msg | None":
    """Fallback handler for ``/<skill_name>`` dispatch."""
    from agentscope.message import Msg, TextBlock

    agent = getattr(ctx, "agent", None)
    msgs = getattr(ctx, "input_msgs", None)

    if agent is None:
        return None

    toolkit = getattr(agent, "toolkit", None)
    skills = getattr(toolkit, "_qp_skills", None) if toolkit else None
    if not skills:
        return None

    parsed = _parse_skill_query(raw_text)
    if not parsed:
        return None
    skill_name, user_input = parsed

    skill = next(
        (
            s
            for s in skills.values()
            if Path(s["dir"]).name.lower() == skill_name
        ),
        None,
    )
    if not skill:
        return None

    skill_dir = Path(skill["dir"])
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return None

    from ..agents.utils.file_handling import (
        read_text_file_with_encoding_fallback,
    )

    import frontmatter as fm

    raw = read_text_file_with_encoding_fallback(skill_md)
    post = fm.loads(raw)
    display_name = post.get("name") or skill_name

    if not user_input:
        desc = post.get("description") or "No description."
        return Msg(
            name=getattr(agent, "name", "assistant"),
            role="assistant",
            content=[
                TextBlock(
                    type="text",
                    text=(
                        f"**{skill_name}**\n\n"
                        f"- **command**: `/{skill_name} <input>` to invoke\n"
                        f"- **name**: {display_name}\n"
                        f"- **description**: {desc}\n"
                        f"- **path**: `{skill_dir}`"
                    ),
                ),
            ],
        )

    # Rewrite last message with skill body
    merged = (
        f"Use the [{display_name}] skill in "
        f"`{skill_dir}` to fulfill "
        f"user's task: {user_input}\n\n"
        f"{post.content}"
    )
    if msgs:
        last = msgs[-1]
        content = getattr(last, "content", None)
        if isinstance(content, list):
            for i, block in enumerate(content):
                btype = (
                    block.get("type")
                    if isinstance(block, dict)
                    else getattr(block, "type", None)
                )
                if btype == "text":
                    content[i] = TextBlock(type="text", text=merged)
                    return None
            content.insert(0, TextBlock(type="text", text=merged))
        elif isinstance(content, str):
            last.content = merged
    return None


# ======================================================================
# Factory
# ======================================================================


def build_default_command_registry() -> SlashCommandRegistry:
    """Create a :class:`SlashCommandRegistry` with all built-in commands.

    Returns a fully populated registry covering daemon, control,
    conversation, and skill-fallback dispatch.
    """
    reg = SlashCommandRegistry()

    for spec in _collect_conversation_specs():
        reg.register(spec)
    for spec in _collect_daemon_specs():
        reg.register(spec)
    for spec in _collect_control_specs():
        reg.register(spec)

    reg.register_fallback(_skill_fallback_handler)
    return reg


__all__ = [
    "build_default_command_registry",
]
