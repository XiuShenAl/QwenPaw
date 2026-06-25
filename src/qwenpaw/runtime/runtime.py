# -*- coding: utf-8 -*-
"""8-phase request orchestration.

Delegates to:

* ``Envelope``       — SSE state machine
* ``AgentBuilder``   — per-request agent assembly
* ``AgentExecutor``  — heartbeat-wrapped reply stream

All insertable features live in ``LifecycleHook`` / ``AgentMode``
instances registered in the per-workspace ``HookRegistry``.  The two
fixed steps (build + execute) are the only agent-touching code.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator

from .builder import AgentBuilder
from .envelope import Envelope
from .executor import AgentExecutor
from .hooks import HookAction, HookContext
from .message_convert import _get_last_user_text, _request_input_to_msgs
from .phases import Phase

logger = logging.getLogger(__name__)


class Runtime:
    """Per-workspace request orchestrator.

    One ``Runtime`` instance per ``Workspace``.  ``run()`` is called once
    per ``AgentRequest`` and yields SSE envelope objects identical to
    what the legacy ``Runner.stream_query`` produced.
    """

    def __init__(
        self,
        *,
        workspace: Any,
        app_services: Any,
    ) -> None:
        self.workspace = workspace
        self.app_services = app_services

    async def run(  # pylint: disable=too-many-branches,too-many-statements
        self,
        request: Any,
    ) -> AsyncGenerator[Any, None]:
        """8-phase lifecycle orchestration."""
        request = self._normalize(request)
        ctx = self._build_context(request)
        hooks = self.workspace.plugins.hook_registry

        envelope = Envelope(session_id=ctx.session_id)
        skip_agent = False

        try:
            # --- [phase 1] PRE_DISPATCH ---
            r = await hooks.run(Phase.PRE_DISPATCH, ctx)
            if r.action == HookAction.SHORT_CIRCUIT:
                async for ev in envelope.from_msg(r.payload):
                    yield ev
                return
            if r.action == HookAction.SKIP_AGENT:
                skip_agent = True

            # --- [fixed 1] slash command dispatch ---
            text = _get_last_user_text(ctx.input_msgs)
            cmd_registry = self.workspace.plugins.slash_command_registry
            cmd_msg = await cmd_registry.dispatch(text or "", ctx)
            if cmd_msg is not None:
                async for ev in envelope.from_msg(cmd_msg):
                    yield ev
                skip_agent = True
            else:
                # --- [phase 2] POST_DISPATCH ---
                r = await hooks.run(Phase.POST_DISPATCH, ctx)
                if r.action == HookAction.SHORT_CIRCUIT:
                    async for ev in envelope.from_msg(r.payload):
                        yield ev
                    skip_agent = True
                elif r.action == HookAction.SKIP_AGENT:
                    skip_agent = True

            if not skip_agent:
                # --- [phase 3] PRE_AGENT_BUILD ---
                r = await hooks.run(Phase.PRE_AGENT_BUILD, ctx)
                if r.action == HookAction.SHORT_CIRCUIT:
                    async for ev in envelope.from_msg(r.payload):
                        yield ev
                    skip_agent = True
                elif r.action == HookAction.SKIP_AGENT:
                    skip_agent = True

            if not skip_agent:
                # --- [fixed 2] build agent ---
                builder = AgentBuilder(
                    app_services=self.app_services,
                )
                ctx.agent = await builder.build(ctx)

                # --- [phase 4] POST_AGENT_BUILD ---
                await hooks.run(Phase.POST_AGENT_BUILD, ctx)

                # --- [phase 5] PRE_EXECUTE ---
                r = await hooks.run(Phase.PRE_EXECUTE, ctx)
                if r.action == HookAction.SHORT_CIRCUIT:
                    async for ev in envelope.from_msg(r.payload):
                        yield ev
                    skip_agent = True
                elif r.action == HookAction.SKIP_AGENT:
                    skip_agent = True

            if not skip_agent:
                # --- [fixed 3] execute agent ---
                # Check for mission Phase 2 execution override
                _mission_exec = (ctx.extras or {}).get("_mission_phase2")
                if _mission_exec:
                    async for ev in self._run_mission_phase2(
                        ctx,
                        envelope,
                        _mission_exec,
                    ):
                        yield ev
                else:
                    async for ev in envelope.emit_response_created():
                        yield ev
                    executor = AgentExecutor(ctx.agent, envelope)
                    async for ev in executor.run(ctx.input_msgs):
                        yield ev

            # --- [phase 6] POST_RESPONSE ---
            await hooks.run(Phase.POST_RESPONSE, ctx)

            # Finalize envelope (complete message + response).
            async for ev in envelope.finalize():
                yield ev

        except (asyncio.CancelledError, KeyboardInterrupt) as e:
            ctx.error = e
            await hooks.run(Phase.ON_ERROR, ctx)
            async for ev in envelope.cancel_envelope():
                yield ev
            raise
        except BaseException as e:
            ctx.error = e
            logger.error(
                "runtime: unhandled error session=%s: %s",
                getattr(ctx, "session_id", ""),
                e,
                exc_info=True,
            )
            await hooks.run(Phase.ON_ERROR, ctx)
            err_text = ctx.extras.get(
                "_error_text",
                str(e) or e.__class__.__name__,
            )
            async for ev in envelope.error_envelope(err_text):
                yield ev
            raise
        finally:
            # Close agent first so governor can flush audit log and persist
            # policy before downstream FINALLY hooks observe the context.
            # See ``QwenPawAgent.close`` (agents/react_agent.py).
            agent = getattr(ctx, "agent", None)
            if agent is not None and hasattr(agent, "close"):
                try:
                    await agent.close()
                except Exception:  # pylint: disable=broad-except
                    logger.warning(
                        "runtime: agent.close() failed session=%s",
                        getattr(ctx, "session_id", ""),
                        exc_info=True,
                    )
            await hooks.run(Phase.FINALLY, ctx)

    # ----------------------------------------------------------------- helpers

    async def _run_mission_phase2(
        self,
        ctx: Any,
        envelope: Any,
        mission_exec: dict,
    ) -> AsyncGenerator[Any, None]:
        """Drive mission Phase 2 iteration loop as alternate executor.

        Note: run_mission_phase2 uses agent._reply() internally
        (non-streaming). Each iteration's result is emitted as a
        complete Msg. A follow-up should migrate to reply_stream
        for token-level streaming.
        """
        # TODO(streaming): Replace agent._reply() with reply_stream in
        # mission_runner.py to enable token-level streaming for Phase 2.
        from ..agents.mission.mission_runner import run_mission_phase2
        from ..agents.mission.state import read_loop_config
        from ..agents.mission.constants import DEFAULT_MAX_ITERATIONS

        loop_dir = Path(mission_exec["loop_dir"])
        max_iterations = mission_exec.get(
            "max_iterations",
            DEFAULT_MAX_ITERATIONS,
        )
        agent_id = getattr(ctx, "agent_id", "default")

        try:
            async for ev in envelope.emit_response_created():
                yield ev

            async for msg, _is_last in run_mission_phase2(
                agent=ctx.agent,
                msgs=ctx.input_msgs,
                loop_dir=loop_dir,
                max_iterations=max_iterations,
                agent_id=agent_id,
            ):
                async for ev in envelope.from_msg(msg):
                    yield ev
        finally:
            session_state = ctx.session_state or {}
            cfg = read_loop_config(loop_dir)
            phase = cfg.get("current_phase", "")
            if phase in ("completed", "max_iterations_reached"):
                session_state["mission_active"] = False
            session_state["mission_current_phase"] = phase
            ctx.session_state = session_state

    @staticmethod
    def _normalize(request: Any) -> Any:
        from ..schemas import AgentRequest

        if isinstance(request, dict):
            request = AgentRequest(**request)
        if not getattr(request, "session_id", None):
            request.session_id = uuid.uuid4().hex
        if not getattr(request, "user_id", None):
            request.user_id = request.session_id
        return request

    def _build_context(self, request: Any) -> HookContext:
        workspace_dir = getattr(self.workspace, "workspace_dir", None)
        # Prefer the workspace's resolved agent id over a bare "default", so an
        # agent selected by header (no body agent_id) loads its own config.
        agent_id = (
            getattr(request, "agent_id", None)
            or getattr(self.workspace, "agent_id", None)
            or "default"
        )
        session_id = request.session_id
        root_session_id = getattr(request, "root_session_id", "") or session_id
        root_agent_id = getattr(request, "root_agent_id", "") or agent_id

        return HookContext(
            request=request,
            session_id=session_id,
            agent_id=agent_id,
            root_session_id=root_session_id,
            root_agent_id=root_agent_id,
            workspace_dir=workspace_dir,
            workspace=self.workspace,
            app_services=self.app_services,
            input_msgs=_request_input_to_msgs(request.input),
        )


__all__ = ["Runtime"]
