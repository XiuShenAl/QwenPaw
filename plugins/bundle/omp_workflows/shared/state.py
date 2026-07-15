# -*- coding: utf-8 -*-
"""WorkflowState — state directory and file management for OMP modes."""

from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class WorkflowState:
    """Manage per-instance state directory and files.

    Path convention:
        {workspace_dir}/.qwenpaw/omp_workflows/{mode_name}-{timestamp}/
    """

    def __init__(self, workspace_dir: Path, mode_name: str) -> None:
        self.workspace_dir = workspace_dir
        self.mode_name = mode_name
        self._instance_dir: Path | None = None

    def create_instance(self) -> Path:
        """Create a timestamped instance directory."""
        ts = time.strftime("%Y%m%d-%H%M%S")
        suffix = uuid.uuid4().hex[:6]
        base = self.workspace_dir / ".qwenpaw" / "omp_workflows"
        self._instance_dir = base / f"{self.mode_name}-{ts}-{suffix}"
        self._instance_dir.mkdir(parents=True, exist_ok=True)
        return self._instance_dir

    @property
    def instance_dir(self) -> Path | None:
        return self._instance_dir

    @classmethod
    def from_existing(
        cls,
        workspace_dir: Path,
        mode_name: str,
        instance_dir: Path,
    ) -> WorkflowState:
        """Attach to an already-created instance directory."""
        wf = cls(workspace_dir, mode_name)
        wf._instance_dir = instance_dir
        return wf

    def read_state(self) -> dict[str, Any]:
        """Read state.json, returning empty dict if absent."""
        if not self._instance_dir:
            return {}
        p = self._instance_dir / "state.json"
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Failed to read %s", p, exc_info=True)
            return {}

    def write_state(self, data: dict[str, Any]) -> None:
        """Write state.json."""
        if not self._instance_dir:
            return
        p = self._instance_dir / "state.json"
        p.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def read_prd(self) -> dict[str, Any]:
        """Read prd.json, returning empty dict if absent."""
        if not self._instance_dir:
            return {}
        p = self._instance_dir / "prd.json"
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Failed to read %s", p, exc_info=True)
            return {}

    def append_log(self, entry: str) -> None:
        """Append a line to progress.txt."""
        if not self._instance_dir:
            return
        p = self._instance_dir / "progress.txt"
        with p.open("a", encoding="utf-8") as f:
            f.write(entry + "\n")

    def cleanup(self) -> None:
        """Delete state files, keeping directory and progress.txt."""
        if not self._instance_dir:
            return
        for name in ("state.json", "prd.json"):
            p = self._instance_dir / name
            if p.exists():
                p.unlink()
        logger.info("Cleaned up state files in %s", self._instance_dir)
