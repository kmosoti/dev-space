import structlog
import typer
from dev_space import executor
from dev_space.aop import plugin_command

logger = structlog.get_logger()
app = typer.Typer(name="qa", help="Zero-Trust QA Pipeline Plugin (ADR-008).")


@app.command()
@plugin_command(resource_lock="qa-scan")
def scan():
    """
    Executes lightweight static analysis: Ruff, Vulture, and Pip-Audit.
    """
    logger.info("Initiating zero-trust QA static scan...")

    tools = [
        ("ruff check", ["uv", "run", "ruff", "check"]),
        ("ruff format", ["uv", "run", "ruff", "format", "--check"]),
        ("vulture", ["uv", "run", "vulture"]),
        ("pip-audit", ["uv", "run", "pip-audit"]),
    ]

    for name, cmd in tools:
        logger.info(f"Running {name}...")
        result = executor.execute_agent_command(cmd[0], cmd[1:])
        logger.info(f"{name} passed", output=result.strip()[:200])

    logger.info("QA Scan complete. Zero-Trust boundaries validated.")
    typer.echo('{"status": "success", "message": "QA Scan Passed"}')


@app.command()
@plugin_command(resource_lock="qa-enforce")
def enforce():
    """
    Executes heavy enforcement: Pytest and thresholded mutation testing.
    """
    logger.info("Initiating heavy QA enforcement...")

    tools = [
        ("pytest", ["uv", "run", "pytest"]),
        ("mutmut", ["uv", "run", "mutmut", "run"]),
        (
            "mutmut stats",
            ["uv", "run", "mutmut", "export-cicd-stats"],
        ),
        (
            "mutation score",
            [
                "uv",
                "run",
                "python",
                "-m",
                "dev_space.control_plane.mutation_score",
                "--minimum",
                "80",
            ],
        ),
    ]

    for name, cmd in tools:
        logger.info(f"Running {name}...")
        result = executor.execute_agent_command(cmd[0], cmd[1:])
        logger.info(f"{name} passed", output=result.strip()[:200])

    logger.info("QA Enforcement complete. Required mutation score achieved.")
    typer.echo('{"status": "success", "message": "QA Enforcement Passed"}')
