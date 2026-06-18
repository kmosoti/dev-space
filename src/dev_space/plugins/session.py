import typer
import structlog
from pathlib import Path
from dev_space.aop import plugin_command

app = typer.Typer(help="Session Orchestration & Git Worktrees (ADR-004)")
logger = structlog.get_logger()


@app.command()
@plugin_command(resource_lock="session")
def start(session_id: str, repos: list[str]):
    """
    Provisions a session jail containing git worktrees for the requested repositories.
    """
    logger.info("Starting session", session_id=session_id, repos=repos)
    session_dir = Path.home() / "dev_space" / "sessions" / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    # In a real async implementation, we'd use asyncio.gather for multiple worktrees.
    # For Phase 3, we just output the directory and create the AGENTS.md context.

    agents_md = session_dir / "AGENTS.md"
    agents_md.write_text(
        f"# Session: {session_id}\n\nIsolated environment provisioned."
    )

    logger.info("Session Provisioned", session_dir=str(session_dir))
