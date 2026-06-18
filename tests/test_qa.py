import pytest
from unittest.mock import patch

from typer.testing import CliRunner
from dev_space.cli import app

runner = CliRunner()


@pytest.mark.no_observability
@patch("dev_space.executor.execute_agent_command")
def test_qa_scan(mock_exec, snapshot):
    """
    Validates that dev-space qa scan executes all sub-processes correctly.
    """
    mock_exec.return_value = "Mocked execution success"

    result = runner.invoke(app, ["--format", "json", "qa", "scan"])
    assert result.exit_code == 0
    assert "Mocked execution success" in result.stdout
    assert "QA Scan Passed" in result.stdout


@pytest.mark.no_observability
@patch("dev_space.executor.execute_agent_command")
def test_qa_scan_failure(mock_exec):
    """
    Validates that dev-space qa scan exits on tool failure.
    """
    mock_exec.side_effect = Exception("Ruff failed")

    result = runner.invoke(app, ["--format", "json", "qa", "scan"])
    assert result.exit_code == 1


@pytest.mark.no_observability
@patch("dev_space.executor.execute_agent_command")
def test_qa_enforce(mock_exec, snapshot):
    """
    Validates that dev-space qa enforce executes pytest and mutmut.
    """
    mock_exec.return_value = "Mocked execution success"

    result = runner.invoke(app, ["--format", "json", "qa", "enforce"])
    assert result.exit_code == 0
    assert "Mocked execution success" in result.stdout
    assert "QA Enforcement Passed" in result.stdout


@pytest.mark.no_observability
@patch("dev_space.executor.execute_agent_command")
def test_qa_enforce_failure(mock_exec):
    """
    Validates that dev-space qa enforce exits on tool failure.
    """
    mock_exec.side_effect = Exception("Pytest failed")

    result = runner.invoke(app, ["--format", "json", "qa", "enforce"])
    assert result.exit_code == 1
