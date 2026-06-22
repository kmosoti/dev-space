from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import structlog

from dev_space.control_plane.github import GitHubClient
from dev_space.control_plane.models import ActorRole, ProjectPolicy

logger = structlog.get_logger()


def apply_identity_lane(lane: str) -> None:
    """Select an isolated gh configuration and commit identity for this process."""
    config_dir = Path.home() / ".config" / "dev-space"
    if lane == "agent":
        agent_gh = config_dir / "agent-gh"
        os.environ["GH_CONFIG_DIR"] = str(agent_gh)
        os.environ["GIT_AUTHOR_NAME"] = "kz-harbringer"
        os.environ["GIT_AUTHOR_EMAIL"] = "kz-harbringer@users.noreply.github.com"
        os.environ["GIT_COMMITTER_NAME"] = "kz-harbringer"
        os.environ["GIT_COMMITTER_EMAIL"] = "kz-harbringer@users.noreply.github.com"
        logger.debug("Applied 'agent' identity lane.")
        return
    if lane == "human":
        os.environ.pop("GH_CONFIG_DIR", None)
        for key in (
            "GIT_AUTHOR_NAME",
            "GIT_AUTHOR_EMAIL",
            "GIT_COMMITTER_NAME",
            "GIT_COMMITTER_EMAIL",
        ):
            os.environ.pop(key, None)
        logger.debug("Applied 'human' identity lane.")
        return
    raise ValueError(f"unknown identity lane: {lane}")


@dataclass(frozen=True)
class IdentityCheck:
    name: str
    ok: bool
    expected: str
    actual: str


@dataclass(frozen=True)
class IdentityReport:
    role: ActorRole
    checks: tuple[IdentityCheck, ...]

    @property
    def healthy(self) -> bool:
        return all(check.ok for check in self.checks)


def preflight_identity(
    policy: ProjectPolicy,
    role: ActorRole,
    repo: Path,
    *,
    client: GitHubClient | None = None,
    verify_ssh: bool = True,
) -> IdentityReport:
    actor = policy.actors.planner if role == ActorRole.PLANNER else policy.actors.worker
    github = client or GitHubClient()
    login = github.current_user()
    checks = [
        IdentityCheck(
            "github_actor",
            login.casefold() == actor.login.casefold(),
            actor.login,
            login,
        )
    ]
    name = _git_config(repo, "user.name")
    email = _git_config(repo, "user.email")
    checks.extend(
        [
            IdentityCheck(
                "commit_name", name == actor.commit_name, actor.commit_name, name
            ),
            IdentityCheck(
                "commit_email", email == actor.commit_email, actor.commit_email, email
            ),
        ]
    )
    if verify_ssh:
        ssh_actor = _ssh_actor(actor.ssh_host)
        checks.append(
            IdentityCheck(
                "ssh_actor",
                ssh_actor.casefold() == actor.login.casefold(),
                actor.login,
                ssh_actor,
            )
        )
    permission_repo = (
        policy.repository.worker_repository
        if role == ActorRole.WORKER
        else policy.repository.full_name
    )
    response = github.rest(
        f"repos/{permission_repo}/collaborators/{actor.login}/permission"
    )
    permission = (
        str(response.get("permission", "none"))
        if isinstance(response, dict)
        else "none"
    )
    allowed = permission in {"admin", "maintain", "write"}
    checks.append(
        IdentityCheck(
            "repository_permission", allowed, f"write on {permission_repo}", permission
        )
    )
    return IdentityReport(role, tuple(checks))


def configure_worktree_identity(
    worktree: Path, policy: ProjectPolicy, role: Literal["planner", "worker"]
) -> None:
    actor = policy.actors.planner if role == "planner" else policy.actors.worker
    root = Path(
        subprocess.run(
            ["git", "-C", str(worktree), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
    subprocess.run(
        ["git", "-C", str(root), "config", "extensions.worktreeConfig", "true"],
        check=True,
    )
    for key, value in (
        ("user.name", actor.commit_name),
        ("user.email", actor.commit_email),
        ("dev-space.ssh-host", actor.ssh_host),
    ):
        subprocess.run(
            ["git", "-C", str(worktree), "config", "--worktree", key, value],
            check=True,
        )


def _git_config(repo: Path, key: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "config", "--get", key],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _ssh_actor(host: str) -> str:
    result = subprocess.run(
        ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", f"git@{host}"],
        check=False,
        capture_output=True,
        text=True,
    )
    message = f"{result.stdout}\n{result.stderr}"
    match = re.search(r"Hi ([^!]+)!", message)
    return match.group(1) if match else message.strip()
