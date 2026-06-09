# -*- coding: utf-8 -*-
"""Per-request agent assembly.

:class:`AgentBuilder` fully constructs a :class:`QwenPawAgent` for each
request.  It draws from the per-Kernel :class:`ToolRegistry`,
:class:`PromptManager`, and model factory to produce all dependencies
(toolkit, system prompt, model, middlewares) and injects them into the
agent constructor.
"""

from __future__ import annotations

from typing import Any, Iterable

from .tool_guard import GuardedFunctionTool
from .tool_registry import ToolRegistry


class AgentBuilder:
    """Compose an agent from a per-Kernel :class:`ToolRegistry`.

    ``tool_registry`` is the per-Kernel registry that lifespan startup
    populated via ``discover_builtin_tool_funcs``.  ``app_services``
    provides cross-Kernel shared services (TaskTracker, etc.).
    """

    def __init__(
        self,
        tool_registry: ToolRegistry,
        app_services: Any | None = None,
    ) -> None:
        self._tool_registry = tool_registry
        self._app_services = app_services

    # ------------------------------------------------------------------ public
    def build_toolkit(
        self,
        agent_config: Any,
        *,
        agent_id: str | None = None,
        request_context: dict[str, str] | None = None,
        active_modes: Iterable[str] | None = None,
        effective_skills: Iterable[str] | None = None,
        enabled_features: Iterable[str] | None = None,
        extra_tools: Iterable[Any] | None = None,
        memory_tools: Iterable[Any] | None = None,
        mcp_clients: list[Any] | None = None,
    ) -> Any:
        """Build a populated ``Toolkit`` for one agent invocation.

        Selection mirrors the legacy ``_create_toolkit``:

        * ``agent_config.tools.builtin_tools[name].enabled`` is bridged to
          the registry's ``allowed`` / ``denied`` sets (see
          :meth:`_resolve_config_gates`).
        * ``extra_tools`` are appended verbatim — used for dynamic tools
          like Coding Mode's LSP wrapper that can't be statically
          decorated.
        * ``memory_tools`` are wrapped in :class:`GuardedFunctionTool` so
          the memory manager's helpers respect the same approval flow.
        """
        from agentscope.tool import Toolkit

        allowed, denied = self._resolve_config_gates(agent_config)
        descs = self._tool_registry.filter(
            active_modes=set(active_modes or ()),
            active_skills=set(effective_skills or ()),
            enabled_features=set(enabled_features or ()),
            allowed=allowed,
            denied=denied,
        )

        tools: list[Any] = [
            GuardedFunctionTool(
                d.func,
                agent_id=agent_id,
                request_context=request_context,
            )
            for d in descs
        ]

        if extra_tools:
            tools.extend(extra_tools)

        if memory_tools:
            for fn in memory_tools:
                tools.append(
                    GuardedFunctionTool(
                        fn,
                        agent_id=agent_id,
                        request_context=request_context,
                    ),
                )

        return Toolkit(tools=tools, mcps=mcp_clients or None)

    # ----------------------------------------------------------------- helpers
    def _resolve_config_gates(
        self,
        agent_config: Any,
    ) -> tuple[set[str] | None, set[str]]:
        """Translate ``agent_config.tools.builtin_tools`` to (allowed, denied).

        The legacy semantic was: hardcoded tools default-on unless the
        config explicitly disables them; plugin tools default-off unless
        the config explicitly enables them. The registry exposes the
        former via ``enabled_by_default=True``; this method covers the
        latter by widening ``allowed`` to ``defaults ∪ explicit_enabled``
        whenever the user opted in at least one plugin tool. When no
        plugin is opted in, ``allowed`` stays ``None`` so the filter
        doesn't restrict the default-enabled set.
        """
        cfg = (
            getattr(
                getattr(agent_config, "tools", None),
                "builtin_tools",
                None,
            )
            or {}
        )
        denied = {
            n for n, c in cfg.items() if getattr(c, "enabled", True) is False
        }
        explicit_enabled = {
            n for n, c in cfg.items() if getattr(c, "enabled", True)
        }

        defaults = self._tool_registry.default_enabled_names()
        plugin_opt_ins = explicit_enabled - defaults
        if plugin_opt_ins:
            return defaults | explicit_enabled, denied
        return None, denied

    # ----------------------------------------------------------------- build

    async def build(self, ctx: Any) -> Any:
        """Construct a fully-wired :class:`QwenPawAgent` for one request.

        Integrates all per-Kernel registries: ToolRegistry (toolkit),
        PromptManager (system prompt), model factory, and middlewares.
        The agent receives all dependencies externally — it does not
        build any of them internally.
        """
        from agentscope.agent import ReActConfig

        from ..agents.react_agent import QwenPawAgent
        from ..agents.skill_system import (
            ensure_skills_initialized,
            resolve_effective_skills,
        )
        from ..config.config import load_agent_config
        from ..constant import WORKING_DIR
        from ..providers.provider_manager import ProviderManager

        import logging

        _logger = logging.getLogger(__name__)

        agent_id = getattr(ctx, "agent_id", None) or "default"
        agent_config = load_agent_config(agent_id)
        ctx.agent_config = agent_config

        # Validate model availability.
        active = agent_config.active_model
        if not (active and active.provider_id and active.model):
            active = ProviderManager.get_instance().get_active_model()
        if active is None or not active.provider_id or not active.model:
            raise RuntimeError(
                "No active model configured; pick one in the UI",
            )

        workspace_dir = getattr(ctx, "workspace_dir", None)

        # Resolve skills.
        ensure_skills_initialized(workspace_dir or WORKING_DIR)
        request_context = self._build_request_context(ctx)
        channel_name = request_context.get("channel", "console")
        try:
            effective_skills = resolve_effective_skills(
                workspace_dir or WORKING_DIR,
                channel_name,
            )
        except Exception:
            effective_skills = []

        # Compute active modes.
        active_modes: set[str] = set()
        kernel = getattr(ctx, "kernel", None)
        if kernel is not None:
            plugins = getattr(kernel, "plugins", None)
            if plugins is not None:
                active_modes = plugins.active_mode_names(ctx)

        # MCP clients (async).
        mcp_clients = await self._get_mcp_clients_async(ctx)

        # Toolkit.
        extra_tools = self._collect_coding_mode_tools(
            agent_config,
            workspace_dir,
            agent_id,
            request_context,
        )
        toolkit = self.build_toolkit(
            agent_config,
            agent_id=agent_id,
            request_context=request_context,
            active_modes=active_modes,
            effective_skills=effective_skills,
            extra_tools=extra_tools,
            mcp_clients=mcp_clients,
        )

        # System prompt.
        sys_prompt = self.build_prompt(ctx, agent_config)

        # Model + formatter.
        model, _formatter = self.build_model(agent_config)

        # Middlewares (only context_manager).
        middlewares = self._build_middlewares(ctx, agent_config)

        running_config = agent_config.running

        agent = QwenPawAgent(
            name=agent_config.name or "QwenPaw",
            model=model,
            system_prompt=sys_prompt,
            toolkit=toolkit,
            react_config=ReActConfig(max_iters=running_config.max_iters),
            middlewares=middlewares,
            agent_config=agent_config,
            workspace_dir=workspace_dir,
            request_context=request_context,
            memory_manager=self._get_memory_manager(ctx),
            context_manager=self._get_context_manager(ctx),
            mcp_clients=mcp_clients,
            effective_skills=effective_skills,
        )

        # Load session state if SessionLoadHook populated it.
        if ctx.session_state:
            agent.load_state_dict(ctx.session_state)

        _logger.info(
            "builder: built agent for session=%s agent=%s"
            " model=%s/%s tools=%d",
            getattr(ctx, "session_id", ""),
            agent_id,
            active.provider_id,
            active.model,
            len(agent.toolkit.tool_groups[0].tools),
        )
        return agent

    def build_prompt(self, ctx: Any, agent_config: Any = None) -> str:
        """Build the system prompt via the per-Kernel
        :class:`PromptManager`.
        """
        from types import SimpleNamespace
        from ..constant import WORKING_DIR

        if agent_config is None:
            from ..config.config import load_agent_config

            agent_config = load_agent_config(
                getattr(ctx, "agent_id", "default"),
            )

        workspace_dir = getattr(ctx, "workspace_dir", None) or WORKING_DIR

        heartbeat_enabled = False
        hb = getattr(agent_config, "heartbeat", None)
        if hb is not None:
            heartbeat_enabled = getattr(hb, "enabled", False)

        prompt_ctx = SimpleNamespace(
            workspace_dir=workspace_dir,
            agent_id=getattr(ctx, "agent_id", None),
            extras={
                "language": agent_config.language,
                "heartbeat_enabled": heartbeat_enabled,
                "memory_manager": self._get_memory_manager(ctx),
                "env_context": self._build_env_context(ctx, agent_config),
                "agent_config": agent_config,
            },
        )

        kernel = getattr(ctx, "kernel", None)
        if kernel is not None:
            plugins = getattr(kernel, "plugins", None)
            pm = getattr(plugins, "prompt_manager", None) if plugins else None
            if pm is not None and len(pm) > 0:
                return pm.build_sync(prompt_ctx)

        from .prompt_contributors import build_default_prompt_manager

        return build_default_prompt_manager().build_sync(prompt_ctx)

    def build_model(self, agent_config: Any) -> tuple[Any, Any]:
        """Create model and formatter using the factory method."""
        from ..agents.model_factory import create_model_and_formatter

        model, formatter = create_model_and_formatter(
            agent_id=agent_config.id,
        )
        if formatter is not None:
            innermost = model
            # pylint: disable=protected-access
            while hasattr(innermost, "_inner"):
                innermost = innermost._inner
            while hasattr(innermost, "_model"):
                innermost = innermost._model
            # pylint: enable=protected-access
            if hasattr(innermost, "formatter"):
                innermost.formatter = formatter
        return model, formatter

    # ------------------------------------------------------- helpers

    @staticmethod
    def _build_request_context(ctx: Any) -> dict[str, str]:
        request = getattr(ctx, "request", None)
        rc: dict[str, str] = {
            "session_id": getattr(ctx, "session_id", "") or "",
            "agent_id": getattr(ctx, "agent_id", "") or "",
            "channel": (
                (getattr(request, "channel", None) or "") if request else ""
            ),
            "user_id": (
                (getattr(request, "user_id", None) or "") if request else ""
            ),
            "root_session_id": getattr(ctx, "root_session_id", "") or "",
            "root_agent_id": getattr(ctx, "root_agent_id", "") or "",
        }
        app_services = getattr(ctx, "app_services", None)
        if app_services is not None:
            rc["approval_coordinator"] = getattr(
                app_services,
                "approval_coordinator",
                None,
            )
            rc["tool_coordinator"] = getattr(
                app_services,
                "tool_coordinator",
                None,
            )
        _channel_meta = (
            getattr(request, "channel_meta", None) if request else None
        )
        if isinstance(_channel_meta, dict):
            user_name = _channel_meta.get("user_name")
            if user_name:
                rc["user_name"] = user_name
        _payload_ctx = (
            getattr(request, "request_context", None) if request else None
        )
        if isinstance(_payload_ctx, dict):
            rc.update(_payload_ctx)
        return rc

    @staticmethod
    def _build_env_context(ctx: Any, agent_config: Any) -> str:
        import os
        import sys
        from ..app.runner.utils import build_env_context
        from ..constant import WORKING_DIR

        workspace_dir = getattr(ctx, "workspace_dir", None)
        ws = str(workspace_dir) if workspace_dir else str(WORKING_DIR)

        _cm = getattr(agent_config, "coding_mode", None)
        _project_dir = (
            _cm.project_dir
            if _cm and getattr(_cm, "project_dir", None)
            else None
        )
        _configured_shell = getattr(
            getattr(agent_config, "running", None),
            "shell_command_executable",
            None,
        )
        _default_shell = (
            _configured_shell
            or os.environ.get("SHELL")
            or ("cmd.exe" if sys.platform == "win32" else "/bin/sh")
        )
        request = getattr(ctx, "request", None)
        return build_env_context(
            session_id=getattr(ctx, "session_id", ""),
            user_id=(getattr(request, "user_id", None) if request else None),
            user_name=None,
            channel=(getattr(request, "channel", None) if request else None),
            working_dir=ws,
            default_shell=_default_shell,
            project_dir=_project_dir,
        )

    @staticmethod
    def _collect_coding_mode_tools(
        agent_config: Any,
        workspace_dir: Any,
        agent_id: str,
        request_context: dict[str, str],
    ) -> list[Any]:
        import logging

        _logger = logging.getLogger(__name__)

        cm = getattr(agent_config, "coding_mode", None)
        if cm is None or not getattr(cm, "enabled", False):
            return []

        from ..agents.coding_mode_mixin import CodingModeMixin

        # Reuse the mixin's static tool-collection logic.
        mixin = CodingModeMixin.__new__(CodingModeMixin)
        mixin._agent_config = agent_config  # pylint: disable=protected-access
        # pylint: disable=protected-access
        mixin._workspace_dir = workspace_dir
        try:
            return mixin._collect_coding_mode_tools(
                agent_id=agent_id,
                request_context=request_context,
            )
            # pylint: enable=protected-access
        except Exception as exc:
            _logger.warning("Failed to collect Coding Mode tools: %s", exc)
            return []

    @staticmethod
    def _get_memory_manager(ctx: Any) -> Any:
        kernel = getattr(ctx, "kernel", None)
        if kernel is not None:
            return getattr(kernel, "memory_manager", None)
        return None

    @staticmethod
    def _get_context_manager(ctx: Any) -> Any:
        kernel = getattr(ctx, "kernel", None)
        if kernel is not None:
            return getattr(kernel, "context_manager", None)
        return None

    @staticmethod
    async def _get_mcp_clients_async(ctx: Any) -> list[Any] | None:
        kernel = getattr(ctx, "kernel", None)
        if kernel is None:
            return None
        mcp_mgr = getattr(kernel, "mcp_manager", None)
        if mcp_mgr is None:
            return None
        try:
            return await mcp_mgr.get_clients()
        except Exception:
            return None

    @staticmethod
    def _build_middlewares(
        ctx: Any,
        agent_config: Any,
    ) -> list[Any]:  # noqa: ARG004
        """Build middleware list — only context_manager remains.

        ContextVars, bootstrap injection, skill env, and file/media
        processing are now handled by lifecycle hooks.
        """
        del agent_config  # reserved for future mode-specific middleware
        mws: list[Any] = []
        context_manager = AgentBuilder._get_context_manager(ctx)
        if context_manager is not None:
            mws.append(context_manager)
        return mws


__all__ = ["AgentBuilder"]
