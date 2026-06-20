import typer
import structlog
from dev_space import executor
from dev_space.aop import plugin_command

app = typer.Typer(help="Log Search (ADR-006)")
logger = structlog.get_logger()


@app.command()
@plugin_command()
def search(plugin: str, query: str = "", from_date: str = "", to_date: str = ""):
    """
    Searches logs across live files and .zst archives using the Rust execution core.
    """
    logger.info("Searching logs", plugin=plugin, query=query)
    result = executor.search_logs(plugin, query, from_date, to_date)
    logger.info("Search Results", results=result)
