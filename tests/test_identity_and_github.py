from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from dev_space.control_plane.github import (
    GitHubAuthenticationError,
    GitHubAuthorizationError,
    GitHubClient,
    GitHubError,
    GitHubResponseError,
    SubprocessGhRunner,
)
from dev_space.control_plane.models import ActorRole
from dev_space.control_plane.policy import load_policy
from dev_space.identity import apply_identity_lane, preflight_identity

pytestmark = pytest.mark.no_observability


class IdentityClient:
    def __init__(self, login="kz-harbringer", permission="write"):
        self.login = login
        self.permission = permission
        self.endpoints = []

    def current_user(self):
        return self.login

    def rest(self, endpoint, **kwargs):
        self.endpoints.append(endpoint)
        return {"permission": self.permission}


def completed(args, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args, returncode, stdout, stderr)


def test_identity_lane_sets_and_clears_isolated_environment(monkeypatch):
    monkeypatch.setenv("GH_CONFIG_DIR", "old")
    apply_identity_lane("agent")
    assert os.environ["GH_CONFIG_DIR"].endswith(".config/dev-space/agent-gh")
    assert os.environ["GIT_AUTHOR_NAME"] == "kz-harbringer"

    apply_identity_lane("human")
    assert "GH_CONFIG_DIR" not in os.environ
    assert "GIT_AUTHOR_NAME" not in os.environ

    with pytest.raises(ValueError, match="unknown identity lane"):
        apply_identity_lane("mystery")


def test_identity_preflight_verifies_git_ssh_actor_and_fork_permission(monkeypatch):
    configured = load_policy(Path(__file__).parents[1])

    def fake_run(arguments, **kwargs):
        if arguments[:2] == ["git", "-C"] and arguments[-2:] == ["--get", "user.name"]:
            return completed(arguments, stdout="kz-harbringer\n")
        if arguments[:2] == ["git", "-C"] and arguments[-2:] == ["--get", "user.email"]:
            return completed(
                arguments, stdout="kz-harbringer@users.noreply.github.com\n"
            )
        if arguments[0] == "ssh":
            return completed(
                arguments,
                returncode=1,
                stderr="Hi kz-harbringer! Authentication succeeded.\n",
            )
        raise AssertionError(arguments)

    monkeypatch.setattr(subprocess, "run", fake_run)
    client = IdentityClient()
    report = preflight_identity(
        configured, ActorRole.WORKER, Path(__file__).parents[1], client=client
    )

    assert report.healthy is True
    assert [check.name for check in report.checks] == [
        "github_actor",
        "commit_name",
        "commit_email",
        "ssh_actor",
        "repository_permission",
    ]
    assert client.endpoints == [
        "repos/kz-harbringer/dev-space/collaborators/kz-harbringer/permission"
    ]


def test_identity_preflight_reports_mismatches_without_ssh(monkeypatch):
    configured = load_policy(Path(__file__).parents[1])
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda arguments, **kwargs: completed(arguments, returncode=1),
    )
    report = preflight_identity(
        configured,
        ActorRole.WORKER,
        Path(__file__).parents[1],
        client=IdentityClient(login="wrong", permission="read"),
        verify_ssh=False,
    )

    assert report.healthy is False
    assert sum(not check.ok for check in report.checks) == 4


@pytest.mark.parametrize(
    ("stderr", "exception"),
    [
        ("not logged into any GitHub hosts", GitHubAuthenticationError),
        ("GraphQL: Resource not accessible by integration", GitHubAuthorizationError),
        ("network unavailable", GitHubError),
    ],
)
def test_subprocess_gh_runner_classifies_failures(monkeypatch, stderr, exception):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: completed(args, returncode=1, stderr=stderr),
    )
    with pytest.raises(exception):
        SubprocessGhRunner().run(["api", "user"])
    assert stderr


def test_subprocess_gh_runner_and_rest_payload(monkeypatch):
    calls = []

    def fake_run(arguments, **kwargs):
        calls.append((arguments, kwargs))
        return completed(arguments, stdout='{"ok":true}')

    monkeypatch.setattr(subprocess, "run", fake_run)
    output = SubprocessGhRunner().run(["api", "user"], "input")
    client = GitHubClient(SubprocessGhRunner())
    response = client.rest("repos/o/r", method="PATCH", payload={"x": 1})

    assert output == '{"ok":true}'
    assert response == {"ok": True}
    assert calls[1][0] == [
        "gh",
        "api",
        "repos/o/r",
        "--method",
        "PATCH",
        "--input",
        "-",
    ]
    assert calls[1][1]["input"] == '{"x": 1}'


def test_github_client_rejects_scalar_and_missing_user_login():
    class Runner:
        def __init__(self, value):
            self.value = value

        def run(self, arguments, input_text=None):
            return self.value

    with pytest.raises(GitHubResponseError, match="non-container"):
        GitHubClient(Runner("1")).rest("user")
    with pytest.raises(GitHubResponseError, match="missing login"):
        GitHubClient(Runner("{}")).current_user()
    assert Runner("{}").value == "{}"
