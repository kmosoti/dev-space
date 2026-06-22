from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from dev_space.control_plane.authorization import (
    AuthorizationError,
    AuthorizationResult,
    authorize,
    require_authorized,
)
from dev_space.control_plane.journal import (
    JournalStore,
    OperationJournal,
    OperationStatus,
    OperationStep,
    StepStatus,
)
from dev_space.control_plane.lifecycle import (
    TransitionContext,
    allowed_transitions,
    evaluate_transition,
)
from dev_space.control_plane.models import (
    ActorRole,
    LifecycleState,
    ProjectPolicy,
    Risk,
)
from dev_space.control_plane.policy import PolicyError, discover_repository, load_policy

pytestmark = pytest.mark.no_observability


def test_repository_policy_loads_with_full_project_contract():
    policy = load_policy(Path(__file__).parents[1])

    assert policy.schema_version == 1
    assert policy.repository.full_name == "kmosoti/dev-space"
    assert policy.project.title == "dev-space"
    assert [field.name for field in policy.project.fields] == [
        "Status",
        "Work Type",
        "Execution",
        "Risk",
        "Development Branch",
    ]
    assert [option.name for option in policy.project.fields[0].options] == [
        state.value for state in LifecycleState
    ]
    assert len(policy.project.views) == 7


def test_policy_rejects_same_actor_and_status_drift():
    policy = load_policy(Path(__file__).parents[1])
    assert policy.actors.planner.login != policy.actors.worker.login
    raw = policy.model_dump(mode="json")
    raw["actors"]["worker"]["login"] = raw["actors"]["planner"]["login"]

    with pytest.raises(ValidationError, match="must be distinct"):
        ProjectPolicy.model_validate(raw)

    raw = policy.model_dump(mode="json")
    raw["project"]["fields"][0]["options"].pop()
    with pytest.raises(ValidationError, match="Status options must match"):
        ProjectPolicy.model_validate(raw)


def test_policy_discovery_and_missing_policy(tmp_path):
    repo = discover_repository(Path(__file__).parents[1] / "src")
    assert repo.name == "dev-space"
    assert (repo / ".git").exists()

    with pytest.raises(PolicyError, match="not a Git repository"):
        load_policy(tmp_path)


def test_ready_transition_requires_contract_gates():
    denied = evaluate_transition(
        LifecycleState.NEEDS_DEFINITION,
        LifecycleState.READY,
        ActorRole.PLANNER,
        TransitionContext(
            specification_complete=False,
            unresolved_decisions=("Choose storage",),
            dependencies_complete=False,
            risk=Risk.HIGH,
        ),
    )
    accepted = evaluate_transition(
        LifecycleState.NEEDS_DEFINITION,
        LifecycleState.READY,
        ActorRole.PLANNER,
        TransitionContext(
            specification_complete=True,
            dependencies_complete=True,
            risk=Risk.MEDIUM,
        ),
    )

    assert denied.allowed is False
    assert denied.violations == (
        "specification is incomplete",
        "unresolved decisions remain",
        "dependencies are incomplete",
        "high-risk work cannot be marked agent-ready",
    )
    assert accepted.allowed is True
    assert accepted.violations == ()


@pytest.mark.parametrize(
    ("current", "target", "role", "context", "expected"),
    [
        (
            LifecycleState.READY,
            LifecycleState.IN_PROGRESS,
            ActorRole.WORKER,
            TransitionContext(),
            True,
        ),
        (
            LifecycleState.READY,
            LifecycleState.IN_PROGRESS,
            ActorRole.PLANNER,
            TransitionContext(),
            False,
        ),
        (
            LifecycleState.IN_PROGRESS,
            LifecycleState.IN_REVIEW,
            ActorRole.WORKER,
            TransitionContext(checks_passed=True, pr_ready_for_review=True),
            True,
        ),
        (
            LifecycleState.IN_REVIEW,
            LifecycleState.DONE,
            ActorRole.PLANNER,
            TransitionContext(merged_by_planner=False),
            False,
        ),
        (
            LifecycleState.IN_PROGRESS,
            LifecycleState.BLOCKED,
            ActorRole.WORKER,
            TransitionContext(blocker="Waiting on API; retry after access is granted"),
            True,
        ),
        (
            LifecycleState.READY,
            LifecycleState.CANCELED,
            ActorRole.PLANNER,
            TransitionContext(cancellation_reason="Superseded"),
            True,
        ),
        (
            LifecycleState.DONE,
            LifecycleState.READY,
            ActorRole.PLANNER,
            TransitionContext(),
            False,
        ),
    ],
)
def test_transition_matrix(current, target, role, context, expected):
    result = evaluate_transition(current, target, role, context)
    assert result.allowed is expected


def test_allowed_transitions_are_role_scoped():
    worker_targets = allowed_transitions(LifecycleState.READY, ActorRole.WORKER)
    planner_targets = allowed_transitions(LifecycleState.READY, ActorRole.PLANNER)

    assert LifecycleState.IN_PROGRESS in worker_targets
    assert LifecycleState.IN_PROGRESS not in planner_targets
    assert LifecycleState.CANCELED in planner_targets


def test_command_authorization_uses_configured_actor_roles():
    policy = load_policy(Path(__file__).parents[1])

    planner_apply = authorize("project.apply", "kmosoti", policy)
    worker_apply = authorize("project.apply", "kz-harbringer", policy)
    worker_start = authorize("session.start", "kz-harbringer", policy)
    unconfigured = authorize("project.plan", "somebody-else", policy)
    unknown = authorize("not-a-command", "kmosoti", policy)

    assert planner_apply == AuthorizationResult(True, ActorRole.PLANNER)
    assert worker_apply == AuthorizationResult(
        False,
        ActorRole.WORKER,
        "worker is not allowed to run project.apply",
    )
    assert worker_start == AuthorizationResult(True, ActorRole.WORKER)
    assert unconfigured == AuthorizationResult(
        False, None, "unconfigured GitHub actor: somebody-else"
    )
    assert unknown == AuthorizationResult(
        False, None, "unknown command capability: not-a-command"
    )
    assert require_authorized("project.apply", "kmosoti", policy) == ActorRole.PLANNER

    with pytest.raises(
        AuthorizationError,
        match=r"worker is not allowed to run project\.apply",
    ):
        require_authorized("project.apply", "kz-harbringer", policy)
    with pytest.raises(
        AuthorizationError, match="unknown command capability: not-a-command"
    ):
        require_authorized("not-a-command", "kmosoti", policy)


def test_operation_journal_round_trip_and_atomic_update(tmp_path):
    store = JournalStore(tmp_path)
    journal = OperationJournal(
        command="session.start",
        repository="kmosoti/dev-space",
        issue_number=42,
        actor="kz-harbringer",
        policy_commit="abc123",
        steps=[OperationStep(name="reserve", idempotency_key="start:42:reserve")],
    )

    path = store.save(journal)
    loaded = store.load("kmosoti/dev-space", 42)
    assert path == tmp_path / "kmosoti" / "dev-space" / "42" / "operation.json"
    assert loaded is not None
    assert loaded.operation_id == journal.operation_id
    assert loaded.steps[0].status == StepStatus.PENDING

    loaded.status = OperationStatus.COMPLETE
    loaded.steps[0].status = StepStatus.COMPLETE
    store.save(loaded)
    completed = store.load("kmosoti/dev-space", 42)
    assert completed is not None
    assert completed.status == OperationStatus.COMPLETE
    assert completed.steps[0].status == StepStatus.COMPLETE
    assert list(path.parent.glob("*.tmp")) == []

    store.delete("kmosoti/dev-space", 42)
    assert store.load("kmosoti/dev-space", 42) is None


def test_operation_journal_rejects_invalid_identity(tmp_path):
    store = JournalStore(tmp_path)
    assert store.root == tmp_path
    with pytest.raises(ValueError, match="invalid repository"):
        store.path_for("not-a-repository", 1)
    with pytest.raises(ValueError, match="positive"):
        store.path_for("kmosoti/dev-space", 0)
