import typer
import structlog
from dev_space import executor
from dev_space.aop import plugin_command

app = typer.Typer(help="Git Worktree Subcommands")
logger = structlog.get_logger()


@app.command()
@plugin_command()
def add(path: str, branch: str):
    """
    Creates a new git worktree using the Rust execution core.
    """
    try:
        result = executor.execute_agent_command("git", ["worktree", "add", path, branch])
        logger.info("Worktree added", output=result.strip())
    except Exception as e:  # noqa: BLE001
        logger.error("Worktree add failed", error=str(e))
        raise typer.Exit(code=1)


@app.command()
@plugin_command()
def list():
    """
    Lists current git worktrees.
    """
    try:
        result = executor.execute_agent_command("git", ["worktree", "list"])
        logger.info("Worktrees", output=result.strip())
    except Exception as e:  # noqa: BLE001
        logger.error("Worktree list failed", error=str(e))
        raise typer.Exit(code=1)


@app.command()
@plugin_command()
def remove(path: str):
    """
    Removes a git worktree.
    """
    try:
        result = executor.execute_agent_command("git", ["worktree", "remove", path])
        logger.info("Worktree removed", output=result.strip())
    except Exception as e:  # noqa: BLE001
        logger.error("Worktree remove failed", error=str(e))
        raise typer.Exit(code=1)
