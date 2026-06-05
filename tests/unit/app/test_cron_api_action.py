# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for CronManager @api_action decoration (Phase 6 pilot)."""

from __future__ import annotations

from qwenpaw.api_action import ManagerBase


def test_cron_manager_extends_manager_base() -> None:
    from qwenpaw.app.crons.manager import CronManager

    assert issubclass(CronManager, ManagerBase)


def test_cron_manager_has_api_actions() -> None:
    from qwenpaw.app.crons.manager import CronManager

    assert len(CronManager._api_actions) == 3


def test_cron_manager_api_action_names() -> None:
    from qwenpaw.app.crons.manager import CronManager

    names = {s.name for s in CronManager._api_actions}
    assert names == {"list_jobs", "create_or_replace_job", "delete_job"}


def test_cron_manager_methods_include_all_surfaces() -> None:
    from qwenpaw.app.crons.manager import CronManager

    for spec in CronManager._api_actions:
        assert "http" in spec.methods
        assert "cli" in spec.methods
        assert "slash" in spec.methods


def test_cron_manager_endpoint_prefix() -> None:
    from qwenpaw.app.crons.manager import CronManager

    assert CronManager.endpoint_prefix == "crons"
