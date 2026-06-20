from __future__ import annotations

import json
from pathlib import Path

import typer

from dev_space.aop import plugin_command
from dev_space.control_plane.project_service import ProjectService
from dev_space.control_plane.project_v2 import snapshot_as_dict

app = typer.Typer(help="GitHub Project v2 control-plane reconciliation")


def _service(repo: Path | None) -> ProjectService:
    return ProjectService.from_repo(repo)


@app.command()
@plugin_command()
def doctor(repo: Path | None = typer.Option(None, "--repo", help="Repository path")):
    """Validate policy, authentication, Project identity, and API capabilities."""
    report = _service(repo).doctor()
    typer.echo(
        json.dumps(
            {
                "healthy": report.healthy,
                "checks": [check.__dict__ for check in report.checks],
            },
            sort_keys=True,
        )
    )
    if not report.healthy:
        raise typer.Exit(code=1)


@app.command("snapshot")
@plugin_command()
def project_snapshot(
    repo: Path | None = typer.Option(None, "--repo", help="Repository path"),
):
    """Emit a normalized full-fidelity Project v2 snapshot."""
    typer.echo(json.dumps(snapshot_as_dict(_service(repo).snapshot()), sort_keys=True))


@app.command()
@plugin_command()
def plan(repo: Path | None = typer.Option(None, "--repo", help="Repository path")):
    """Produce a deterministic, non-mutating reconciliation report."""
    typer.echo(_service(repo).plan().model_dump_json(indent=2))


@app.command()
@plugin_command(resource_lock="project-apply")
def apply(repo: Path | None = typer.Option(None, "--repo", help="Repository path")):
    """Create or reconcile the configured Project v2 without pruning unknown state."""
    before, snapshot = _service(repo).apply()
    typer.echo(
        json.dumps(
            {
                "planned": before.model_dump(mode="json"),
                "project": snapshot_as_dict(snapshot),
            },
            sort_keys=True,
        )
    )
