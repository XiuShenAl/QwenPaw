# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for ``_api_action_routes.py`` (HTTP/Slash auto-collection)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from qwenpaw.api_action import (
    ManagerBase,
    ManagerRegistry,
    api_action,
)
from qwenpaw.app._api_action_routes import (
    collect_slash_specs_from_api_actions,
    register_http_routes,
)


class _SampleManager(ManagerBase):
    endpoint_prefix = "sample"

    @api_action(methods={"http", "slash"}, http_method="GET")
    async def list_items(self) -> list[str]:
        return ["a", "b"]

    @api_action(methods={"http"}, http_method="POST")
    async def create_item(self, name: str = "") -> dict[str, str]:
        return {"created": name}


def _make_registry() -> ManagerRegistry:
    reg = ManagerRegistry()
    reg.register(_SampleManager, lambda app: _SampleManager())
    return reg


def test_manager_base_collects_api_actions() -> None:
    assert len(_SampleManager._api_actions) == 2
    names = {s.name for s in _SampleManager._api_actions}
    assert names == {"list_items", "create_item"}


def test_collect_slash_specs_filters_slash_only() -> None:
    specs = collect_slash_specs_from_api_actions(_make_registry())
    assert len(specs) == 1
    assert specs[0].name == "list_items"


@pytest.mark.asyncio
async def test_slash_adapter_returns_msg() -> None:
    specs = collect_slash_specs_from_api_actions(_make_registry())
    slash_spec = specs[0]

    ctx = SimpleNamespace(app_services=None)
    msg = await slash_spec.handler(ctx, "")
    assert msg.role == "assistant"
    assert msg.content[0].text  # non-empty


def test_register_http_routes_count() -> None:
    from unittest.mock import MagicMock

    fake_app = MagicMock()
    fake_app.add_api_route = MagicMock()

    count = register_http_routes(fake_app, _make_registry())
    assert count == 2
    assert fake_app.add_api_route.call_count == 2


def test_register_http_routes_paths() -> None:
    from unittest.mock import MagicMock

    fake_app = MagicMock()
    recorded_paths: list[str] = []

    def _track(path: str, *_args: Any, **_kwargs: Any) -> None:
        recorded_paths.append(path)

    fake_app.add_api_route = _track

    register_http_routes(fake_app, _make_registry())
    assert "/sample/list_items" in recorded_paths
    assert "/sample/create_item" in recorded_paths
