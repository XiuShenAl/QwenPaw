# -*- coding: utf-8 -*-
"""Unit tests for console background chat-task timeout handling."""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.routers import console as console_mod
from qwenpaw.app.routers.console import (
    _background_task_cancel_error,
    _resolve_effective_stream_task_timeout,
)
from qwenpaw.app.task_tracker import TaskTracker
from qwenpaw.constant import DEFAULT_STREAM_TASK_TIMEOUT_SECONDS


def test_resolve_timeout_omitted_uses_default() -> None:
    assert (
        _resolve_effective_stream_task_timeout(None)
        == DEFAULT_STREAM_TASK_TIMEOUT_SECONDS
    )


def test_resolve_timeout_accepts_positive_number_and_string() -> None:
    assert _resolve_effective_stream_task_timeout(30) == 30
    assert _resolve_effective_stream_task_timeout(30.9) == 30
    assert _resolve_effective_stream_task_timeout("1800") == 1800


@pytest.mark.parametrize(
    "bad",
    ["abc", "", "null", True, False, 0, -1, 0.5, "0", "-3", float("nan")],
)
def test_resolve_timeout_rejects_invalid(bad) -> None:
    with pytest.raises(ValueError) as exc_info:
        _resolve_effective_stream_task_timeout(bad)
    message = str(exc_info.value)
    assert "timeout" in message
    assert "got" in message


def test_background_cancel_error_distinguishes_timeout() -> None:
    timed_out = _background_task_cancel_error(
        timed_out=True,
        timeout_seconds=30,
    )
    assert timed_out["code"] == "timeout"
    assert timed_out["message"] == "Task timed out after 30s"

    cancelled = _background_task_cancel_error(
        timed_out=False,
        timeout_seconds=30,
    )
    assert cancelled == {"message": "Task cancelled"}


async def test_timeout_guard_marks_timeout_before_cancel() -> None:
    """Mirrors console `_timeout_guard` + `_run` cancel handling."""
    timed_out = False
    captured: dict = {}

    async def _run() -> None:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            captured["error"] = _background_task_cancel_error(
                timed_out=timed_out,
                timeout_seconds=1,
            )

    atask = asyncio.create_task(_run())

    async def _timeout_guard() -> None:
        nonlocal timed_out
        await asyncio.sleep(0.01)
        if not atask.done():
            timed_out = True
            atask.cancel()

    await asyncio.gather(atask, _timeout_guard(), return_exceptions=True)
    assert captured["error"]["code"] == "timeout"
    assert captured["error"]["message"] == "Task timed out after 1s"


@pytest.fixture
def console_workspace(workspace_mock, monkeypatch):
    """Workspace with console channel + chat manager for /chat/task."""
    console_channel = MagicMock(name="ConsoleChannel")
    console_channel.resolve_session_id = MagicMock(
        return_value="console:default",
    )

    async def _stream_one(_payload):
        # Complete immediately so TestClient does not leave hung tasks.
        # Empty async generator: zero iterations.
        for _ in ():
            yield ""

    console_channel.stream_one = _stream_one
    workspace_mock.channel_manager.get_channel = AsyncMock(
        return_value=console_channel,
    )
    workspace_mock.console_channel = console_channel

    chat = MagicMock(name="ChatSpec")
    chat.id = "chat-1"
    chat.name = "New Chat"
    chat.meta = {}
    workspace_mock.chat_manager = MagicMock(name="ChatManager")
    workspace_mock.chat_manager.get_or_create_chat = AsyncMock(
        return_value=chat,
    )
    workspace_mock.task_tracker = TaskTracker()
    workspace_mock.agent_id = "default"
    workspace_mock.workspace_dir = "/tmp/qwenpaw-test-workspace"

    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _agent_id: MagicMock(project_dir=None),
    )
    monkeypatch.setattr(
        "qwenpaw.services.project_directory.resolve_effective_project_dir",
        lambda *args, **kwargs: ("/tmp/project", "test"),
    )
    monkeypatch.setattr(
        "qwenpaw.services.project_directory.session_project_dir",
        lambda _meta: None,
    )
    monkeypatch.setattr(
        console_mod,
        "_apply_session_project_dir",
        AsyncMock(side_effect=lambda _ws, chat_obj, _payload: chat_obj),
    )
    return workspace_mock


@pytest.fixture
def app(manager_mock, console_workspace) -> FastAPI:
    application = FastAPI()
    application.state.multi_agent_manager = manager_mock
    application.include_router(console_mod.router, prefix="/api")
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _chat_task_body(**extra):
    body = {
        "channel": "console",
        "user_id": "default",
        "session_id": "console:default",
        "input": [
            {
                "role": "user",
                "type": "message",
                "content": [{"type": "text", "text": "hello"}],
            },
        ],
    }
    body.update(extra)
    return body


def test_chat_task_omitted_timeout_returns_default(
    client,
    console_workspace,
):
    response = client.post("/api/console/chat/task", json=_chat_task_body())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["timeout"] == DEFAULT_STREAM_TASK_TIMEOUT_SECONDS
    assert body["task_id"].startswith("task-")


def test_chat_task_explicit_timeout_echoed(
    client,
    console_workspace,
):
    response = client.post(
        "/api/console/chat/task",
        json=_chat_task_body(timeout=30),
    )
    assert response.status_code == 200, response.text
    assert response.json()["timeout"] == 30


@pytest.mark.parametrize("bad_timeout", ["abc", 0, -1, True])
def test_chat_task_invalid_timeout_returns_400(
    client,
    console_workspace,
    bad_timeout,
):
    response = client.post(
        "/api/console/chat/task",
        json=_chat_task_body(timeout=bad_timeout),
    )
    assert response.status_code == 400, response.text
    assert "timeout" in response.json()["detail"]
