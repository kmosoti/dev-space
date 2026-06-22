from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

from pydantic import ValidationError

from .models import ProjectPolicy


class PolicyError(RuntimeError):
    """Raised when repository policy cannot be discovered or validated."""


def discover_repository(path: Path | str | None = None) -> Path:
    candidate = Path(path or Path.cwd()).expanduser().resolve()
    if candidate.is_file():
        candidate = candidate.parent
    result = subprocess.run(
        ["git", "-C", str(candidate), "rev-parse", "--show-toplevel"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise PolicyError(f"not a Git repository: {candidate}")
    return Path(result.stdout.strip()).resolve()


def load_policy(repo: Path | str | None = None) -> ProjectPolicy:
    root = discover_repository(repo)
    policy_path = root / ".dev-space" / "project.toml"
    if not policy_path.is_file():
        raise PolicyError(f"missing project policy: {policy_path}")
    try:
        data = tomllib.loads(policy_path.read_text(encoding="utf-8"))
        return ProjectPolicy.model_validate(data)
    except (OSError, tomllib.TOMLDecodeError, ValidationError) as exc:
        raise PolicyError(f"invalid project policy {policy_path}: {exc}") from exc


def load_policy_at_revision(repo: Path | str | None, revision: str) -> ProjectPolicy:
    root = discover_repository(repo)
    result = subprocess.run(
        ["git", "-C", str(root), "show", f"{revision}:.dev-space/project.toml"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise PolicyError(
            f"cannot load policy from {revision}: {result.stderr.strip()}"
        )
    try:
        return ProjectPolicy.model_validate(tomllib.loads(result.stdout))
    except (tomllib.TOMLDecodeError, ValidationError) as exc:
        raise PolicyError(f"invalid project policy at {revision}: {exc}") from exc
