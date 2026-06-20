from __future__ import annotations

from dataclasses import dataclass

from .models import ActorRole, LifecycleState, Risk


@dataclass(frozen=True)
class TransitionContext:
    specification_complete: bool = False
    unresolved_decisions: tuple[str, ...] = ()
    dependencies_complete: bool = False
    risk: Risk = Risk.LOW
    active_resources: bool = False
    checks_passed: bool = False
    draft_pr_exists: bool = False
    merged_by_planner: bool = False
    blocker: str | None = None
    cancellation_reason: str | None = None
    previous_state: LifecycleState | None = None


@dataclass(frozen=True)
class TransitionResult:
    allowed: bool
    violations: tuple[str, ...] = ()


_TRANSITIONS: dict[tuple[LifecycleState, LifecycleState], frozenset[ActorRole]] = {
    (LifecycleState.INBOX, LifecycleState.NEEDS_DEFINITION): frozenset(
        {ActorRole.PLANNER}
    ),
    (LifecycleState.NEEDS_DEFINITION, LifecycleState.READY): frozenset(
        {ActorRole.PLANNER}
    ),
    (LifecycleState.READY, LifecycleState.IN_PROGRESS): frozenset({ActorRole.WORKER}),
    (LifecycleState.IN_PROGRESS, LifecycleState.IN_REVIEW): frozenset(
        {ActorRole.WORKER}
    ),
    (LifecycleState.IN_REVIEW, LifecycleState.DONE): frozenset({ActorRole.PLANNER}),
    (LifecycleState.IN_PROGRESS, LifecycleState.NEEDS_DEFINITION): frozenset(
        {ActorRole.PLANNER}
    ),
    (LifecycleState.BLOCKED, LifecycleState.NEEDS_DEFINITION): frozenset(
        {ActorRole.PLANNER}
    ),
    (LifecycleState.BLOCKED, LifecycleState.READY): frozenset({ActorRole.PLANNER}),
    (LifecycleState.BLOCKED, LifecycleState.IN_PROGRESS): frozenset(
        {ActorRole.PLANNER}
    ),
}

for state in LifecycleState:
    if state not in {
        LifecycleState.DONE,
        LifecycleState.CANCELED,
        LifecycleState.BLOCKED,
    }:
        _TRANSITIONS[(state, LifecycleState.BLOCKED)] = frozenset(
            {ActorRole.PLANNER, ActorRole.WORKER}
        )

for state in {
    LifecycleState.NEEDS_DEFINITION,
    LifecycleState.READY,
    LifecycleState.IN_PROGRESS,
    LifecycleState.IN_REVIEW,
    LifecycleState.BLOCKED,
}:
    _TRANSITIONS[(state, LifecycleState.CANCELED)] = frozenset({ActorRole.PLANNER})


def evaluate_transition(
    current: LifecycleState,
    target: LifecycleState,
    role: ActorRole,
    context: TransitionContext,
) -> TransitionResult:
    violations: list[str] = []
    allowed_roles = _TRANSITIONS.get((current, target))
    if allowed_roles is None:
        return TransitionResult(False, (f"illegal transition: {current} -> {target}",))
    if role not in allowed_roles:
        violations.append(f"{role} cannot perform {current} -> {target}")

    if target == LifecycleState.READY:
        if not context.specification_complete:
            violations.append("specification is incomplete")
        if context.unresolved_decisions:
            violations.append("unresolved decisions remain")
        if not context.dependencies_complete:
            violations.append("dependencies are incomplete")
        if context.risk == Risk.HIGH:
            violations.append("high-risk work cannot be marked agent-ready")

    if (current, target) == (LifecycleState.READY, LifecycleState.IN_PROGRESS):
        if context.active_resources:
            violations.append(
                "active branch, worktree, session, or pull request exists"
            )

    if target == LifecycleState.IN_REVIEW:
        if not context.checks_passed:
            violations.append("verification checks did not pass")
        if not context.draft_pr_exists:
            violations.append("draft pull request does not exist")

    if target == LifecycleState.DONE and not context.merged_by_planner:
        violations.append("pull request was not merged by the planner")

    if target == LifecycleState.BLOCKED and not context.blocker:
        violations.append("blocker and unblock condition are required")

    if target == LifecycleState.CANCELED:
        if not context.cancellation_reason:
            violations.append("cancellation reason is required")
        if current in {LifecycleState.NEEDS_DEFINITION, LifecycleState.READY}:
            if context.active_resources:
                violations.append("active implementation resources must be resolved")

    if current == LifecycleState.BLOCKED and target != LifecycleState.CANCELED:
        if context.blocker:
            violations.append("blocker is still active")
        if context.previous_state is not None and target != context.previous_state:
            violations.append("blocked work must return to its previous active state")

    return TransitionResult(not violations, tuple(violations))


def allowed_transitions(
    current: LifecycleState, role: ActorRole
) -> tuple[LifecycleState, ...]:
    return tuple(
        target
        for (source, target), roles in _TRANSITIONS.items()
        if source == current and role in roles
    )
