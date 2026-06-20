from __future__ import annotations

import json
from pathlib import Path

import typer

from dev_space.aop import plugin_command
from dev_space.control_plane.sessions import SessionService

app = typer.Typer(help="Issue-scoped worker sessions, worktrees, and draft-PR handoff")


@app.command()
@plugin_command(resource_lock="session")
def start(
    number: int = typer.Argument(..., min=1),
    repo: Path | None = typer.Option(None, "--repo", help="Repository path"),
):
    """Start one isolated worker session for a Ready, Agent-ready issue."""
    journal = SessionService(repo).start(number)
    typer.echo(journal.model_dump_json(indent=2))


@app.command()
@plugin_command(resource_lock="session")
def handoff(
    number: int = typer.Argument(..., min=1),
    repo: Path | None = typer.Option(None, "--repo", help="Repository path"),
):
    """Verify, push, and create or update one draft pull request."""
    journal = SessionService(repo).handoff(number)
    typer.echo(journal.model_dump_json(indent=2))


@app.command()
@plugin_command()
def status(
    number: int = typer.Argument(..., min=1),
    repo: Path | None = typer.Option(None, "--repo", help="Repository path"),
):
    """Inspect durable start and handoff state."""
    typer.echo(json.dumps(SessionService(repo).status(number), sort_keys=True))


@app.command()
@plugin_command(resource_lock="session")
def recover(
    number: int = typer.Argument(..., min=1),
    repo: Path | None = typer.Option(None, "--repo", help="Repository path"),
):
    """Resume an interrupted session operation from its journal."""
    journal = SessionService(repo).recover(number)
    typer.echo(journal.model_dump_json(indent=2))


@app.command()
@plugin_command(resource_lock="session")
def cleanup(
    number: int = typer.Argument(..., min=1),
    repo: Path | None = typer.Option(None, "--repo", help="Repository path"),
):
    """Planner-authorized cleanup after remote work is resolved."""
    SessionService(repo).cleanup(number)
    typer.echo(json.dumps({"issue": number, "cleaned": True}))
