from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class OperationStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    FAILED = "failed"
    COMPLETE = "complete"


class StepStatus(StrEnum):
    PENDING = "pending"
    COMPLETE = "complete"
    FAILED = "failed"


class OperationStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    idempotency_key: str
    status: StepStatus = StepStatus.PENDING
    observed_version: str | None = None
    result: dict[str, object] = Field(default_factory=dict)
    recovery_action: str | None = None
    error: str | None = None


class OperationJournal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: str = Field(default_factory=lambda: str(uuid4()))
    command: str
    repository: str
    issue_number: int = Field(gt=0)
    actor: str
    policy_commit: str
    specification_hash: str | None = None
    status: OperationStatus = OperationStatus.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    steps: list[OperationStep] = Field(default_factory=list)


def default_state_root() -> Path:
    state_home = os.environ.get("XDG_STATE_HOME")
    base = Path(state_home).expanduser() if state_home else Path.home() / ".local/state"
    return base / "dev-space" / "sessions"


class JournalStore:
    def __init__(self, root: Path | None = None):
        self.root = (root or default_state_root()).resolve()

    def path_for(self, repository: str, issue_number: int) -> Path:
        owner, separator, name = repository.partition("/")
        if not separator or not owner or not name or "/" in name:
            raise ValueError(f"invalid repository name: {repository}")
        if issue_number <= 0:
            raise ValueError("issue number must be positive")
        return self.root / owner / name / str(issue_number) / "operation.json"

    def load(self, repository: str, issue_number: int) -> OperationJournal | None:
        path = self.path_for(repository, issue_number)
        if not path.exists():
            return None
        return OperationJournal.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, journal: OperationJournal) -> Path:
        journal.updated_at = datetime.now(UTC)
        path = self.path_for(journal.repository, journal.issue_number)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = journal.model_dump_json(indent=2)
        file_descriptor, temporary_name = tempfile.mkstemp(
            dir=path.parent, prefix=".operation-", suffix=".tmp", text=True
        )
        try:
            with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
        return path

    def delete(self, repository: str, issue_number: int) -> None:
        path = self.path_for(repository, issue_number)
        if path.exists():
            path.unlink()


def journal_as_dict(journal: OperationJournal) -> dict[str, object]:
    return json.loads(journal.model_dump_json())
