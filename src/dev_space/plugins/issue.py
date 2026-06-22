from __future__ import annotations

import json
from pathlib import Path

import typer

from dev_space.aop import plugin_command
from dev_space.control_plane.issues import IssueService

app = typer.Typer(help="Planner-owned issue specifications and lifecycle transitions")


@app.command("create-change")
@plugin_command(resource_lock="issue-create")
def create_change(
    parent: int = typer.Option(..., "--parent", min=1, help="Parent Epic number"),
    spec: Path = typer.Option(..., "--spec", exists=True, dir_okay=False),
    repo: Path | None = typer.Option(None, "--repo", help="Repository path"),
):
    """Validate a Markdown change specification and create its Project item."""
    issue = IssueService(repo).create_change(parent, spec.read_text(encoding="utf-8"))
    typer.echo(json.dumps(issue, sort_keys=True))


@app.command("mark-ready")
@plugin_command(resource_lock="issue-transition")
def mark_ready(
    number: int = typer.Argument(..., min=1),
    repo: Path | None = typer.Option(None, "--repo", help="Repository path"),
):
    """Planner-authorize a complete, dependency-ready Agent-ready Change."""
    issue = IssueService(repo).mark_ready(number)
    typer.echo(json.dumps({"issue": issue["number"], "status": "Ready"}))
