import pytest
from types import SimpleNamespace
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
@patch("dev_space.plugins.session.SessionService")
def test_session_start(mock_service):
    journal = mock_service.return_value.start.return_value
    journal.model_dump_json.return_value = '{"status":"complete"}'
    result = runner.invoke(
        app, ["--format", "json", "session", "start", "123", "--repo", "."]
    )
    assert result.exit_code == 0
    assert "complete" in result.stdout
    mock_service.return_value.start.assert_called_once_with(123)


@pytest.mark.no_observability
@patch("dev_space.plugins.project.ProjectService")
def test_project_commands(mock_service, tmp_path):
    service = mock_service.from_repo.return_value
    service.doctor.return_value = SimpleNamespace(
        healthy=True,
        checks=(SimpleNamespace(name="policy", status="ok", detail="valid"),),
    )
    service.plan.return_value.model_dump_json.return_value = '{"entries":[]}'
    service.snapshot.return_value = SimpleNamespace(
        normalized_json=lambda: '{"title":"dev-space"}\n'
    )
    service.apply.return_value = (
        SimpleNamespace(model_dump=lambda mode: {"entries": []}),
        service.snapshot.return_value,
    )

    doctor = runner.invoke(
        app, ["--lane", "human", "project", "doctor", "--repo", str(tmp_path)]
    )
    plan = runner.invoke(
        app, ["--lane", "human", "project", "plan", "--repo", str(tmp_path)]
    )
    snapshot = runner.invoke(
        app, ["--lane", "human", "project", "snapshot", "--repo", str(tmp_path)]
    )
    apply = runner.invoke(
        app, ["--lane", "human", "project", "apply", "--repo", str(tmp_path)]
    )

    assert doctor.exit_code == 0
    assert plan.exit_code == 0
    assert snapshot.exit_code == 0
    assert apply.exit_code == 0
    assert "dev-space" in snapshot.stdout


@pytest.mark.no_observability
@patch("dev_space.plugins.issue.IssueService")
def test_issue_commands(mock_service, tmp_path):
    specification = tmp_path / "change.md"
    specification.write_text("# Change\n", encoding="utf-8")
    mock_service.return_value.create_change.return_value = {"number": 7}
    mock_service.return_value.mark_ready.return_value = {"number": 7}

    created = runner.invoke(
        app,
        [
            "--lane",
            "human",
            "issue",
            "create-change",
            "--parent",
            "3",
            "--spec",
            str(specification),
            "--repo",
            str(tmp_path),
        ],
    )
    ready = runner.invoke(
        app,
        ["--lane", "human", "issue", "mark-ready", "7", "--repo", str(tmp_path)],
    )

    assert created.exit_code == 0
    assert ready.exit_code == 0
    assert '"number": 7' in created.stdout
    assert '"status": "Ready"' in ready.stdout


@pytest.mark.no_observability
@patch("dev_space.plugins.session.SessionService")
def test_remaining_session_commands(mock_service, tmp_path):
    journal = SimpleNamespace(model_dump_json=lambda indent: '{"status":"complete"}')
    service = mock_service.return_value
    service.handoff.return_value = journal
    service.recover.return_value = journal
    service.status.return_value = {"start": {"status": "complete"}, "handoff": None}

    handoff = runner.invoke(
        app, ["--lane", "agent", "session", "handoff", "9", "--repo", str(tmp_path)]
    )
    status = runner.invoke(
        app, ["--lane", "agent", "session", "status", "9", "--repo", str(tmp_path)]
    )
    recover = runner.invoke(
        app, ["--lane", "agent", "session", "recover", "9", "--repo", str(tmp_path)]
    )
    cleanup = runner.invoke(
        app, ["--lane", "human", "session", "cleanup", "9", "--repo", str(tmp_path)]
    )

    assert handoff.exit_code == 0
    assert status.exit_code == 0
    assert recover.exit_code == 0
    assert cleanup.exit_code == 0
    service.cleanup.assert_called_once_with(9)


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
