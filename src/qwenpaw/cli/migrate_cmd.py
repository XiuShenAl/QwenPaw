# -*- coding: utf-8 -*-
"""CLI commands for migrating configurations from other platforms."""
from __future__ import annotations

import click


@click.group("migrate")
def migrate_group():
    """Migrate configurations from other platforms to QwenPaw."""


@migrate_group.command("openclaw")
@click.option(
    "--source",
    type=click.Path(exists=False),
    default=None,
    help="OpenClaw installation directory (default: auto-detect)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Preview changes without writing any files",
)
@click.option(
    "--agent-id",
    default="default",
    help="Target QwenPaw agent ID",
)
@click.option(
    "--include",
    default=None,
    help="Comma-separated categories to include (e.g. persona,memory,mcp)",
)
@click.option(
    "--exclude",
    default=None,
    help="Comma-separated categories to exclude (default: history)",
)
@click.option(
    "--migrate-secrets",
    is_flag=True,
    default=False,
    help="Include API keys in migration",
)
@click.option(
    "--overwrite",
    is_flag=True,
    default=False,
    help="Overwrite existing files",
)
@click.option(
    "--no-backup",
    is_flag=True,
    default=False,
    help="Skip pre-migration backup",
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    default=False,
    help="Skip confirmation prompt",
)
@click.option(
    "--openclaw-agent",
    default="main",
    help="OpenClaw agent ID to migrate",
)
def openclaw_cmd(
    source,
    dry_run,
    agent_id,
    include,
    exclude,
    migrate_secrets,
    overwrite,
    no_backup,
    yes,
    openclaw_agent,
):
    """Migrate OpenClaw configuration to QwenPaw."""
    from pathlib import Path

    from qwenpaw.migrate.openclaw.orchestrator import run_migration

    include_set = set(include.split(",")) if include else None
    exclude_set = set(exclude.split(",")) if exclude else {"history"}
    source_path = Path(source) if source else None

    run_migration(
        source_path=source_path,
        target_agent_id=agent_id,
        openclaw_agent_id=openclaw_agent,
        dry_run=dry_run,
        include=include_set,
        exclude=exclude_set,
        migrate_secrets=migrate_secrets,
        overwrite=overwrite,
        no_backup=no_backup,
        yes=yes,
    )
