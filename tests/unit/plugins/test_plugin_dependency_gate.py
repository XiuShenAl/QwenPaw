# -*- coding: utf-8 -*-
"""Protect core dependencies without installing or changing packages."""

import sys
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest
from packaging.requirements import Requirement

from qwenpaw.plugins.dependency_gate import (
    DependencyGate,
    hits_imported_host_package,
)


@pytest.mark.parametrize(
    "package",
    ["openai", "agentscope", "reme-ai", "apscheduler"],
)
@pytest.mark.parametrize("frozen", [False, True])
def test_conflicting_core_dependency_is_blocked(
    tmp_path: Path,
    package: str,
    frozen: bool,
):
    requirements = tmp_path / "requirements.txt"
    declaration = f"{package}<0.1"
    requirements.write_text(declaration + "\n", encoding="utf-8")
    with (
        patch(
            "qwenpaw.plugins.dependency_gate._dist_version",
            return_value="2.0.0",
        ),
        patch(
            "qwenpaw.plugins.dependency_gate._is_frozen",
            return_value=frozen,
        ),
    ):
        decision = DependencyGate().evaluate(
            requirements,
            allow_install=True,
            plugin_id="test-plugin",
        )
    assert not decision.allow_install
    assert not decision.already_satisfied
    assert decision.host_conflicts == [declaration]
    assert decision.require_restart


@pytest.mark.parametrize(
    "package",
    ["openai", "agentscope", "reme-ai", "apscheduler"],
)
def test_satisfied_core_dependency_needs_no_install(
    tmp_path: Path,
    package: str,
):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text(f"{package}>=1\n", encoding="utf-8")
    with patch(
        "qwenpaw.plugins.dependency_gate._dist_version",
        return_value="2.0.0",
    ):
        decision = DependencyGate().evaluate(
            requirements,
            allow_install=True,
            plugin_id="test-plugin",
        )
    assert decision.already_satisfied
    assert not decision.allow_install
    assert not decision.host_conflicts
    assert not decision.require_restart


def test_reme_distribution_detects_loaded_module_without_metadata():
    with (
        patch.dict(sys.modules, {"reme": ModuleType("reme")}),
        patch(
            "qwenpaw.plugins.dependency_gate._dist_version",
            side_effect=PackageNotFoundError("reme-ai"),
        ),
        patch(
            "qwenpaw.plugins.dependency_gate._is_frozen",
            return_value=False,
        ),
    ):
        assert hits_imported_host_package(Requirement("reme-ai<0.1"))
