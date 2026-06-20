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
    result = executor.execute_agent_command("git", ["worktree", "add", path, branch])
    logger.info("Worktree added", output=result.strip())


@app.command()
@plugin_command()
def list():
    """
    Lists current git worktrees.
    """
    result = executor.execute_agent_command("git", ["worktree", "list"])
    logger.info("Worktrees", output=result.strip())


@app.command()
@plugin_command()
def remove(path: str):
    """
    Removes a git worktree.
    """
    result = executor.execute_agent_command("git", ["worktree", "remove", path])
    logger.info("Worktree removed", output=result.strip())
