import typer
import structlog
from dev_space.aop import plugin_command

app = typer.Typer(help="Daemon Lifecycle Management (ADR-006)")
logger = structlog.get_logger()


@app.command()
@plugin_command()
def start(host: str = "127.0.0.1", port: int = 8080):
    """
    Starts the Granian daemon serving the RSGI application.
    """
    try:
        from granian import Granian

        logger.info("Starting Granian daemon...", host=host, port=port)
        server = Granian(
            "dev_space.daemon:rsgi_app",
            address=host,
            port=port,
            interfaces="rsgi",
            workers=1,
        )
        server.serve()
    except Exception as e:  # noqa: BLE001
        logger.error("Failed to start daemon", error=str(e))
        raise typer.Exit(code=1)
