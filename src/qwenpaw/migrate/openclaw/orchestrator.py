# -*- coding: utf-8 -*-
"""Orchestrate the full OpenClaw → QwenPaw migration pipeline."""
from __future__ import annotations

import logging
import zipfile
from datetime import datetime
from pathlib import Path

import click

from ...config.utils import load_config
from ...constant import WORKING_DIR
from ..models import ItemStatus, MigrationPlan, MigrationReport
from .detector import detect
from .persona import plan_persona_migration
from .memory import plan_memory_migration
from .providers import plan_provider_migration
from .mcp import plan_mcp_migration
from .channels import plan_channel_migration
from .cron import plan_cron_migration
from .history import plan_history_migration
from .skills import plan_skill_report

logger = logging.getLogger(__name__)

ALL_CATEGORIES = {
    "persona",
    "memory",
    "providers",
    "mcp",
    "channels",
    "cron",
    "history",
}


def run_migration(
    *,
    source_path: Path | None,
    target_agent_id: str,
    openclaw_agent_id: str,
    dry_run: bool,
    include: set[str] | None,
    exclude: set[str] | None,
    migrate_secrets: bool,
    overwrite: bool,
    no_backup: bool,
    yes: bool,
) -> MigrationReport:
    source = detect(source_path, openclaw_agent_id)

    config = load_config()
    if target_agent_id not in config.agents.profiles:
        raise click.ClickException(
            f"Agent '{target_agent_id}' not found. "
            f"Available: {', '.join(config.agents.profiles.keys())}",
        )
    agent_ref = config.agents.profiles[target_agent_id]
    target_workspace = Path(agent_ref.workspace_dir).expanduser()

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    archive_dir = WORKING_DIR / f"migration-archive/openclaw-{ts}"

    plan = MigrationPlan(
        source=source,
        target_agent_id=target_agent_id,
        target_workspace=target_workspace,
        items=[],
    )

    active = (include if include else set(ALL_CATEGORIES)) - (exclude or set())

    converters = {
        "persona": lambda: plan_persona_migration(
            source,
            target_workspace,
            archive_dir,
            overwrite,
        ),
        "memory": lambda: plan_memory_migration(
            source,
            target_workspace,
            archive_dir,
            overwrite,
        ),
        "providers": lambda: plan_provider_migration(
            source,
            target_workspace,
            migrate_secrets,
            overwrite,
        ),
        "mcp": lambda: plan_mcp_migration(source, target_workspace, overwrite),
        "channels": lambda: plan_channel_migration(
            source,
            target_workspace,
            overwrite,
        ),
        "cron": lambda: plan_cron_migration(
            source,
            target_workspace,
            overwrite,
        ),
        "history": lambda: plan_history_migration(
            source,
            target_workspace,
            overwrite,
        ),
    }

    for name, converter_fn in converters.items():
        if name in active:
            plan.items.extend(converter_fn())

    plan.items.extend(plan_skill_report(source))

    _print_preview(plan)

    if dry_run:
        report = _build_report(plan, applied=0, backup_path=None)
        click.echo("\n[dry-run] No files were written.")
        return report

    if not yes:
        if not click.confirm("\nProceed with migration?"):
            raise click.Abort()

    backup_path = None
    if not no_backup:
        backup_path = _create_pre_migration_backup(target_workspace, ts)

    applied, errors = 0, 0
    for item in plan.items:
        if item.status == ItemStatus.OK and item.write_fn:
            try:
                item.write_fn()
                applied += 1
            except Exception as exc:
                item.status = ItemStatus.ERROR
                item.detail = str(exc)
                errors += 1
                logger.warning(
                    "Migration failed for %s: %s",
                    item.source_path,
                    exc,
                )

    report = _build_report(plan, applied=applied, backup_path=backup_path)
    _print_report(report)
    return report


def _build_report(
    plan: MigrationPlan,
    *,
    applied: int,
    backup_path: Path | None,
) -> MigrationReport:
    return MigrationReport(
        plan=plan,
        applied=applied,
        skipped=sum(1 for i in plan.items if i.status == ItemStatus.SKIP),
        conflicts=sum(
            1 for i in plan.items if i.status == ItemStatus.CONFLICT
        ),
        warnings=sum(1 for i in plan.items if i.status == ItemStatus.WARN),
        errors=sum(1 for i in plan.items if i.status == ItemStatus.ERROR),
        backup_path=backup_path,
    )


def _create_pre_migration_backup(
    target_workspace: Path,
    ts: str,
) -> Path | None:
    if not target_workspace.exists():
        return None
    backup_dir = Path(f"{WORKING_DIR}.backups")
    backup_dir.mkdir(parents=True, exist_ok=True)
    zip_path = backup_dir / f"pre-migrate-{ts}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for fp in target_workspace.rglob("*"):
            if fp.is_file():
                zf.write(fp, fp.relative_to(target_workspace))
    click.echo(f"Backup saved: {zip_path}")
    return zip_path


_STATUS_ICON = {
    ItemStatus.OK: "✓",
    ItemStatus.SKIP: "⊘",
    ItemStatus.CONFLICT: "✗",
    ItemStatus.WARN: "⚠",
    ItemStatus.ERROR: "✗",
    ItemStatus.ARCHIVED: "ⓘ",
}


def _print_preview(plan: MigrationPlan) -> None:
    try:
        _print_preview_rich(plan)
    except ImportError:
        _print_preview_plain(plan)


def _print_preview_rich(plan: MigrationPlan) -> None:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel

    console = Console()
    console.print(
        Panel(
            "[bold]QwenPaw Migration Preview[/bold]\n"
            "[dim]OpenClaw → QwenPaw[/dim]",
            expand=False,
        ),
    )
    console.print(f"  Source:  {plan.source.root} ({plan.source.flavor})")
    console.print(
        f"  Agent:   {plan.source.agent_id} → {plan.target_agent_id}",
    )
    console.print(f"  Target:  {plan.target_workspace}\n")

    table = Table(show_header=True, header_style="bold")
    table.add_column("Category", width=10)
    table.add_column("Detail", min_width=30)
    table.add_column("Status", width=10, justify="center")

    status_style = {
        ItemStatus.OK: "green",
        ItemStatus.SKIP: "dim",
        ItemStatus.CONFLICT: "red",
        ItemStatus.WARN: "yellow",
        ItemStatus.ERROR: "red bold",
        ItemStatus.ARCHIVED: "cyan",
    }
    for item in plan.items:
        icon = _STATUS_ICON.get(item.status, "?")
        style = status_style.get(item.status, "")
        table.add_row(
            item.category,
            item.detail,
            f"[{style}]{icon} {item.status.value.upper()}[/{style}]",
        )
    console.print(table)


def _print_preview_plain(plan: MigrationPlan) -> None:
    click.echo("\n=== QwenPaw Migration Preview ===")
    click.echo(f"Source:  {plan.source.root} ({plan.source.flavor})")
    click.echo(f"Agent:   {plan.source.agent_id} → {plan.target_agent_id}")
    click.echo(f"Target:  {plan.target_workspace}\n")
    click.echo(f"{'Category':<12} {'Detail':<40} {'Status':<10}")
    click.echo("-" * 62)
    for item in plan.items:
        icon = _STATUS_ICON.get(item.status, "?")
        click.echo(
            f"{item.category:<12} {item.detail:<40}"
            f" {icon} {item.status.value.upper()}",
        )


def _print_report(report: MigrationReport) -> None:
    try:
        from rich.console import Console
        from rich.panel import Panel

        console = Console()
        lines = [
            f"[bold green]Applied:[/bold green]   {report.applied}",
            f"[dim]Skipped:[/dim]   {report.skipped}",
            f"[yellow]Warnings:[/yellow]  {report.warnings}",
            f"[red]Conflicts:[/red] {report.conflicts}",
            f"[red]Errors:[/red]    {report.errors}",
        ]
        if report.backup_path:
            lines.append(f"[cyan]Backup:[/cyan]    {report.backup_path}")
        console.print(
            Panel("\n".join(lines), title="Migration Report", expand=False),
        )
    except ImportError:
        click.echo("\n=== Migration Report ===")
        click.echo(f"Applied:   {report.applied}")
        click.echo(f"Skipped:   {report.skipped}")
        click.echo(f"Warnings:  {report.warnings}")
        click.echo(f"Conflicts: {report.conflicts}")
        click.echo(f"Errors:    {report.errors}")
        if report.backup_path:
            click.echo(f"Backup:    {report.backup_path}")
