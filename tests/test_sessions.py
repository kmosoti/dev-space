from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from dev_space.control_plane.journal import JournalStore, OperationStatus
from dev_space.control_plane.models import LifecycleState, VerificationPolicy
from dev_space.control_plane.policy import load_policy
from dev_space.control_plane.project_v2 import ProjectItemSnapshot
from dev_space.control_plane.sessions import (
    SessionError,
    SessionService,
    _slug,
    default_worktree_root,
)
from dev_space.control_plane.specification import (
    parse_change_specification,
    render_change_specification,
)

SPECIFICATION = (Path(__file__).parent / "fixtures" / "change-spec.md").read_text(
    encoding="utf-8"
)

pytestmark = pytest.mark.no_observability


class SessionClient:
    def __init__(self):
        self.login = "kz-harbringer"
        self.calls = []

    def current_user(self):
        return self.login

    def rest(self, endpoint, *, method="GET", payload=None):
        self.calls.append((endpoint, method, payload))
        if "pulls?" in endpoint:
            return []
        return payload or {}


class SessionIssues:
    def __init__(self, body):
        self.body = body
        self.states = []
        self.policy = None
        self.issues = self

    def issue_with_project_item(self, number):
        return self.get(number), ProjectItemSnapshot(
            id="ITEM",
            type="ISSUE",
            repository="kmosoti/dev-space",
            number=number,
            title="Add control-plane contracts",
            field_values={"Status": "Ready", "Execution": "Agent-ready"},
        )

    def get(self, number):
        return {
            "number": number,
            "title": "Add control-plane contracts",
            "body": self.body,
        }

    def set_project_state(self, number, state, *, development_branch=None):
        self.states.append((number, state, development_branch))

    @staticmethod
    def _parent_from_body(body):
        return 100


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def session_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "Kennedy Mosoti")
    git(repo, "config", "user.email", "47609243+kmosoti@users.noreply.github.com")
    policy_source = Path(__file__).parents[1] / ".dev-space" / "project.toml"
    policy_target = repo / ".dev-space" / "project.toml"
    policy_target.parent.mkdir()
    policy_target.write_text(
        policy_source.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (repo / "README.md").write_text("session fixture\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "fixture")
    return repo


def service(session_repo, tmp_path):
    configured = load_policy(session_repo)
    client = SessionClient()
    instance = SessionService(
        session_repo,
        policy=configured,
        policy_commit=git(session_repo, "rev-parse", "HEAD"),
        client=client,
        journal_store=JournalStore(tmp_path / "state"),
        worktree_root=tmp_path / "worktrees",
        verify_identity=False,
    )
    body = render_change_specification(parse_change_specification(SPECIFICATION, 100))
    instance.issue_service = SessionIssues(body)
    return instance, client


def test_session_start_creates_journal_worktree_identity_and_instructions(
    session_repo, tmp_path
):
    instance, _ = service(session_repo, tmp_path)

    journal = instance.start(101)
    validation = next(step for step in journal.steps if step.name == "validate")
    worktree = Path(validation.result["worktree"])
    instruction_path = (
        instance.journal_store.path_for("kmosoti/dev-space", 101).parent / "AGENTS.md"
    )

    assert journal.status == OperationStatus.COMPLETE
    assert worktree.is_dir()
    assert git(worktree, "config", "--worktree", "user.name") == "kz-harbringer"
    assert (
        git(worktree, "config", "--worktree", "dev-space.ssh-host") == "github.com-kz"
    )
    assert "Policy commit" in instruction_path.read_text(encoding="utf-8")
    assert instance.issue_service.states[-1][1] == LifecycleState.IN_PROGRESS

    instance.client.login = "kmosoti"
    instance.cleanup(101)
    assert not worktree.exists()


def test_session_start_refuses_duplicate_completed_session(session_repo, tmp_path):
    instance, _ = service(session_repo, tmp_path)
    first = instance.start(102)

    with pytest.raises(SessionError, match="completed session"):
        instance.start(102)
    assert first.status == OperationStatus.COMPLETE

    validation = next(step for step in first.steps if step.name == "validate")
    instance.client.login = "kmosoti"
    instance.cleanup(102)
    assert not Path(validation.result["worktree"]).exists()


def test_handoff_is_journaled_and_never_calls_merge(session_repo, tmp_path):
    instance, client = service(session_repo, tmp_path)
    instance.start(103)
    instance._verify = lambda worktree: {
        "commands": [{"command": "true", "returncode": 0}]
    }
    instance._push = lambda worktree, branch: {"branch": branch, "remote": "fork"}
    instance._pull_request = lambda issue, branch, verification: {
        "number": 55,
        "draft": True,
    }
    instance._request_review = lambda number: {"pull_request": number}

    journal = instance.handoff(103)

    assert journal.status == OperationStatus.COMPLETE
    assert instance.issue_service.states[-1][1] == LifecycleState.IN_REVIEW
    assert not any("merge" in call[0] for call in client.calls)

    validation = next(
        step
        for step in instance.journal_store.load("kmosoti/dev-space", 103).steps
        if step.name == "validate"
    )
    client.login = "kmosoti"
    instance.cleanup(103)
    assert not Path(validation.result["worktree"]).exists()


def test_slug_is_bounded_and_safe():
    value = _slug("[Change] Build Project v2 — full fidelity!!!")
    assert value == "change-build-project-v2-full-fidelity"
    assert len(_slug("A" * 200)) <= 48


def test_worktree_root_honors_xdg_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert default_worktree_root() == tmp_path / "dev-space" / "worktrees"
    monkeypatch.delenv("XDG_DATA_HOME")
    assert str(default_worktree_root()).endswith(".local/share/dev-space/worktrees")


def test_start_failure_is_journaled_and_recoverable(
    session_repo, tmp_path, monkeypatch
):
    instance, _ = service(session_repo, tmp_path)
    original = instance._create_worktree
    monkeypatch.setattr(
        instance,
        "_create_worktree",
        lambda *args, **kwargs: (_ for _ in ()).throw(SessionError("disk full")),
    )

    with pytest.raises(SessionError, match="disk full"):
        instance.start(104)
    failed = instance.journal_store.load("kmosoti/dev-space", 104)
    assert failed.status == OperationStatus.FAILED
    assert (
        next(step for step in failed.steps if step.name == "worktree").error
        == "disk full"
    )

    monkeypatch.setattr(instance, "_create_worktree", original)
    recovered = instance.recover(104)
    assert recovered.status == OperationStatus.COMPLETE
    validation = next(step for step in recovered.steps if step.name == "validate")
    instance.client.login = "kmosoti"
    instance.cleanup(104)
    assert not Path(validation.result["worktree"]).exists()


def test_handoff_failure_status_and_recovery(session_repo, tmp_path, monkeypatch):
    instance, _ = service(session_repo, tmp_path)
    instance.start(105)
    monkeypatch.setattr(instance, "_verify", lambda worktree: {"commands": []})
    monkeypatch.setattr(
        instance,
        "_push",
        lambda *args: (_ for _ in ()).throw(SessionError("push denied")),
    )

    with pytest.raises(SessionError, match="push denied"):
        instance.handoff(105)
    state = instance.status(105)
    assert state["start"]["status"] == "complete"
    assert state["handoff"]["status"] == "failed"

    monkeypatch.setattr(instance, "_push", lambda *args: {"remote": "fork"})
    monkeypatch.setattr(instance, "_pull_request", lambda *args: {"number": 56})
    monkeypatch.setattr(instance, "_request_review", lambda number: {"number": number})
    recovered = instance.recover(105)
    assert recovered.status == OperationStatus.COMPLETE

    instance.client.login = "kmosoti"
    instance.cleanup(105)


def test_cleanup_refuses_open_pull_request(session_repo, tmp_path, monkeypatch):
    instance, _ = service(session_repo, tmp_path)
    journal = instance.start(106)
    instance.client.login = "kmosoti"
    monkeypatch.setattr(instance, "_open_pull_requests", lambda branch: [{"number": 1}])

    with pytest.raises(SessionError, match="pull request is open"):
        instance.cleanup(106)
    assert journal.status == OperationStatus.COMPLETE

    monkeypatch.setattr(instance, "_open_pull_requests", lambda branch: [])
    instance.cleanup(106)


def test_verification_runner_captures_success_and_stops_on_failure(
    session_repo, tmp_path
):
    instance, _ = service(session_repo, tmp_path)
    instance.policy = instance.policy.model_copy(
        update={
            "verification": VerificationPolicy(focused=["true"], full=["printf ok"])
        }
    )
    result = instance._verify(session_repo)
    assert [entry["returncode"] for entry in result["commands"]] == [0, 0]

    instance.policy = instance.policy.model_copy(
        update={"verification": VerificationPolicy(focused=["false"], full=["true"])}
    )
    with pytest.raises(SessionError, match="verification failed"):
        instance._verify(session_repo)


def test_push_success_and_failure_are_typed(session_repo, tmp_path, monkeypatch):
    instance, _ = service(session_repo, tmp_path)
    calls = []

    def success(arguments, **kwargs):
        calls.append(arguments)
        return subprocess.CompletedProcess(arguments, 0, "pushed", "")

    monkeypatch.setattr(subprocess, "run", success)
    result = instance._push(session_repo, "mutation/issue-1-test")
    assert result["remote"].startswith("git@github.com-kz:")
    assert "push" in calls[0]

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda arguments, **kwargs: subprocess.CompletedProcess(
            arguments, 1, "", "denied"
        ),
    )
    with pytest.raises(SessionError, match="denied"):
        instance._push(session_repo, "mutation/issue-1-test")


def test_pull_request_create_update_duplicate_and_review(
    session_repo, tmp_path, monkeypatch
):
    instance, client = service(session_repo, tmp_path)
    verification = {"commands": [{"command": "true", "returncode": 0}]}

    def create_rest(endpoint, *, method="GET", payload=None):
        client.calls.append((endpoint, method, payload))
        if method == "POST" and endpoint.endswith("/pulls"):
            return {"number": 70, "draft": True}
        if method == "PATCH" and "/pulls/" in endpoint:
            return {"number": 70, **(payload or {})}
        return payload or {}

    client.rest = create_rest
    monkeypatch.setattr(instance, "_open_pull_requests", lambda branch: [])
    created = instance._pull_request(101, "mutation/issue-101-test", verification)
    assert created["number"] == 70

    monkeypatch.setattr(
        instance, "_open_pull_requests", lambda branch: [{"number": 70}]
    )
    updated = instance._pull_request(101, "mutation/issue-101-test", verification)
    assert updated["body"].startswith("## Implementation issue")
    review = instance._request_review(70)
    assert review == {"pull_request": 70, "reviewer": "kmosoti"}

    monkeypatch.setattr(
        instance, "_open_pull_requests", lambda branch: [{"number": 1}, {"number": 2}]
    )
    with pytest.raises(SessionError, match="multiple open"):
        instance._pull_request(101, "mutation/issue-101-test", verification)


def test_pull_request_uses_target_owner_for_repository_write(
    session_repo, tmp_path, monkeypatch
):
    instance, client = service(session_repo, tmp_path)
    repository = instance.policy.repository.model_copy(
        update={"worker_authority": "repository_write", "worker_fork_owner": None}
    )
    instance.policy = instance.policy.model_copy(update={"repository": repository})

    def create_rest(endpoint, *, method="GET", payload=None):
        client.calls.append((endpoint, method, payload))
        if method == "POST" and endpoint.endswith("/pulls"):
            return {"number": 71, "draft": True}
        return payload or {}

    client.rest = create_rest
    monkeypatch.setattr(instance, "_open_pull_requests", lambda branch: [])

    created = instance._pull_request(
        101,
        "mutation/issue-101-test",
        {"commands": [{"command": "true", "returncode": 0}]},
    )
    payload = next(
        payload
        for endpoint, method, payload in client.calls
        if method == "POST" and endpoint.endswith("/pulls")
    )

    assert created["number"] == 71
    assert repository.worker_owner == "kmosoti"
    assert payload["head"] == "kmosoti:mutation/issue-101-test"


def test_worker_identity_failure_is_reported(session_repo, tmp_path, monkeypatch):
    instance, _ = service(session_repo, tmp_path)
    instance.verify_identity = True
    report = SimpleNamespace(
        healthy=False,
        checks=(
            SimpleNamespace(
                ok=False, name="github_actor", expected="kz-harbringer", actual="wrong"
            ),
        ),
    )
    monkeypatch.setattr(
        "dev_space.control_plane.sessions.preflight_identity",
        lambda *args, **kwargs: report,
    )

    with pytest.raises(SessionError, match="identity preflight failed"):
        instance._require_worker_identity()
    assert report.healthy is False
