# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name,unused-argument
"""Plugin failure recovery and workspace replacement regressions."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.app.channels.manager import ChannelManager
from qwenpaw.app.workspace.workspace_plugins import WorkspacePlugins
from qwenpaw.plugins.api import PluginApi
from qwenpaw.plugins.architecture import PluginManifest, PluginRecord
from qwenpaw.plugins.lifecycle import PluginState, UnloadMode
from qwenpaw.plugins.loader import PluginLoader
from qwenpaw.plugins.provision import load_inventory, record_escape_provision
from qwenpaw.plugins.registry import PluginRegistry
from qwenpaw.plugins.workspace_projector import WorkspaceProjector


@pytest.fixture
def registry(tmp_path, monkeypatch):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    monkeypatch.setattr(PluginRegistry, "_instance", None)
    return PluginRegistry()


def workspace():
    return SimpleNamespace(agent_id="same-agent", plugins=WorkspacePlugins())


@pytest.mark.asyncio
async def test_replacement_workspace_gets_its_own_binding(registry):
    old, new = workspace(), workspace()
    live = [old]
    registry.projector = WorkspaceProjector(lambda: live)
    loader = PluginLoader([])
    api = PluginApi("replacement", {}, {"id": "replacement"})
    api.set_registry(registry)
    inst = loader.lifecycle.ensure_instance("replacement")
    api.bind_instance(inst)
    api.register_slash_command("hello", lambda *_: None)
    await registry.projector.project("slash_command", "hello", "replacement")
    # Reload candidates are set up before replacing the current workspace.
    await registry.projector.project_one(
        new,
        "slash_command",
        "hello",
        "replacement",
    )
    assert new.plugins.slash_command_registry.resolve("/hello") is not None
    assert old.plugins.slash_command_registry.resolve("/hello") is not None
    live[:] = [new]
    await inst.dispose(UnloadMode.UNLOAD)
    assert new.plugins.slash_command_registry.resolve("/hello") is None
    assert old.plugins.slash_command_registry.resolve("/hello") is None


@pytest.mark.asyncio
async def test_failed_mode_cleanup_retains_binding_for_retry(registry):
    ws = workspace()
    registry.projector = WorkspaceProjector(lambda: [ws])
    loader = PluginLoader([])
    inst = loader.lifecycle.ensure_instance("mode-test")
    api = PluginApi("mode-test", {}, {"id": "mode-test"})
    api.set_registry(registry)
    api.bind_instance(inst)
    calls = []

    class Mode:
        name = "retryable"

        def setup(self, _):
            pass

        def teardown(self, _):
            calls.append("stop")
            if len(calls) == 1:
                raise RuntimeError("connection still open")

    api.register_mode(Mode)
    await registry.projector.project("mode", "retryable", "mode-test")
    report = await inst.dispose(UnloadMode.UNLOAD)
    assert not report.quiescent
    assert report.needs_restart
    assert inst.state is PluginState.FAILED
    assert len(ws.plugins.modes) == 1
    report = await inst.dispose(UnloadMode.UNLOAD)
    assert report.quiescent
    assert not ws.plugins.modes


@pytest.mark.asyncio
@pytest.mark.parametrize("cancelled", [False, True])
async def test_partial_channel_start_keeps_handle_until_stopped(
    monkeypatch,
    cancelled,
):
    connected = []
    started = asyncio.Event()

    async def start():
        connected.append(True)
        started.set()
        if cancelled:
            await asyncio.Event().wait()
        raise RuntimeError("start failed")

    ch = SimpleNamespace(
        channel="partial",
        uses_manager_queue=False,
        start=start,
        stop=AsyncMock(side_effect=RuntimeError("stop failed")),
        set_enqueue=lambda _: None,
    )
    monkeypatch.setattr(
        "qwenpaw.app.channels.manager.instantiate_channel",
        lambda *a, **k: ch,
    )
    manager = ChannelManager([])
    manager._process = lambda *_: None
    task = asyncio.create_task(manager.start_one("partial", object()))
    await started.wait()
    if cancelled:
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancelled else RuntimeError):
        await task
    assert connected
    assert await manager.get_channel("partial") is ch
    ch.stop.side_effect = None
    assert (await manager.stop_one("partial")).stopped
    assert await manager.get_channel("partial") is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ref",
    [None, "missing_module:cleanup", "cleanup:missing", "cleanup:cleanup"],
)
async def test_uninstall_unresolved_provisions_keeps_retry_information(
    tmp_path,
    registry,
    ref,
):
    root = tmp_path / "plugins" / "disk-plugin"
    root.mkdir(parents=True)
    (root / "plugin.json").write_text(
        json.dumps({"id": "disk-plugin", "version": "1.0.0", "name": "Disk"}),
    )
    (root / "cleanup.py").write_text(
        "def cleanup():\n    raise RuntimeError('resource busy')\n",
    )
    resource = tmp_path / "external-resource"
    resource.write_text("still owned")
    record_escape_provision("disk-plugin", "external", teardown_ref=ref)
    loader = PluginLoader([tmp_path / "plugins"])
    report = await loader.unload_plugin(
        "disk-plugin",
        mode=UnloadMode.UNINSTALL,
    )
    assert not report.clean
    assert not report.quiescent
    assert report.errors
    assert root.exists()
    assert resource.exists()
    assert load_inventory("disk-plugin")["provisions"]


@pytest.mark.asyncio
async def test_memory_config_rejected_before_any_teardown(
    tmp_path,
    registry,
    monkeypatch,
):
    from qwenpaw.agents.memory.base_memory_manager import MemoryBackendRegistry
    from qwenpaw import memory

    isolated = MemoryBackendRegistry()
    monkeypatch.setattr(memory, "memory_registry", isolated)
    # The guard reads the registry exposed by qwenpaw.memory.
    isolated.register_backend(
        backend_id="selected",
        factory=type("Factory", (), {}),
        plugin_id="memory-plugin",
        label="Selected",
    )
    ws = workspace()
    ws._config = SimpleNamespace(
        running=SimpleNamespace(memory_manager_backend="selected"),
    )
    registry.set_workspace_manager(SimpleNamespace(agents={ws.agent_id: ws}))
    loader = PluginLoader([])
    inst = loader.lifecycle.ensure_instance("memory-plugin")
    closed = []
    inst.record_runtime("connection", lambda: closed.append(True))
    manifest = PluginManifest.from_dict(
        {"id": "memory-plugin", "version": "1.0.0", "name": "Memory"},
    )
    loader._loaded_plugins["memory-plugin"] = PluginRecord(
        manifest=manifest,
        source_path=tmp_path,
        instance=object(),
        status="active",
        enabled=True,
    )
    report = await loader.lifecycle.update_config("memory-plugin", {})
    assert not report.ok
    assert report.unchanged
    assert report.conflict
    assert not closed
    assert inst.has_runtime_ledger()
    assert loader.get_loaded_plugin("memory-plugin").status == "active"
    from fastapi import HTTPException
    from qwenpaw.app.routers.plugins import (
        UpdatePluginConfigRequest,
        update_plugin_config,
    )

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(plugin_loader=loader)),
    )
    with pytest.raises(HTTPException) as error:
        await update_plugin_config(
            "memory-plugin",
            UpdatePluginConfigRequest(config={}),
            request,
        )
    assert error.value.status_code == 409
    assert error.value.detail["unchanged"]
    assert not closed


@pytest.mark.asyncio
async def test_channel_failed_projection_can_retry_cleanup(
    registry,
    monkeypatch,
):
    ws = workspace()
    manager = ChannelManager([])
    manager._process = lambda *_: None
    ws.channel_manager = manager
    registry.projector = WorkspaceProjector(lambda: [ws])
    ch = SimpleNamespace(
        channel="partial",
        uses_manager_queue=False,
        start=AsyncMock(side_effect=RuntimeError("start failed")),
        stop=AsyncMock(side_effect=RuntimeError("stop failed")),
        set_enqueue=lambda _: None,
    )
    monkeypatch.setattr(
        "qwenpaw.app.channels.manager.instantiate_channel",
        lambda *a, **k: ch,
    )
    monkeypatch.setattr(
        "qwenpaw.plugins.workspace_projector.channel_passes_gates",
        lambda *_: True,
    )
    loader = PluginLoader([])
    inst = loader.lifecycle.ensure_instance("channel-plugin")
    api = PluginApi("channel-plugin", {}, {"id": "channel-plugin"})
    api.set_registry(registry)
    api.bind_instance(inst)
    api._project_channel("partial")
    with pytest.raises(RuntimeError):
        await registry.projector.project(
            "channel",
            "partial",
            "channel-plugin",
        )
    report = await inst.dispose(UnloadMode.UNLOAD)
    assert not report.quiescent
    assert report.needs_restart
    assert await manager.get_channel("partial") is ch
    ch.stop.side_effect = None
    report = await inst.dispose(UnloadMode.UNLOAD)
    assert report.quiescent
    assert await manager.get_channel("partial") is None


@pytest.mark.asyncio
async def test_restart_cleanup_preserves_only_unfinished_rows(
    tmp_path,
    registry,
    monkeypatch,
):
    root = tmp_path / "plugins" / "disk-plugin"
    root.mkdir(parents=True)
    (root / "plugin.json").write_text(
        json.dumps({"id": "disk-plugin", "version": "1.0.0", "name": "Disk"}),
    )
    flag = tmp_path / "busy"
    flag.touch()
    completed = tmp_path / "completed"
    (root / "cleanup.py").write_text(
        "from pathlib import Path\n"
        f"def first():\n    Path({str(completed)!r}).write_text('done')\n"
        "def second():\n"
        f"    if Path({str(flag)!r}).exists():\n"
        "        raise RuntimeError('busy')\n",
    )
    record_escape_provision(
        "disk-plugin",
        "first",
        teardown_ref="cleanup:first",
    )
    record_escape_provision(
        "disk-plugin",
        "second",
        teardown_ref="cleanup:second",
    )
    loader = PluginLoader([tmp_path / "plugins"])
    monkeypatch.setattr(loader, "_drop_uninstalled_settings", AsyncMock())
    report = await loader.unload_plugin(
        "disk-plugin",
        mode=UnloadMode.UNINSTALL,
    )
    assert not report.clean
    assert completed.read_text() == "done"
    assert [
        row["desc"] for row in load_inventory("disk-plugin")["provisions"]
    ] == ["second"]
    completed.write_text("do not run first again")
    flag.unlink()
    report = await loader.unload_plugin(
        "disk-plugin",
        mode=UnloadMode.UNINSTALL,
    )
    assert report.clean
    assert not root.exists()
    assert completed.read_text() == "do not run first again"


@pytest.mark.asyncio
async def test_failed_mode_setup_cleanup_is_reported_as_unquiescent(registry):
    ws = workspace()
    registry.projector = WorkspaceProjector(lambda: [ws])
    loader = PluginLoader([])
    inst = loader.lifecycle.ensure_instance("bad-mode")
    api = PluginApi("bad-mode", {}, {"id": "bad-mode"})
    api.set_registry(registry)
    api.bind_instance(inst)

    class Mode:
        name = "partial"

        def setup(self, _):
            raise RuntimeError("setup failed")

        def teardown(self, _):
            raise RuntimeError("resource remains")

    api.register_mode(Mode)
    with pytest.raises(RuntimeError):
        await registry.projector.project("mode", "partial", "bad-mode")
    report = await inst.dispose(UnloadMode.UNLOAD)
    assert not report.quiescent
    assert report.needs_restart
    assert not ws.plugins.modes
    assert len(ws.plugins._pending_modes) == 1


@pytest.mark.asyncio
async def test_retiring_workspace_cleanup_preserves_new_workspace(registry):
    old, new = workspace(), workspace()
    live = [old]
    registry.projector = WorkspaceProjector(lambda: live)
    api = PluginApi("retiring", {}, {"id": "retiring"})
    api.set_registry(registry)
    api.register_slash_command("hello", lambda *_: None)
    await registry.projector.project("slash_command", "hello", "retiring")
    await registry.projector.project_one(
        new,
        "slash_command",
        "hello",
        "retiring",
    )
    live[:] = [new]
    await registry.projector.revoke_workspace(old)
    assert old.plugins.slash_command_registry.resolve("/hello") is None
    assert new.plugins.slash_command_registry.resolve("/hello") is not None
    await registry.projector.revoke("slash_command", "hello", "retiring")
    assert new.plugins.slash_command_registry.resolve("/hello") is None


def test_existing_provision_can_gain_restartable_cleanup_without_setup(
    registry,
):
    calls = []
    api = PluginApi("upgrade-cleanup", {}, {"id": "upgrade-cleanup"})
    api.set_registry(registry)
    api.provision("owned", lambda: calls.append("setup"), lambda: None)
    api.provision(
        "owned",
        lambda: calls.append("duplicate"),
        lambda: None,
        teardown_ref="cleanup:remove",
    )
    assert calls == ["setup"]
    assert (
        load_inventory("upgrade-cleanup")["provisions"][0]["teardown_ref"]
        == "cleanup:remove"
    )


@pytest.mark.asyncio
async def test_workspace_stop_releases_its_plugin_bindings(registry):
    from qwenpaw.app.workspace.workspace import Workspace

    old = Workspace.__new__(Workspace)
    old.agent_id = "same-agent"
    old.plugins = WorkspacePlugins()
    old._started = True
    old._start_attempted = True
    old._harness_runtime = None
    old._service_manager = SimpleNamespace(stop_all=AsyncMock(), services={})
    new = workspace()
    registry.projector = WorkspaceProjector(lambda: [old])
    api = PluginApi("stop-workspace", {}, {"id": "stop-workspace"})
    api.set_registry(registry)
    api.register_slash_command("hello", lambda *_: None)
    await registry.projector.project(
        "slash_command",
        "hello",
        "stop-workspace",
    )
    await registry.projector.project_one(
        new,
        "slash_command",
        "hello",
        "stop-workspace",
    )
    await old.stop(final=False)
    assert old.plugins.slash_command_registry.resolve("/hello") is None
    assert new.plugins.slash_command_registry.resolve("/hello") is not None
    old._service_manager.stop_all.assert_awaited_once()


@pytest.mark.asyncio
async def test_unresolved_restart_cleanup_returns_http_conflict(
    tmp_path,
    registry,
):
    from fastapi import HTTPException
    from qwenpaw.app.routers.plugins import uninstall_plugin

    root = tmp_path / "plugins" / "disk-plugin"
    root.mkdir(parents=True)
    (root / "plugin.json").write_text(
        json.dumps({"id": "disk-plugin", "version": "1.0.0", "name": "Disk"}),
    )
    record_escape_provision("disk-plugin", "unresolved")
    loader = PluginLoader([tmp_path / "plugins"])
    app = SimpleNamespace(state=SimpleNamespace(plugin_loader=loader))
    with pytest.raises(HTTPException) as error:
        await uninstall_plugin("disk-plugin", SimpleNamespace(app=app))
    assert error.value.status_code == 409
    assert error.value.detail["needs_restart"]
    assert not error.value.detail["quiescent"]
    assert root.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("custom_awaitable", [False, True])
async def test_restart_cleanup_awaits_result(
    tmp_path,
    registry,
    monkeypatch,
    custom_awaitable,
):
    root = tmp_path / "plugins" / "async-cleanup"
    root.mkdir(parents=True)
    (root / "plugin.json").write_text(
        json.dumps(
            {"id": "async-cleanup", "version": "1.0.0", "name": "Async"},
        ),
    )
    flag = tmp_path / "finished"
    body = (
        "from pathlib import Path\n"
        "async def finish():\n"
        f"    Path({str(flag)!r}).write_text('done')\n"
    )
    if custom_awaitable:
        body += (
            "class Pending:\n"
            "    def __await__(self):\n"
            "        return finish().__await__()\n"
            "def cleanup():\n"
            "    return Pending()\n"
        )
    else:
        body += "def cleanup():\n    return finish()\n"
    (root / "cleanup.py").write_text(body)
    record_escape_provision(
        "async-cleanup",
        "resource",
        teardown_ref="cleanup:cleanup",
    )
    loader = PluginLoader([tmp_path / "plugins"])
    monkeypatch.setattr(loader, "_drop_uninstalled_settings", AsyncMock())
    report = await loader.unload_plugin(
        "async-cleanup",
        mode=UnloadMode.UNINSTALL,
    )
    assert report.clean
    assert flag.read_text() == "done"
    assert not root.exists()
