# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
"""Plugin load, reload, provision, and custody contracts."""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.channels.manager import ChannelManager
from qwenpaw.app.routers.plugins import (
    UpdatePluginConfigRequest,
    uninstall_plugin_source,
    update_plugin_config,
)
from qwenpaw.plugins.architecture import PluginManifest
from qwenpaw.plugins.custody import close_connection
from qwenpaw.plugins.lifecycle import (
    PluginInstance,
    PluginState,
    UnloadMode,
    UnloadReport,
)
from qwenpaw.plugins.dependency_gate import DependencyGate
from qwenpaw.plugins.loader import PluginLoader
from qwenpaw.plugins.provision import (
    apply_tool_factory,
    load_inventory,
    provision_files,
    teardown_created_locations,
)
from qwenpaw.plugins.registry import PluginRegistry
from qwenpaw.plugins.safe_fs import (
    ensure_deletable,
    parse_optional_absolute,
    same_location,
)
from qwenpaw.plugins.updates import (
    marker_path,
    recover_interrupted_updates,
    updates_dir,
)
from qwenpaw.plugins.workspace_projector import WorkspaceProjector
from qwenpaw.runtime.slash_command_registry import SlashCommandRegistry
from qwenpaw.runtime.tool_registry import ToolRegistry


@pytest.fixture()
def fresh_registry():
    old = PluginRegistry._instance
    PluginRegistry._instance = None
    registry = PluginRegistry()
    yield registry
    PluginRegistry._instance = old


def _write_plugin(
    root: Path,
    plugin_id: str,
    *,
    body: str = "pass",
    requirements: str | None = None,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "plugin.json").write_text(
        json.dumps(
            {
                "id": plugin_id,
                "version": "1.0.0",
                "name": plugin_id,
                "entry": {"backend": "main.py"},
            },
        ),
        encoding="utf-8",
    )
    (root / "main.py").write_text(
        "class _P:\n"
        f"    def register(self, api):\n"
        f"        {body}\n"
        "plugin = _P()\n",
        encoding="utf-8",
    )
    if requirements is not None:
        (root / "requirements.txt").write_text(
            requirements,
            encoding="utf-8",
        )
    return root


def _slash_workspace():
    return SimpleNamespace(
        agent_id="talk",
        plugins=SimpleNamespace(
            slash_command_registry=SlashCommandRegistry(),
            tool_registry=ToolRegistry(),
        ),
    )


def _isolate_working_dir(tmp_path: Path, monkeypatch) -> Path:
    work = tmp_path / "work"
    work.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", work)
    monkeypatch.setattr("qwenpaw.config.utils.WORKING_DIR", work)
    from qwenpaw.config import utils as config_utils

    config_utils._config_cache = None
    config_utils._config_mtime = None
    config_utils._agent_config_cache.clear()
    return work


def _seed_talk_agent(tmp_path: Path, monkeypatch) -> Path:
    from qwenpaw.config.config import AgentProfileRef, AgentsConfig, Config
    from qwenpaw.config.utils import save_config

    work = _isolate_working_dir(tmp_path, monkeypatch)
    workspace = work / "workspaces" / "talk"
    workspace.mkdir(parents=True, exist_ok=True)
    save_config(
        Config(
            agents=AgentsConfig(
                active_agent="talk",
                agent_order=["talk"],
                profiles={
                    "talk": AgentProfileRef(
                        id="talk",
                        workspace_dir=str(workspace),
                    ),
                },
            ),
        ),
        work / "config.json",
    )
    monkeypatch.setattr(
        "qwenpaw.app.agent_context.get_current_agent_id",
        lambda: "talk",
    )
    return workspace


def _agent_tool_names(agent_id: str = "talk") -> set[str]:
    from qwenpaw.config.config import load_agent_config

    return set(load_agent_config(agent_id).tools.builtin_tools)


def _seed_two_agents(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    from qwenpaw.config.config import AgentProfileRef, AgentsConfig, Config
    from qwenpaw.config.utils import save_config

    work = _isolate_working_dir(tmp_path, monkeypatch)
    talk = work / "workspaces" / "talk"
    other = work / "workspaces" / "other"
    talk.mkdir(parents=True, exist_ok=True)
    other.mkdir(parents=True, exist_ok=True)
    save_config(
        Config(
            agents=AgentsConfig(
                active_agent="talk",
                agent_order=["talk", "other"],
                profiles={
                    "talk": AgentProfileRef(
                        id="talk",
                        workspace_dir=str(talk),
                    ),
                    "other": AgentProfileRef(
                        id="other",
                        workspace_dir=str(other),
                    ),
                },
            ),
        ),
        work / "config.json",
    )
    monkeypatch.setattr(
        "qwenpaw.app.agent_context.get_current_agent_id",
        lambda: "talk",
    )
    from qwenpaw.config.config import (
        AgentProfileConfig,
        ToolsConfig,
        save_agent_config,
    )

    for agent_id, workspace in (("talk", talk), ("other", other)):
        save_agent_config(
            agent_id,
            AgentProfileConfig(
                id=agent_id,
                name=agent_id,
                workspace_dir=str(workspace),
                tools=ToolsConfig(builtin_tools={}),
            ),
        )
    return talk, other


def _raw_agent_tools(workspace: Path) -> set[str]:
    path = workspace / "agent.json"
    if not path.is_file():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    tools = (data.get("tools") or {}).get("builtin_tools") or {}
    return set(tools)


def _volume_is_case_insensitive(path: Path) -> bool:
    path.mkdir(parents=True, exist_ok=True)
    probe = path / "CaseProbe"
    probe.mkdir()
    alias = path / "caseprobe"
    try:
        return alias.exists() and same_location(probe, alias)
    finally:
        shutil.rmtree(probe)


def _patch_agent_tools(monkeypatch):
    boxes = {
        "talk": SimpleNamespace(tools=SimpleNamespace(builtin_tools={})),
    }

    def _load(agent_id):
        return boxes[agent_id]

    def _save(agent_id, cfg):
        boxes[agent_id] = cfg

    monkeypatch.setattr(
        "qwenpaw.app.agent_context.get_current_agent_id",
        lambda: "talk",
    )
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        _load,
    )
    monkeypatch.setattr(
        "qwenpaw.config.config.save_agent_config",
        _save,
    )
    return boxes


def _control_body(name: str) -> str:
    return (
        "from qwenpaw.runtime.commands.control.base import "
        "BaseControlCommandHandler\n"
        "        class _H(BaseControlCommandHandler):\n"
        f"            command_name = '{name}'\n"
        "            async def handle(self, context):\n"
        "                return 'ok'\n"
        "        api.register_control_command(_H())"
    )


def _tool_body(name: str, description: str = "shared") -> str:
    return (
        f"def _{name}():\n"
        "            return 'ok'\n"
        "        api.register_tool(\n"
        f"            '{name}', _{name}, description={description!r},\n"
        "        )"
    )


def _tools_body(*pairs: tuple[str, str]) -> str:
    chunks = [_tool_body(name, desc) for name, desc in pairs]
    return ("\n        ").join(chunks)


def _tool_description(name: str, agent_id: str = "talk") -> str | None:
    from qwenpaw.config.config import load_agent_config

    tool = load_agent_config(agent_id).tools.builtin_tools.get(name)
    if tool is None:
        return None
    return getattr(tool, "description", None)


async def _load(
    tmp_path: Path,
    fresh_registry,
    plugin_id: str,
    body: str,
    *,
    config: dict | None = None,
    activate: bool = True,
):
    workspace = _slash_workspace()
    fresh_registry.projector = WorkspaceProjector(
        live_workspaces=lambda: [workspace],
    )
    fresh_registry.set_workspace_manager(
        SimpleNamespace(agents={"talk": workspace}),
    )
    installed = _write_plugin(
        tmp_path / "plugins" / plugin_id,
        plugin_id,
        body=body,
    )
    loader = PluginLoader(plugin_dirs=[tmp_path / "plugins"])
    loader.registry = fresh_registry
    manifest = PluginManifest.from_dict(
        json.loads((installed / "plugin.json").read_text(encoding="utf-8")),
    )
    await loader.load_plugin(
        manifest,
        installed,
        config,
        activate=activate,
    )
    return loader, workspace, installed


@pytest.mark.asyncio
async def test_collision_does_not_revoke_other_owner(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    loader, workspace, _installed = await _load(
        tmp_path,
        fresh_registry,
        "owner-a",
        "api.register_slash_command('ping', lambda c, a: None)",
    )
    _write_plugin(
        tmp_path / "plugins" / "owner-b",
        "owner-b",
        body="api.register_slash_command('ping', lambda c, a: None)",
    )
    manifest_b = PluginManifest.from_dict(
        json.loads(
            (tmp_path / "plugins" / "owner-b" / "plugin.json").read_text(
                encoding="utf-8",
            ),
        ),
    )
    await loader.load_plugin(
        manifest_b,
        tmp_path / "plugins" / "owner-b",
        activate=False,
    )
    with pytest.raises(Exception, match="Projection|already"):
        await loader.activate_plugin_unlocked("owner-b")
    await loader.unload_plugin("owner-b", delete_files=False)
    assert "ping" in workspace.plugins.slash_command_registry.names()


@pytest.mark.asyncio
async def test_failed_staging_keeps_old_dir(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    loader, _workspace, installed = await _load(
        tmp_path,
        fresh_registry,
        "stage-keep",
        "api.register_slash_command('ping', lambda c, a: None)",
    )
    old_text = (installed / "main.py").read_text(encoding="utf-8")
    staging = _write_plugin(
        tmp_path / "incoming-stage",
        "stage-keep",
        body="api.register_slash_command('pong', lambda c, a: None)",
    )

    def _boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("qwenpaw.plugins.loader.shutil.copytree", _boom)
    report = await loader.lifecycle.reload(
        "stage-keep",
        new_source=staging,
    )
    assert not report.ok
    assert (installed / "main.py").read_text(encoding="utf-8") == old_text
    assert "stage-keep" in loader.get_all_loaded_plugins()


@pytest.mark.asyncio
async def test_startup_failure_restores_old_projection(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    loader, workspace, installed = await _load(
        tmp_path,
        fresh_registry,
        "svc",
        "api.register_slash_command('ping', lambda c, a: None)",
    )
    old_text = (installed / "main.py").read_text(encoding="utf-8")
    staging = _write_plugin(
        tmp_path / "incoming-svc",
        "svc",
        body=(
            "api.register_slash_command('pong', lambda c, a: None)\n"
            "        def _boom():\n"
            "            raise RuntimeError('startup boom')\n"
            "        api.register_startup_hook('boom', _boom)"
        ),
    )
    report = await loader.lifecycle.reload("svc", new_source=staging)
    assert not report.ok
    assert (installed / "main.py").read_text(encoding="utf-8") == old_text
    assert "ping" in workspace.plugins.slash_command_registry.names()
    assert "pong" not in workspace.plugins.slash_command_registry.names()


@pytest.mark.asyncio
async def test_sync_close_does_not_block_event_loop():
    beats: list[float] = []

    async def _heart() -> None:
        for _ in range(8):
            beats.append(time.monotonic())
            await asyncio.sleep(0.01)

    class _SlowClose:
        def close(self) -> None:
            time.sleep(0.12)

    heart = asyncio.create_task(_heart())
    await close_connection(_SlowClose(), "slow")
    await heart
    gaps = [later - earlier for earlier, later in zip(beats, beats[1:])]
    assert gaps
    assert min(gaps) < 0.05


def test_empty_update_paths_are_noop(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    sentinel = tmp_path / "work" / "keep-me"
    sentinel.parent.mkdir(parents=True)
    sentinel.write_text("safe\n", encoding="utf-8")
    marker = updates_dir() / "empty.json"
    marker.write_text(
        json.dumps(
            {
                "plugin_id": "empty",
                "status": "updating",
                "backup_path": "",
                "target_path": "",
                "staging_path": "",
            },
        ),
        encoding="utf-8",
    )
    recover_interrupted_updates()
    assert sentinel.read_text(encoding="utf-8") == "safe\n"
    assert parse_optional_absolute("") is None
    assert parse_optional_absolute(None) is None
    with pytest.raises(ValueError, match="refusing to delete"):
        ensure_deletable(Path(""))


@pytest.mark.asyncio
async def test_dependency_gate_runs_before_probe(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    loader, _workspace, _installed = await _load(
        tmp_path,
        fresh_registry,
        "deps",
        "pass",
    )
    incoming = _write_plugin(
        tmp_path / "incoming-deps",
        "deps",
        body="import definitely_not_a_real_pkg_xyz\n        pass",
        requirements="definitely-not-a-real-pkg-xyz==9.9.9\n",
    )
    order: list[str] = []

    def _eval(self, *args, **kwargs):
        del self, args, kwargs
        order.append("gate")
        from qwenpaw.plugins.dependency_gate import GateDecision

        return GateDecision(
            allow_install=False,
            already_satisfied=True,
            reason="ok",
        )

    monkeypatch.setattr(DependencyGate, "evaluate", _eval)

    async def _probe(*args, **kwargs):
        del args, kwargs
        order.append("probe")
        return None

    monkeypatch.setattr("qwenpaw.plugins.loader._probe_incoming", _probe)
    report = await loader.lifecycle.reload(
        "deps",
        new_source=incoming,
        allow_install=True,
    )
    assert not report.ok
    assert "gate" in order
    assert order.index("gate") < order.index("probe")


def test_platform_marker_is_skipped(tmp_path: Path):
    req = tmp_path / "requirements.txt"
    req.write_text(
        'definitely-windows-only-xyz==1.0; sys_platform == "win32"\n'
        'definitely-darwin-only-xyz==1.0; sys_platform == "darwin"\n',
        encoding="utf-8",
    )
    decision = DependencyGate().evaluate(
        req,
        allow_install=False,
        plugin_id="p",
    )
    missing = " ".join(decision.missing)
    if sys.platform == "win32":
        assert "definitely-windows-only-xyz" in missing
        assert "definitely-darwin-only-xyz" not in missing
    elif sys.platform == "darwin":
        assert "definitely-darwin-only-xyz" in missing
        assert "definitely-windows-only-xyz" not in missing
    assert not decision.unsupported


def test_unsupported_requirement_is_loud(tmp_path: Path):
    req = tmp_path / "requirements.txt"
    req.write_text("-r extra.txt\n", encoding="utf-8")
    decision = DependencyGate().evaluate(
        req,
        allow_install=True,
        plugin_id="p",
    )
    assert decision.unsupported
    assert not decision.allow_install
    assert "unsupported" in decision.reason


def test_migrate_keeps_owned_for_uninstall(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    src = tmp_path / "src"
    src.mkdir()
    (src / "note.md").write_text("v1\n", encoding="utf-8")
    dest = tmp_path / "dest"
    assert provision_files("own", src, dest, "1.0.0") == "create"
    (src / "note.md").write_text("v2\n", encoding="utf-8")
    assert provision_files("own", src, dest, "2.0.0") == "migrate"
    loc = load_inventory("own")["locations"][str(dest)]
    assert loc["owned"] is True
    assert "branch" not in loc
    teardown_created_locations("own")
    assert not dest.exists()


@pytest.mark.asyncio
async def test_failed_register_undoes_this_txn_create(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    dest = tmp_path / "created-once"
    body = (
        "from pathlib import Path\n"
        f"        api.provision_files(Path({str(tmp_path / 'factory')!r}), "
        f"Path({str(dest)!r}), '1.0.0')\n"
        "        raise RuntimeError('register boom')"
    )
    factory = tmp_path / "factory"
    factory.mkdir()
    (factory / "note.md").write_text("v1\n", encoding="utf-8")
    installed = _write_plugin(tmp_path / "plugins" / "boom", "boom", body=body)
    loader = PluginLoader(plugin_dirs=[tmp_path / "plugins"])
    loader.registry = fresh_registry
    manifest = PluginManifest.from_dict(
        json.loads((installed / "plugin.json").read_text(encoding="utf-8")),
    )
    record = await loader.load_plugin(manifest, installed)
    assert record.status == "failed"
    assert not dest.exists()


@pytest.mark.asyncio
async def test_failed_channel_stop_keeps_handle():
    class _Bad:
        channel = "bad-ch"

        def set_enqueue(self, _enqueue) -> None:
            return None

        async def stop(self) -> None:
            raise RuntimeError("still connected")

    manager = ChannelManager([])
    bad = _Bad()
    manager.channels.append(bad)
    receipt = await manager.stop_one("bad-ch")
    assert receipt.stopped is False
    assert bad in manager.channels


@pytest.mark.asyncio
async def test_unquiescent_reload_does_not_reregister(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    loader, _workspace, _installed = await _load(
        tmp_path,
        fresh_registry,
        "busy",
        "pass",
    )

    async def _busy_unload(*_args, **_kwargs):
        return UnloadReport(
            plugin_id="busy",
            mode=UnloadMode.UNLOAD,
            clean=False,
            quiescent=False,
            needs_restart=True,
            errors=["thread still running"],
        )

    monkeypatch.setattr(loader, "_unload_plugin_unlocked", _busy_unload)
    report = await loader.lifecycle.reload("busy")
    assert not report.ok
    assert report.needs_restart
    assert "busy" in loader.get_all_loaded_plugins()


@pytest.mark.asyncio
async def test_config_route_runs_startup_once(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    monkeypatch.setattr(
        "qwenpaw.plugins.settings.persist_plugin_settings",
        lambda *args, **kwargs: None,
    )
    counter = tmp_path / "starts.txt"
    body = (
        "from pathlib import Path\n"
        f"        p = Path({str(counter)!r})\n"
        "        def _start(_p=p):\n"
        "            n = int(_p.read_text()) if _p.exists() else 0\n"
        "            _p.write_text(str(n + 1))\n"
        "        api.register_startup_hook('count', _start)\n"
        "        api.register_slash_command("
        "api.config.get('cmd', 'old'), lambda c, a: None)"
    )
    loader, _workspace, _installed = await _load(
        tmp_path,
        fresh_registry,
        "cfg",
        body,
        config={"cmd": "old"},
    )
    before = int(counter.read_text()) if counter.exists() else 0
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(plugin_loader=loader)),
    )
    result = await update_plugin_config(
        "cfg",
        UpdatePluginConfigRequest(config={"cmd": "new"}),
        request,
    )
    assert result["ok"] is True
    after = int(counter.read_text())
    assert after - before == 1


@pytest.mark.asyncio
async def test_reload_generation_keeps_new_task(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    marker = tmp_path / "task.txt"
    body = (
        "import pathlib\n"
        "        async def _run():\n"
        f"            pathlib.Path({str(marker)!r}).write_text('ran')\n"
        "        api.spawn_task(_run(), 'tick')"
    )
    loader, _workspace, installed = await _load(
        tmp_path,
        fresh_registry,
        "gen",
        body,
    )
    await asyncio.sleep(0.05)
    assert marker.read_text() == "ran"
    inst = loader.lifecycle.get_instance("gen")
    assert inst is not None
    first_gen = inst.generation
    marker.write_text("")
    _write_plugin(
        installed,
        "gen",
        body=(
            "import pathlib\n"
            "        async def _run():\n"
            f"            pathlib.Path({str(marker)!r}).write_text('ran2')\n"
            "        api.spawn_task(_run(), 'tick')"
        ),
    )
    report = await loader.lifecycle.reload("gen")
    assert report.ok
    assert report.generation == first_gen + 1
    await asyncio.sleep(0.05)
    assert marker.read_text() == "ran2"


@pytest.mark.asyncio
async def test_in_place_rollback_reuses_old_plugin_def(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    loader, workspace, installed = await _load(
        tmp_path,
        fresh_registry,
        "inplace",
        "api.register_slash_command('ping', lambda c, a: None)",
    )
    (installed / "main.py").write_text(
        "class _P:\n"
        "    def register(self, api):\n"
        "        raise RuntimeError('bad disk')\n"
        "plugin = _P()\n",
        encoding="utf-8",
    )
    report = await loader.lifecycle.reload("inplace")
    assert not report.ok
    assert loader.get_loaded_plugin("inplace").status == "active"
    assert "ping" in workspace.plugins.slash_command_registry.names()


@pytest.mark.asyncio
async def test_repair_keeps_config_and_activates(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    loader, workspace, _installed = await _load(
        tmp_path,
        fresh_registry,
        "fixme",
        "api.register_slash_command(api.config.get('cmd', 'x'), "
        "lambda c, a: None)",
        config={"cmd": "kept"},
    )
    record = loader.get_loaded_plugin("fixme")
    record.status = "failed"
    record.enabled = False
    inst = loader.lifecycle.get_instance("fixme")
    inst.mark_failed("missing dep")
    inst.activated = False
    repaired = await loader.repair_dependencies("fixme")
    assert repaired.status == "active"
    assert loader.lifecycle.get_instance("fixme").config.get("cmd") == "kept"
    assert "kept" in workspace.plugins.slash_command_registry.names()


@pytest.mark.asyncio
async def test_force_install_respects_owns_commit(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    loader, _workspace, installed = await _load(
        tmp_path,
        fresh_registry,
        "owned",
        "pass",
    )
    loader.lifecycle.delegate.owns_commit = lambda _plugin_id: False
    staging = _write_plugin(
        tmp_path / "staging-owned",
        "owned",
        body="api.register_slash_command('nope', lambda c, a: None)",
    )
    with pytest.raises(RuntimeError, match="not owned"):
        await loader.load_plugin_from_path(staging, force=True)
    assert "class _P" in (installed / "main.py").read_text(encoding="utf-8")
    assert "register_slash_command" not in (installed / "main.py").read_text(
        encoding="utf-8",
    )


def test_same_location_uses_identity(tmp_path: Path):
    target = tmp_path / "CasePlugin"
    target.mkdir()
    alias = tmp_path / "CasePlugin"
    assert same_location(target, alias)
    missing = tmp_path / "missing-a"
    other = tmp_path / "missing-b"
    assert same_location(missing, missing)
    assert not same_location(missing, other)


def test_factory_baseline_frozen_until_commit(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    apply_tool_factory(
        "tid",
        "demo",
        {"description": "old"},
        None,
    )
    first = apply_tool_factory(
        "tid",
        "demo",
        {"description": "new"},
        {"description": "old"},
    )
    second = apply_tool_factory(
        "tid",
        "demo",
        {"description": "new"},
        {"description": "old"},
    )
    assert first["description"] == "new"
    assert second["description"] == "new"
    row = load_inventory("tid")["tools"]["demo"]
    assert row["factory"]["description"] == "old"
    assert row["pending_factory"]["description"] == "new"


@pytest.mark.asyncio
async def test_unload_keeps_instance_when_not_quiescent(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    loader, _workspace, _installed = await _load(
        tmp_path,
        fresh_registry,
        "held",
        "pass",
    )
    inst = loader.lifecycle.get_instance("held")
    assert inst is not None

    async def _hang():
        raise TimeoutError("thread still running")

    inst.record_runtime("thread:x", _hang, kind="custody")
    report = await loader.unload_plugin("held", delete_files=False)
    assert report.quiescent is False
    assert report.needs_restart is True
    assert loader.lifecycle.get_instance("held") is inst
    assert "held" in loader.get_all_loaded_plugins()


@pytest.mark.asyncio
async def test_teardown_timeout_is_not_quiescent():
    inst = PluginInstance("stuck")

    async def _hang():
        raise TimeoutError("thread still running")

    inst.record_runtime("thread:x", _hang, kind="custody")
    report = await inst.teardown_runtime()
    assert report.clean is False
    assert report.quiescent is False
    assert report.needs_restart is True
    assert inst.state is PluginState.ACTIVE
    assert inst._runtime


@pytest.mark.asyncio
async def test_repair_does_not_load_disabled_plugin(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")

    class _Cfg:
        plugins = {"off": {"enabled": False}}

    monkeypatch.setattr(
        "qwenpaw.config.utils.load_config",
        lambda *args, **kwargs: _Cfg(),
    )
    installed = _write_plugin(tmp_path / "plugins" / "off", "off")
    loader = PluginLoader(plugin_dirs=[tmp_path / "plugins"])
    loader.registry = fresh_registry
    repaired = await loader.repair_dependencies("off")
    assert repaired.status == "inactive"
    assert repaired.enabled is False
    assert "off" not in loader.get_all_loaded_plugins()
    assert loader.lifecycle.get_instance("off") is None
    del installed


@pytest.mark.asyncio
async def test_occupied_swap_keeps_marker_and_needs_restart(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    loader, _workspace, installed = await _load(
        tmp_path,
        fresh_registry,
        "busyfs",
        "pass",
    )
    incoming = _write_plugin(
        tmp_path / "incoming-busyfs",
        "busyfs",
        body="api.register_slash_command('next', lambda c, a: None)",
    )
    moves = {"n": 0}
    real_move = shutil.move

    def _move(src, dst, *args, **kwargs):
        moves["n"] += 1
        if moves["n"] >= 2:
            raise PermissionError("file in use")
        return real_move(src, dst, *args, **kwargs)

    monkeypatch.setattr("qwenpaw.plugins.loader.shutil.move", _move)
    report = await loader.reload_plugin_unlocked(
        "busyfs",
        new_source=incoming,
        allow_install=False,
        owns_dependency_env=True,
    )
    assert not report.ok
    assert report.needs_restart
    assert marker_path("busyfs").is_file()
    del installed


def _clear_tool_owners():
    from qwenpaw.plugins.api import (
        _TOOL_PLUGIN_OWNERS,
        _TOOL_PLUGIN_OWNERS_LOCK,
    )

    with _TOOL_PLUGIN_OWNERS_LOCK:
        _TOOL_PLUGIN_OWNERS.clear()


@pytest.mark.asyncio
async def test_tool_collision_does_not_revoke_other_owner(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    boxes = _patch_agent_tools(monkeypatch)
    _clear_tool_owners()
    loader, workspace, _installed = await _load(
        tmp_path,
        fresh_registry,
        "owner-a",
        _tool_body("shared_tool"),
    )
    assert "shared_tool" in workspace.plugins.tool_registry.names()
    assert "shared_tool" in boxes["talk"].tools.builtin_tools
    from qwenpaw.plugins.api import _TOOL_PLUGIN_OWNERS

    assert _TOOL_PLUGIN_OWNERS.get("shared_tool") == "owner-a"
    _write_plugin(
        tmp_path / "plugins" / "owner-b",
        "owner-b",
        body=_tool_body("shared_tool"),
    )
    manifest_b = PluginManifest.from_dict(
        json.loads(
            (tmp_path / "plugins" / "owner-b" / "plugin.json").read_text(
                encoding="utf-8",
            ),
        ),
    )
    await loader.load_plugin(
        manifest_b,
        tmp_path / "plugins" / "owner-b",
        activate=False,
    )
    with pytest.raises(Exception, match="Projection|already|owned"):
        await loader.activate_plugin_unlocked("owner-b")
    record_b = loader.get_loaded_plugin("owner-b")
    assert record_b is None or record_b.status != "active"
    await loader.unload_plugin(
        "owner-b",
        delete_files=True,
        mode=UnloadMode.UNINSTALL,
    )
    assert "shared_tool" in workspace.plugins.tool_registry.names()
    assert "shared_tool" in boxes["talk"].tools.builtin_tools
    assert _TOOL_PLUGIN_OWNERS.get("shared_tool") == "owner-a"
    _clear_tool_owners()


@pytest.mark.asyncio
async def test_control_command_collision_does_not_revoke_other_owner(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    from qwenpaw.runtime.commands.control import (
        command_owner,
        unregister_command,
    )

    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    loader, _workspace, _installed = await _load(
        tmp_path,
        fresh_registry,
        "cmd-a",
        _control_body("sharedcmd"),
    )
    assert command_owner("sharedcmd") == "cmd-a"
    _write_plugin(
        tmp_path / "plugins" / "cmd-b",
        "cmd-b",
        body=_control_body("sharedcmd"),
    )
    manifest_b = PluginManifest.from_dict(
        json.loads(
            (tmp_path / "plugins" / "cmd-b" / "plugin.json").read_text(
                encoding="utf-8",
            ),
        ),
    )
    record_b = await loader.load_plugin(
        manifest_b,
        tmp_path / "plugins" / "cmd-b",
        activate=False,
    )
    assert record_b.status != "active"
    if loader.get_loaded_plugin("cmd-b") is not None:
        await loader.unload_plugin("cmd-b", delete_files=False)
    assert command_owner("sharedcmd") == "cmd-a"
    await loader.unload_plugin("cmd-a", delete_files=False)
    unregister_command("sharedcmd", owner="cmd-a")


@pytest.mark.asyncio
async def test_stop_one_propagates_cancelled_error():
    class _Ch:
        channel = "x"

        def set_enqueue(self, _enqueue):
            return None

        async def stop(self):
            raise asyncio.CancelledError()

    manager = ChannelManager([])
    manager.channels = [_Ch()]
    with pytest.raises(asyncio.CancelledError):
        await manager.stop_one("x")
    assert manager.channels


@pytest.mark.asyncio
async def test_reload_cancel_after_unload_restores_old(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    loader, workspace, installed = await _load(
        tmp_path,
        fresh_registry,
        "svc-cancel",
        "api.register_slash_command('ping', lambda c, a: None)",
    )
    incoming = _write_plugin(
        tmp_path / "incoming-svc-cancel",
        "svc-cancel",
        body="api.register_slash_command('pong', lambda c, a: None)",
    )

    async def _cancel_swap(*_args, **_kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(loader, "_swap_plugin_dir", _cancel_swap)
    with pytest.raises(asyncio.CancelledError):
        await loader.reload_plugin_unlocked(
            "svc-cancel",
            new_source=incoming,
            allow_install=False,
            owns_dependency_env=True,
        )
    assert "ping" in workspace.plugins.slash_command_registry.names()
    record = loader.get_loaded_plugin("svc-cancel")
    assert record is not None
    assert record.status == "active"
    assert (installed / "main.py").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_reload_cancel_after_swap_restores_old(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    loader, workspace, installed = await _load(
        tmp_path,
        fresh_registry,
        "svc-swap-cancel",
        "api.register_slash_command('ping', lambda c, a: None)",
    )
    incoming = _write_plugin(
        tmp_path / "incoming-svc-swap-cancel",
        "svc-swap-cancel",
        body="api.register_slash_command('pong', lambda c, a: None)",
    )
    calls = {"n": 0}
    real_load = loader._load_plugin_unlocked

    async def _load_once(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise asyncio.CancelledError()
        return await real_load(*args, **kwargs)

    monkeypatch.setattr(loader, "_load_plugin_unlocked", _load_once)
    with pytest.raises(asyncio.CancelledError):
        await loader.reload_plugin_unlocked(
            "svc-swap-cancel",
            new_source=incoming,
            allow_install=False,
            owns_dependency_env=True,
        )
    assert "ping" in workspace.plugins.slash_command_registry.names()
    record = loader.get_loaded_plugin("svc-swap-cancel")
    assert record is not None
    assert record.status == "active"
    assert "pong" not in (installed / "main.py").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_install_cancel_waits_for_copy_before_next_load(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    source = _write_plugin(tmp_path / "src-copier", "copier", body="pass")
    install_dir = tmp_path / "plugins"
    install_dir.mkdir(parents=True, exist_ok=True)
    loader = PluginLoader(plugin_dirs=[install_dir])
    loader.registry = fresh_registry
    finished = {"done": False}
    real_copy = shutil.copytree

    def _slow_copy(src, dst, *args, **kwargs):
        time.sleep(0.12)
        result = real_copy(src, dst, *args, **kwargs)
        finished["done"] = True
        return result

    monkeypatch.setattr("qwenpaw.plugins.loader.shutil.copytree", _slow_copy)
    task = asyncio.create_task(
        loader.load_plugin_from_path(source, install_dir=install_dir),
    )
    await asyncio.sleep(0.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert finished["done"]
    record = await loader.load_plugin_from_path(
        source,
        install_dir=install_dir,
        force=True,
    )
    assert record.manifest.id == "copier"


@pytest.mark.asyncio
async def test_provision_replay_without_instance(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    flag = tmp_path / "cleared.txt"
    plugin_dir = tmp_path / "plugins" / "cloud-lite"
    _write_plugin(
        plugin_dir,
        "cloud-lite",
        body=(
            "api.provision(\n"
            "            'cloudpaw_agents',\n"
            "            setup=None,\n"
            "            teardown=None,\n"
            "            kind='cloudpaw_agents',\n"
            "            teardown_ref='agents_setup:uninstall_agents',\n"
            "        )"
        ),
    )
    (plugin_dir / "agents_setup.py").write_text(
        "from pathlib import Path\n"
        f"FLAG = Path({str(flag)!r})\n"
        "def uninstall_agents():\n"
        "    FLAG.write_text('cleared', encoding='utf-8')\n",
        encoding="utf-8",
    )
    loader, _workspace, _installed = await _load(
        tmp_path,
        fresh_registry,
        "cloud-lite",
        (
            "api.provision(\n"
            "            'cloudpaw_agents',\n"
            "            setup=None,\n"
            "            teardown=None,\n"
            "            kind='cloudpaw_agents',\n"
            "            teardown_ref='agents_setup:uninstall_agents',\n"
            "        )"
        ),
    )
    await loader.unload_plugin(
        "cloud-lite",
        delete_files=False,
        mode=UnloadMode.UNLOAD,
    )
    assert loader.get_loaded_plugin("cloud-lite") is None
    assert plugin_dir.is_dir()
    report = await loader.unload_plugin(
        "cloud-lite",
        delete_files=True,
        mode=UnloadMode.UNINSTALL,
    )
    assert report.quiescent
    assert flag.read_text(encoding="utf-8") == "cleared"


@pytest.mark.asyncio
async def test_pawapp_disable_then_delete_uses_lifecycle(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    from qwenpaw.app.routers.pawapps import uninstall_pawapp

    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    monkeypatch.setattr(
        "qwenpaw.config.utils.get_plugins_dir",
        lambda: tmp_path / "plugins",
    )
    loader, _workspace, installed = await _load(
        tmp_path,
        fresh_registry,
        "paw-app",
        "pass",
    )
    await loader.unload_plugin(
        "paw-app",
        delete_files=False,
        mode=UnloadMode.UNLOAD,
    )
    assert loader.get_loaded_plugin("paw-app") is None
    assert installed.is_dir()
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(plugin_loader=loader)),
    )
    result = await uninstall_pawapp("paw-app", request)
    assert result["id"] == "paw-app"
    assert not installed.exists()


@pytest.mark.asyncio
async def test_http_uninstall_does_not_delete_tools_from_meta(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    boxes = _patch_agent_tools(monkeypatch)
    _clear_tool_owners()
    loader, workspace, _installed = await _load(
        tmp_path,
        fresh_registry,
        "owner-a",
        _tool_body("shared_tool"),
    )
    _write_plugin(tmp_path / "plugins" / "meta-b", "meta-b", body="pass")
    plugin_json = tmp_path / "plugins" / "meta-b" / "plugin.json"
    data = json.loads(plugin_json.read_text(encoding="utf-8"))
    data["meta"] = {"tools": [{"name": "shared_tool"}]}
    plugin_json.write_text(json.dumps(data), encoding="utf-8")
    manifest_b = PluginManifest.from_dict(data)
    await loader.load_plugin(manifest_b, tmp_path / "plugins" / "meta-b")
    await loader.activate_plugin_unlocked("meta-b")
    removed = []
    monkeypatch.setattr(
        "qwenpaw.app.routers.plugins._remove_plugin_tools_from_agents",
        lambda plugin_id, meta: removed.append((plugin_id, meta)),
    )
    app = SimpleNamespace(state=SimpleNamespace(plugin_loader=loader))
    await uninstall_plugin_source("meta-b", app=app)
    assert not removed
    assert "shared_tool" in workspace.plugins.tool_registry.names()
    assert "shared_tool" in boxes["talk"].tools.builtin_tools
    _clear_tool_owners()


@pytest.mark.asyncio
async def test_activate_skill_copy_does_not_block_event_loop(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    from qwenpaw.plugins.api import PluginApi

    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")

    def _slow(self, *_args, **_kwargs):
        del self
        time.sleep(0.12)

    monkeypatch.setattr(PluginApi, "_do_install_skills", _slow)
    beats: list[float] = []

    async def _heart() -> None:
        for _ in range(8):
            beats.append(time.monotonic())
            await asyncio.sleep(0.01)

    heart = asyncio.create_task(_heart())
    await _load(
        tmp_path,
        fresh_registry,
        "skiller",
        "from pathlib import Path\n"
        "        api.register_skill_provider(Path('.'))",
    )
    await heart
    gaps = [later - earlier for earlier, later in zip(beats, beats[1:])]
    assert gaps
    assert min(gaps) < 0.05


@pytest.mark.asyncio
async def test_activate_tool_config_write_does_not_block_event_loop(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    _patch_agent_tools(monkeypatch)
    _clear_tool_owners()

    def _slow(*_args, **_kwargs):
        time.sleep(0.12)

    monkeypatch.setattr("qwenpaw.plugins.api._write_tool_config", _slow)
    beats: list[float] = []

    async def _heart() -> None:
        for _ in range(8):
            beats.append(time.monotonic())
            await asyncio.sleep(0.01)

    heart = asyncio.create_task(_heart())
    await _load(
        tmp_path,
        fresh_registry,
        "tool-io",
        _tool_body("io_tool"),
    )
    await heart
    gaps = [later - earlier for earlier, later in zip(beats, beats[1:])]
    assert gaps
    assert min(gaps) < 0.05
    _clear_tool_owners()


def test_plugins_get_missing_id_is_404_not_405():
    from qwenpaw.app.routers.plugins import router as plugins_router

    app = FastAPI()
    app.include_router(plugins_router, prefix="/api")
    app.state.plugin_loader = None
    client = TestClient(app)
    response = client.get("/api/plugins/nonexistent-plugin-12345")
    assert response.status_code == 404
    assert response.status_code != 405


@pytest.mark.asyncio
async def test_disable_then_uninstall_removes_owned_agent_tool(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    _seed_talk_agent(tmp_path, monkeypatch)
    _clear_tool_owners()
    loader, _workspace, _installed = await _load(
        tmp_path,
        fresh_registry,
        "keep-a",
        _tool_body("keep_tool"),
    )
    _write_plugin(
        tmp_path / "plugins" / "solo-b",
        "solo-b",
        body=_tool_body("solo_tool"),
    )
    manifest_b = PluginManifest.from_dict(
        json.loads(
            (tmp_path / "plugins" / "solo-b" / "plugin.json").read_text(
                encoding="utf-8",
            ),
        ),
    )
    await loader.load_plugin(manifest_b, tmp_path / "plugins" / "solo-b")
    await loader.activate_plugin_unlocked("solo-b")
    assert {"keep_tool", "solo_tool"} <= _agent_tool_names()
    await loader.unload_plugin(
        "solo-b",
        delete_files=False,
        mode=UnloadMode.UNLOAD,
    )
    assert loader.get_loaded_plugin("solo-b") is None
    assert {"keep_tool", "solo_tool"} <= _agent_tool_names()
    await loader.unload_plugin(
        "solo-b",
        delete_files=True,
        mode=UnloadMode.UNINSTALL,
    )
    names = _agent_tool_names()
    assert "solo_tool" not in names
    assert "keep_tool" in names
    _clear_tool_owners()


@pytest.mark.asyncio
async def test_inventory_only_uninstall_removes_owned_agent_tool(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    from qwenpaw.config.config import BuiltinToolConfig, load_agent_config
    from qwenpaw.config.config import save_agent_config
    from qwenpaw.plugins.provision import save_inventory

    _seed_talk_agent(tmp_path, monkeypatch)
    agent_cfg = load_agent_config("talk")
    agent_cfg.tools.builtin_tools["solo_tool"] = BuiltinToolConfig(
        name="solo_tool",
        description="solo",
    )
    agent_cfg.tools.builtin_tools["keep_tool"] = BuiltinToolConfig(
        name="keep_tool",
        description="keep",
    )
    save_agent_config("talk", agent_cfg)
    save_inventory(
        "solo-only",
        {
            "plugin_id": "solo-only",
            "locations": {},
            "tools": {"solo_tool": {"factory": {"description": "solo"}}},
            "provisions": [],
        },
    )
    loader = PluginLoader(plugin_dirs=[tmp_path / "plugins"])
    loader.registry = fresh_registry
    assert loader.get_loaded_plugin("solo-only") is None
    await loader.unload_plugin(
        "solo-only",
        delete_files=True,
        mode=UnloadMode.UNINSTALL,
    )
    names = _agent_tool_names()
    assert "solo_tool" not in names
    assert "keep_tool" in names


@pytest.mark.asyncio
async def test_default_load_activates_register_is_not_active(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    loader, workspace, installed = await _load(
        tmp_path,
        fresh_registry,
        "reg-only",
        "api.register_slash_command('ping', lambda c, a: None)",
        activate=False,
    )
    record = loader.get_loaded_plugin("reg-only")
    assert record is not None
    assert record.status == "registered"
    assert "ping" not in workspace.plugins.slash_command_registry.names()
    await loader.activate_plugin_unlocked("reg-only")
    assert record.status == "active"
    assert "ping" in workspace.plugins.slash_command_registry.names()
    await loader.unload_plugin("reg-only", delete_files=False)
    manifest = PluginManifest.from_dict(
        json.loads((installed / "plugin.json").read_text(encoding="utf-8")),
    )
    again = await loader.load_plugin(manifest, installed)
    assert again.status == "active"
    assert "ping" in workspace.plugins.slash_command_registry.names()


@pytest.mark.asyncio
async def test_unquiescent_repair_does_not_drop_instance(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    loader, _workspace, _installed = await _load(
        tmp_path,
        fresh_registry,
        "fix-busy",
        "api.register_slash_command('kept', lambda c, a: None)",
    )
    record = loader.get_loaded_plugin("fix-busy")
    record.status = "failed"
    record.enabled = False
    inst = loader.lifecycle.get_instance("fix-busy")
    inst.mark_failed("missing dep")
    original = inst

    async def _busy() -> UnloadReport:
        return UnloadReport(
            plugin_id="fix-busy",
            mode=UnloadMode.UNLOAD,
            clean=False,
            quiescent=False,
            needs_restart=True,
            errors=["thread still running"],
        )

    monkeypatch.setattr(inst, "teardown_runtime", _busy)
    repaired = await loader.repair_dependencies("fix-busy")
    assert repaired.status == "failed"
    assert loader.lifecycle.get_instance("fix-busy") is original
    assert any("quiescent" in str(item) for item in repaired.diagnostics)


@pytest.mark.asyncio
async def test_activate_failure_rolls_back_new_agent_tools(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    _seed_talk_agent(tmp_path, monkeypatch)
    _clear_tool_owners()
    body = (
        _tool_body("ghost_tool") + "\n"
        "        def _boom():\n"
        "            raise RuntimeError('startup boom')\n"
        "        api.register_startup_hook('boom', _boom, priority=90)"
    )
    installed = _write_plugin(
        tmp_path / "plugins" / "ghost",
        "ghost",
        body=body,
    )
    loader = PluginLoader(plugin_dirs=[tmp_path / "plugins"])
    loader.registry = fresh_registry
    manifest = PluginManifest.from_dict(
        json.loads((installed / "plugin.json").read_text(encoding="utf-8")),
    )
    record = await loader.load_plugin(manifest, installed)
    assert record is loader.get_loaded_plugin("ghost")
    assert record is not None
    assert record.status == "failed"
    assert "ghost_tool" not in _agent_tool_names()
    tools = load_inventory("ghost").get("tools") or {}
    assert "ghost_tool" not in tools
    _clear_tool_owners()


@pytest.mark.asyncio
async def test_skill_install_failure_fails_activate(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    workspace = tmp_path / "ws"
    workspace.mkdir()
    skills = tmp_path / "plugin-skills"
    skill_aaa = skills / "aaa"
    skill_zzz = skills / "zzz"
    skill_aaa.mkdir(parents=True)
    skill_zzz.mkdir(parents=True)
    (skill_aaa / "SKILL.md").write_text("# aaa\n", encoding="utf-8")
    (skill_zzz / "SKILL.md").write_text("# zzz\n", encoding="utf-8")
    monkeypatch.setattr(
        "qwenpaw.agents.skill_system.registry.list_workspaces",
        lambda: [{"workspace_dir": str(workspace), "agent_id": "talk"}],
    )
    from qwenpaw.plugins import provision as provision_mod

    real_provision = provision_mod.provision_files

    def _fail_zzz(plugin_id, src, dest, version):
        if Path(src).name == "zzz" or Path(dest).name == "zzz":
            raise RuntimeError("zzz failed")
        return real_provision(plugin_id, src, dest, version)

    monkeypatch.setattr(provision_mod, "provision_files", _fail_zzz)
    body = (
        "from pathlib import Path\n"
        f"        api.register_skill_provider(Path({str(skills)!r}))"
    )
    installed = _write_plugin(
        tmp_path / "plugins" / "skiller-fail",
        "skiller-fail",
        body=body,
    )
    loader = PluginLoader(plugin_dirs=[tmp_path / "plugins"])
    loader.registry = fresh_registry
    manifest = PluginManifest.from_dict(
        json.loads((installed / "plugin.json").read_text(encoding="utf-8")),
    )
    record = await loader.load_plugin(manifest, installed)
    assert record is loader.get_loaded_plugin("skiller-fail")
    assert record is not None
    assert record.status == "failed"
    inst = loader.lifecycle.get_instance("skiller-fail")
    assert inst is None or inst.activated is False
    from qwenpaw.agents.skill_system.store import get_workspace_skills_dir

    copied = get_workspace_skills_dir(workspace)
    assert not (copied / "aaa").exists()
    assert not (copied / "zzz").exists()
    loc = load_inventory("skiller-fail").get("locations") or {}
    assert not any(Path(key).name in {"aaa", "zzz"} for key in loc)
    migrating = [
        row
        for row in loc.values()
        if (row or {}).get("migrating")
        and (row.get("migrating") or {}).get("status") != "committed"
    ]
    assert not migrating


@pytest.mark.asyncio
async def test_unloaded_force_skips_copy_on_case_alias(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path / "work")
    plugins = tmp_path / "plugins"
    if not _volume_is_case_insensitive(plugins):
        pytest.skip("volume is case-sensitive")
    installed = _write_plugin(plugins / "CasePlugin", "CasePlugin")
    alias = plugins / "caseplugin"
    assert same_location(installed, alias)
    marker = installed / "unique.txt"
    marker.write_text("keep-me", encoding="utf-8")
    loader = PluginLoader(plugin_dirs=[plugins])
    loader.registry = fresh_registry
    record = await loader.load_plugin_from_path(alias, force=True)
    assert installed.exists()
    assert marker.exists()
    assert marker.read_text(encoding="utf-8") == "keep-me"
    assert record.status == "active"
    assert (installed / "plugin.json").exists()


@pytest.mark.asyncio
async def test_meta_only_tool_is_not_written_to_agents(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    talk, other = _seed_two_agents(tmp_path, monkeypatch)
    _clear_tool_owners()
    installed = _write_plugin(tmp_path / "plugins" / "meta-only", "meta-only")
    plugin_json = installed / "plugin.json"
    data = json.loads(plugin_json.read_text(encoding="utf-8"))
    data["meta"] = {"tools": [{"name": "meta_ghost"}]}
    plugin_json.write_text(json.dumps(data), encoding="utf-8")
    loader = PluginLoader(plugin_dirs=[tmp_path / "plugins"])
    loader.registry = fresh_registry
    manifest = PluginManifest.from_dict(data)
    record = await loader.load_plugin(manifest, installed)
    assert record.status == "active"
    assert "meta_ghost" not in _raw_agent_tools(talk)
    assert "meta_ghost" not in _raw_agent_tools(other)
    _clear_tool_owners()


@pytest.mark.asyncio
async def test_register_tool_writes_all_agents_and_uninstall_clears(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    _seed_two_agents(tmp_path, monkeypatch)
    _clear_tool_owners()
    installed = _write_plugin(
        tmp_path / "plugins" / "all-agents",
        "all-agents",
        body=_tool_body("shared_everywhere"),
    )
    loader = PluginLoader(plugin_dirs=[tmp_path / "plugins"])
    loader.registry = fresh_registry
    workspace = _slash_workspace()
    fresh_registry.projector = WorkspaceProjector(
        live_workspaces=lambda: [workspace],
    )
    fresh_registry.set_workspace_manager(
        SimpleNamespace(agents={"talk": workspace}),
    )
    manifest = PluginManifest.from_dict(
        json.loads((installed / "plugin.json").read_text(encoding="utf-8")),
    )
    record = await loader.load_plugin(manifest, installed)
    assert record.status == "active"
    assert "shared_everywhere" in _agent_tool_names("talk")
    assert "shared_everywhere" in _agent_tool_names("other")
    await loader.unload_plugin(
        "all-agents",
        delete_files=True,
        mode=UnloadMode.UNINSTALL,
    )
    assert "shared_everywhere" not in _agent_tool_names("talk")
    assert "shared_everywhere" not in _agent_tool_names("other")
    _clear_tool_owners()


@pytest.mark.asyncio
async def test_reload_failed_activate_restores_tool_description(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    _seed_talk_agent(tmp_path, monkeypatch)
    _clear_tool_owners()
    loader, _workspace, installed = await _load(
        tmp_path,
        fresh_registry,
        "desc-reload",
        _tool_body("reload_demo_tool", "v1-desc"),
    )
    assert _tool_description("reload_demo_tool") == "v1-desc"
    assert (
        load_inventory("desc-reload")["tools"]["reload_demo_tool"]["factory"][
            "description"
        ]
        == "v1-desc"
    )
    _write_plugin(
        installed,
        "desc-reload",
        body=(
            _tool_body("reload_demo_tool", "v2-desc") + "\n"
            "        def _boom():\n"
            "            raise RuntimeError('startup boom')\n"
            "        api.register_startup_hook('boom', _boom, priority=90)"
        ),
    )
    report = await loader.lifecycle.reload("desc-reload")
    assert not report.ok
    assert _tool_description("reload_demo_tool") == "v1-desc"
    assert (
        load_inventory("desc-reload")["tools"]["reload_demo_tool"]["factory"][
            "description"
        ]
        == "v1-desc"
    )
    _write_plugin(
        installed,
        "desc-reload",
        body=_tool_body("reload_demo_tool", "v1-desc"),
    )
    report = await loader.lifecycle.reload("desc-reload")
    assert report.ok
    assert _tool_description("reload_demo_tool") == "v1-desc"
    _clear_tool_owners()


@pytest.mark.asyncio
async def test_update_config_failed_activate_restores_tool_description(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    monkeypatch.setattr(
        "qwenpaw.plugins.settings.persist_plugin_settings",
        lambda *args, **kwargs: None,
    )
    _seed_talk_agent(tmp_path, monkeypatch)
    _clear_tool_owners()
    body = (
        "def _demo():\n"
        "            return 'ok'\n"
        "        api.register_tool(\n"
        "            'cfg_demo_tool', _demo,\n"
        "            description=api.config.get('desc', 'v1-desc'),\n"
        "        )\n"
        "        if api.config.get('boom'):\n"
        "            def _boom():\n"
        "                raise RuntimeError('startup boom')\n"
        "            api.register_startup_hook('boom', _boom, priority=90)"
    )
    loader, _workspace, _installed = await _load(
        tmp_path,
        fresh_registry,
        "desc-cfg",
        body,
        config={"desc": "v1-desc"},
    )
    assert _tool_description("cfg_demo_tool") == "v1-desc"
    failed = await loader.lifecycle.update_config(
        "desc-cfg",
        {"desc": "v2-desc", "boom": True},
    )
    assert not failed.ok
    assert _tool_description("cfg_demo_tool") == "v1-desc"
    assert (
        load_inventory("desc-cfg")["tools"]["cfg_demo_tool"]["factory"][
            "description"
        ]
        == "v1-desc"
    )
    ok = await loader.lifecycle.update_config(
        "desc-cfg",
        {"desc": "v1-desc"},
    )
    assert ok.ok
    assert _tool_description("cfg_demo_tool") == "v1-desc"
    _clear_tool_owners()


@pytest.mark.asyncio
async def test_reload_drops_unregistered_tools_without_meta(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    _seed_two_agents(tmp_path, monkeypatch)
    _clear_tool_owners()
    body_v1 = _tools_body(("drop_old_tool", "old"), ("drop_keep_tool", "keep"))
    loader, _workspace, installed = await _load(
        tmp_path,
        fresh_registry,
        "drop-tools",
        body_v1,
    )
    assert {"drop_old_tool", "drop_keep_tool"} <= _agent_tool_names("talk")
    assert {"drop_old_tool", "drop_keep_tool"} <= _agent_tool_names("other")
    incoming = _write_plugin(
        tmp_path / "incoming-drop-tools",
        "drop-tools",
        body=_tool_body("drop_keep_tool", "keep"),
    )
    report = await loader.lifecycle.reload(
        "drop-tools",
        new_source=incoming,
    )
    assert report.ok
    assert "drop_old_tool" not in _agent_tool_names("talk")
    assert "drop_old_tool" not in _agent_tool_names("other")
    assert "drop_keep_tool" in _agent_tool_names("talk")
    assert "drop_keep_tool" in _agent_tool_names("other")
    assert "drop_old_tool" not in (
        load_inventory("drop-tools").get("tools") or {}
    )
    other = _write_plugin(
        tmp_path / "plugins" / "other-owner",
        "other-owner",
        body=_tool_body("drop_old_tool", "other"),
    )
    manifest_b = PluginManifest.from_dict(
        json.loads((other / "plugin.json").read_text(encoding="utf-8")),
    )
    record_b = await loader.load_plugin(manifest_b, other)
    assert record_b.status == "active"
    await loader.unload_plugin(
        "drop-tools",
        delete_files=True,
        mode=UnloadMode.UNINSTALL,
    )
    assert "drop_old_tool" in _agent_tool_names("talk")
    assert "drop_keep_tool" not in _agent_tool_names("talk")
    _clear_tool_owners()
    del installed


@pytest.mark.asyncio
async def test_force_install_drops_unregistered_tools_without_meta(
    tmp_path: Path,
    fresh_registry,
    monkeypatch,
):
    _seed_two_agents(tmp_path, monkeypatch)
    _clear_tool_owners()
    loader, _workspace, _installed = await _load(
        tmp_path,
        fresh_registry,
        "force-drop",
        _tools_body(("force_old_tool", "old"), ("force_keep_tool", "keep")),
    )
    incoming = _write_plugin(
        tmp_path / "incoming-force-drop",
        "force-drop",
        body=_tool_body("force_keep_tool", "keep"),
    )
    record = await loader.load_plugin_from_path(incoming, force=True)
    assert record.status == "active"
    assert "force_old_tool" not in _agent_tool_names("talk")
    assert "force_old_tool" not in _agent_tool_names("other")
    assert "force_keep_tool" in _agent_tool_names("talk")
    assert "force_old_tool" not in (
        load_inventory("force-drop").get("tools") or {}
    )
    _clear_tool_owners()
