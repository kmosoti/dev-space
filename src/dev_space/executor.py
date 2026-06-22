from dev_space import core


def execute_agent_command(command: str, args: list[str]) -> str:
    """
    Python wrapper over the Rust PyO3 core.
    This provides a patchable target for unittest.mock, as PyO3 C-extensions
    cannot be reliably patched directly in Python.
    """
    return core.execute_agent_command(command, args)


def search_logs(
    plugin: str, query: str = "", from_date: str = "", to_date: str = ""
) -> list[str]:
    """
    Wrapper for the Rust PyO3 log searcher.
    """
    return core.search_logs(plugin, query, from_date, to_date)
