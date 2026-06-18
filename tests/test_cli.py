import pytest
from unittest.mock import patch
from typer.testing import CliRunner
from dev_space.cli import app

runner = CliRunner()


@pytest.mark.no_observability
def test_dev_space_help(snapshot):
    """
    Validates that the Typer CLI loads and the help command succeeds.
    Satisfies AST 'snapshot' requirement from conftest.py.
    """
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    snapshot.assert_match(result.stdout)


@pytest.mark.no_observability
def test_dev_space_shell_init():
    """
    Validates that shell initialization outputs standard profile markers.
    Uses @pytest.mark.no_observability because shell-init outputs raw text, not structured logs.
    """
    result = runner.invoke(app, ["shell-init", "bash"])
    assert result.exit_code == 0
    assert "DEV_SPACE_DEFAULT_FORMAT" in result.stdout
    assert "alias ds=" in result.stdout


@pytest.mark.no_observability
@patch("dev_space.executor.execute_agent_command")
def test_dev_space_bootstrap(mock_exec):
    mock_exec.return_value = "hello"
    result = runner.invoke(app, ["--format", "json", "bootstrap"])
    assert result.exit_code == 0
    assert "Environment bootstrapped" in result.stdout
