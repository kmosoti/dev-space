from __future__ import annotations

from dataclasses import dataclass

from .models import ActorRole, ProjectPolicy


class AuthorizationError(RuntimeError):
    """Raised when an actor attempts a command outside its capability set."""


_COMMAND_ROLES: dict[str, frozenset[ActorRole]] = {
    "project.doctor": frozenset(ActorRole),
    "project.snapshot": frozenset(ActorRole),
    "project.plan": frozenset(ActorRole),
    "project.apply": frozenset({ActorRole.PLANNER}),
    "issue.create-change": frozenset({ActorRole.PLANNER}),
    "issue.mark-ready": frozenset({ActorRole.PLANNER}),
    "issue.transition": frozenset(ActorRole),
    "session.status": frozenset(ActorRole),
    "session.start": frozenset({ActorRole.WORKER}),
    "session.handoff": frozenset({ActorRole.WORKER}),
    "session.recover": frozenset(ActorRole),
    "session.cleanup": frozenset({ActorRole.PLANNER}),
}


@dataclass(frozen=True)
class AuthorizationResult:
    allowed: bool
    role: ActorRole | None
    reason: str | None = None


def identify_role(login: str, policy: ProjectPolicy) -> ActorRole | None:
    normalized = login.casefold()
    if normalized == policy.actors.planner.login.casefold():
        return ActorRole.PLANNER
    if normalized == policy.actors.worker.login.casefold():
        return ActorRole.WORKER
    return None


def authorize(command: str, login: str, policy: ProjectPolicy) -> AuthorizationResult:
    allowed_roles = _COMMAND_ROLES.get(command)
    if allowed_roles is None:
        return AuthorizationResult(
            False, None, f"unknown command capability: {command}"
        )
    role = identify_role(login, policy)
    if role is None:
        return AuthorizationResult(False, None, f"unconfigured GitHub actor: {login}")
    if role not in allowed_roles:
        return AuthorizationResult(
            False, role, f"{role} is not allowed to run {command}"
        )
    return AuthorizationResult(True, role)


def require_authorized(command: str, login: str, policy: ProjectPolicy) -> ActorRole:
    result = authorize(command, login, policy)
    if not result.allowed or result.role is None:
        raise AuthorizationError(result.reason or "authorization denied")
    return result.role
