import typer

from .aop import plugin_command, setup_observability
from .config import config
from .identity import apply_identity_lane
from .plugins import qa, gh, session, worktree, daemon, logs

# Note: rich_markup_mode enables rich help formatting
app = typer.Typer(
    name="dev-space",
    help="Agent-first development environment orchestrator.",
    rich_markup_mode="rich",
    no_args_is_help=True,
)

app.add_typer(qa.app, name="qa")
app.add_typer(gh.app, name="gh")
app.add_typer(session.app, name="session")
app.add_typer(worktree.app, name="worktree")
app.add_typer(daemon.app, name="daemon")
app.add_typer(logs.app, name="logs")


@app.callback()
def main(
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress stderr logs."),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Full debug trace to stderr."
    ),
    format: str = typer.Option(
        config.core.default_format,
        "--format",
        help="Structured output format (json|jsonl|md).",
    ),
    rich: bool = typer.Option(
        False, "--rich", help="Force human-friendly Rich output."
    ),
    lane: str = typer.Option(
        config.core.default_lane, "--lane", help="Identity lane (human or agent)."
    ),
):
    """
    Global CLI configuration and AOP setup (ADR-007).
    """
    _ = (quiet, verbose, format, rich, lane)
    setup_observability(quiet=quiet, verbose=verbose)
    apply_identity_lane(lane)


@app.command()
@plugin_command(resource_lock="env-bootstrap")
def bootstrap():
    """
    Bootstraps the isolated dev-space environment.

    [b]Example (agent):[/b]
      $ dev-space bootstrap --format json

    [b]Example Output:[/b]
      {"status": "success", "message": "Environment bootstrapped"}
    """
    import structlog

    log = structlog.get_logger()
    log.info("Bootstrapping dev-space environment", lane=config.core.default_lane)

    from dev_space import executor

    result = executor.execute_agent_command("echo hello", [])
    log.info("Rust core executed", result=result)

    # In agent mode (jsonl), structlog handles the output automatically.
    # We would return or print structured data here.
    typer.echo('{"status": "success", "message": "Environment bootstrapped"}')


@app.command(name="shell-init")
@plugin_command()
def shell_init(shell: str = typer.Argument("bash", help="Target shell (bash or zsh)")):
    """
    Outputs a sourceable shell profile.
    Usage: eval "$(dev-space shell-init bash)"
    """
    _ = shell
    profile = """
export DEV_SPACE_DEFAULT_FORMAT="jsonl"
export DEV_SPACE_LOG_LEVEL="info"

# Basic prompt decoration
if [ -n "$BASH_VERSION" ]; then
    PS1="(dev-space) \\w\\$ "
elif [ -n "$ZSH_VERSION" ]; then
    PROMPT="(dev-space) %~%# "
fi

# Aliases
alias ds="dev-space"
"""
    typer.echo(profile.strip())


if __name__ == "__main__":
    app()
