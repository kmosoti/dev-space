import pytest
from unittest.mock import patch
from typer.testing import CliRunner
from dev_space.cli import app

runner = CliRunner()


@pytest.mark.no_observability
@patch("dev_space.executor.execute_agent_command")
def test_gh_auth_status(mock_exec):
    mock_exec.return_value = "Logged in as human"
    result = runner.invoke(app, ["--format", "json", "gh", "auth-status"])
    assert result.exit_code == 0
    mock_exec.assert_called_with("gh", ["auth", "status"])


@pytest.mark.no_observability
@patch("dev_space.executor.execute_agent_command")
def test_gh_pr(mock_exec):
    mock_exec.return_value = "[]"
    result = runner.invoke(app, ["--format", "json", "gh", "pr"])
    assert result.exit_code == 0
    mock_exec.assert_called_with("gh", ["pr", "list", "--json", "number,title,state"])


@pytest.mark.no_observability
@patch("dev_space.executor.execute_agent_command")
def test_worktree_add(mock_exec):
    mock_exec.return_value = "Added worktree"
    result = runner.invoke(
        app, ["--format", "json", "worktree", "add", "my-path", "my-branch"]
    )
    assert result.exit_code == 0
    mock_exec.assert_called_with("git", ["worktree", "add", "my-path", "my-branch"])


@pytest.mark.no_observability
@patch("dev_space.executor.execute_agent_command")
def test_worktree_list(mock_exec):
    mock_exec.return_value = "worktree list"
    result = runner.invoke(app, ["--format", "json", "worktree", "list"])
    assert result.exit_code == 0
    mock_exec.assert_called_with("git", ["worktree", "list"])


@pytest.mark.no_observability
@patch("dev_space.core.execute_agent_command")
def test_worktree_remove(mock_exec):
    mock_exec.return_value = "Removed worktree"
    result = runner.invoke(app, ["--format", "json", "worktree", "remove", "my-path"])
    assert result.exit_code == 0
    mock_exec.assert_called_with("git", ["worktree", "remove", "my-path"])


@pytest.mark.no_observability
def test_session_start(tmp_path):
    with patch("pathlib.Path.home", return_value=tmp_path):
        result = runner.invoke(
            app, ["--format", "json", "session", "start", "sess-123", "repo1", "repo2"]
        )
        assert result.exit_code == 0
        assert (tmp_path / "dev_space" / "sessions" / "sess-123" / "AGENTS.md").exists()


@pytest.mark.no_observability
@patch("dev_space.executor.execute_agent_command")
def test_plugin_failures(mock_exec):
    mock_exec.side_effect = Exception("Mocked failure")
    
    assert runner.invoke(app, ["gh", "auth-status"]).exit_code == 1
    assert runner.invoke(app, ["gh", "pr"]).exit_code == 1
    assert runner.invoke(app, ["worktree", "add", "p", "b"]).exit_code == 1
    assert runner.invoke(app, ["worktree", "list"]).exit_code == 1
    assert runner.invoke(app, ["worktree", "remove", "p"]).exit_code == 1

@pytest.mark.no_observability
@patch("dev_space.executor.search_logs")
def test_logs_search(mock_search):
    mock_search.return_value = ["line1", "line2"]
    result = runner.invoke(app, ["--format", "json", "logs", "search", "gh"])
    assert result.exit_code == 0
    mock_search.assert_called_once_with("gh", "", "", "")

@pytest.mark.no_observability
@patch("dev_space.executor.search_logs")
def test_logs_search_failure(mock_search):
    mock_search.side_effect = Exception("Search failed")
    result = runner.invoke(app, ["--format", "json", "logs", "search", "gh"])
    assert result.exit_code == 1

@pytest.mark.no_observability
def test_logs_tail():
    result = runner.invoke(app, ["--format", "json", "logs", "tail", "gh"])
    assert result.exit_code == 0

