import typer
import structlog
from dev_space import executor
from dev_space.aop import plugin_command

app = typer.Typer(help="GitHub Subcommands (ADR-002)")
logger = structlog.get_logger()


@app.command()
@plugin_command()
def auth_status():
    """
    Checks the GitHub authentication status for the current identity lane.
    """
    result = executor.execute_agent_command("gh", ["auth", "status"])
    logger.info("GitHub Auth Status", output=result.strip())


@app.command()
@plugin_command()
def pr():
    """
    Lists Pull Requests using the underlying GH CLI.
    """
    result = executor.execute_agent_command(
        "gh", ["pr", "list", "--json", "number,title,state"]
    )
    logger.info("GitHub PR List", prs=result.strip())
