from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ActorRole(StrEnum):
    PLANNER = "planner"
    WORKER = "worker"


class WorkType(StrEnum):
    EPIC = "Epic"
    CHANGE = "Change"
    BUG = "Bug"
    MAINTENANCE = "Maintenance"
    DECISION = "Decision"


class ExecutionMode(StrEnum):
    AGENT_READY = "Agent-ready"
    AGENT_ASSISTED = "Agent-assisted"
    HUMAN_ONLY = "Human-only"


class Risk(StrEnum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"


class LifecycleState(StrEnum):
    INBOX = "Inbox"
    NEEDS_DEFINITION = "Needs Definition"
    READY = "Ready"
    IN_PROGRESS = "In Progress"
    IN_REVIEW = "In Review"
    BLOCKED = "Blocked"
    DONE = "Done"
    CANCELED = "Canceled"


class ProjectFieldType(StrEnum):
    SINGLE_SELECT = "SINGLE_SELECT"
    TEXT = "TEXT"
    NUMBER = "NUMBER"
    DATE = "DATE"


class ProjectLayout(StrEnum):
    TABLE = "TABLE"
    BOARD = "BOARD"
    ROADMAP = "ROADMAP"


class ActorPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    login: str = Field(min_length=1)
    ssh_host: str = Field(min_length=1)
    commit_name: str = Field(min_length=1)
    commit_email: str = Field(min_length=3)
    gh_config_dir: str | None = None


class ActorSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    planner: ActorPolicy
    worker: ActorPolicy

    @model_validator(mode="after")
    def actors_are_distinct(self) -> ActorSet:
        if self.planner.login.casefold() == self.worker.login.casefold():
            raise ValueError("planner and worker GitHub actors must be distinct")
        return self


class RepositoryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner: str = Field(min_length=1)
    name: str = Field(min_length=1)
    default_branch: str = Field(default="main", min_length=1)
    worker_authority: Literal["fork", "repository_write"] = "fork"
    worker_fork_owner: str | None = None

    @model_validator(mode="after")
    def validate_worker_authority(self) -> RepositoryConfig:
        if self.worker_authority == "fork" and not self.worker_fork_owner:
            raise ValueError("fork worker authority requires worker_fork_owner")
        return self

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"

    @property
    def worker_repository(self) -> str:
        owner = (
            self.worker_fork_owner if self.worker_authority == "fork" else self.owner
        )
        assert owner is not None
        return f"{owner}/{self.name}"


class ProjectOptionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    description: str = ""
    color: Literal[
        "GRAY", "BLUE", "GREEN", "YELLOW", "ORANGE", "RED", "PINK", "PURPLE"
    ] = "GRAY"


class ProjectFieldPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    data_type: ProjectFieldType
    options: list[ProjectOptionPolicy] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_options(self) -> ProjectFieldPolicy:
        if self.data_type == ProjectFieldType.SINGLE_SELECT and not self.options:
            raise ValueError(f"single-select field {self.name!r} requires options")
        if self.data_type != ProjectFieldType.SINGLE_SELECT and self.options:
            raise ValueError(
                f"non-single-select field {self.name!r} cannot have options"
            )
        names = [option.name.casefold() for option in self.options]
        if len(names) != len(set(names)):
            raise ValueError(f"field {self.name!r} has duplicate option names")
        return self


class ProjectViewPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    layout: ProjectLayout = ProjectLayout.TABLE
    filter: str = ""
    group_by: str | None = None
    sort_by: list[str] = Field(default_factory=list)
    fields: list[str] = Field(default_factory=list)


class ProjectWorkflowPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    enabled: bool = False
    configuration: dict[str, str] = Field(default_factory=dict)


class ProjectV2Policy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner: str = Field(min_length=1)
    title: str = Field(min_length=1)
    short_description: str = ""
    readme: str = ""
    public: bool = False
    fields: list[ProjectFieldPolicy]
    views: list[ProjectViewPolicy] = Field(default_factory=list)
    workflows: list[ProjectWorkflowPolicy] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_names(self) -> ProjectV2Policy:
        for kind, values in (
            ("field", [field.name.casefold() for field in self.fields]),
            ("view", [view.name.casefold() for view in self.views]),
            ("workflow", [workflow.name.casefold() for workflow in self.workflows]),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"duplicate Project v2 {kind} names")
        return self


class BranchPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template: str = "mutation/issue-{number}-{slug}"

    @field_validator("template")
    @classmethod
    def required_placeholders(cls, value: str) -> str:
        if "{number}" not in value or "{slug}" not in value:
            raise ValueError("branch template must include {number} and {slug}")
        return value


class CheckPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required: list[str] = Field(min_length=1)

    @field_validator("required")
    @classmethod
    def unique_checks(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("required check names must be unique")
        return value


class VerificationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    focused: list[str] = Field(default_factory=list)
    full: list[str] = Field(min_length=1)


class LifecyclePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    states: list[LifecycleState] = Field(default_factory=lambda: list(LifecycleState))

    @field_validator("states")
    @classmethod
    def complete_state_set(cls, value: list[LifecycleState]) -> list[LifecycleState]:
        if len(value) != len(set(value)):
            raise ValueError("lifecycle states must be unique")
        missing = set(LifecycleState) - set(value)
        if missing:
            missing_names = ", ".join(sorted(state.value for state in missing))
            raise ValueError(f"lifecycle is missing required states: {missing_names}")
        return value


class LabelPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    color: str = Field(pattern=r"^[0-9a-fA-F]{6}$")
    description: str = Field(min_length=1)


class RulesetPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = "dev-space-main-protection"
    enforcement: Literal["active", "disabled"] = "active"
    approvals: int = Field(default=1, ge=1)
    require_code_owner_review: bool = True
    dismiss_stale_reviews: bool = True
    require_last_push_approval: bool = True
    require_conversation_resolution: bool = True


class ProjectPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    repository: RepositoryConfig
    project: ProjectV2Policy
    actors: ActorSet
    branch: BranchPolicy = Field(default_factory=BranchPolicy)
    checks: CheckPolicy
    verification: VerificationPolicy
    lifecycle: LifecyclePolicy = Field(default_factory=LifecyclePolicy)
    labels: list[LabelPolicy] = Field(default_factory=list)
    ruleset: RulesetPolicy = Field(default_factory=RulesetPolicy)

    @model_validator(mode="after")
    def coherent_ownership(self) -> ProjectPolicy:
        if self.repository.owner.casefold() != self.project.owner.casefold():
            raise ValueError(
                "repository and user-owned Project must have the same owner"
            )
        status = next(
            (field for field in self.project.fields if field.name == "Status"), None
        )
        if status is None or status.data_type != ProjectFieldType.SINGLE_SELECT:
            raise ValueError("Project must declare Status as a single-select field")
        expected = [state.value for state in self.lifecycle.states]
        actual = [option.name for option in status.options]
        if actual != expected:
            raise ValueError("Status options must match lifecycle states in order")
        label_names = [label.name.casefold() for label in self.labels]
        if len(label_names) != len(set(label_names)):
            raise ValueError("managed label names must be unique")
        return self


class ActorIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    login: str
    ssh_host: str
    commit_name: str
    commit_email: str


class ChangeSpecification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    parent: int = Field(gt=0)
    problem: str = Field(min_length=1)
    current_behavior: str = Field(min_length=1)
    required_behavior: str = Field(min_length=1)
    scope: list[str] = Field(min_length=1)
    non_goals: list[str] = Field(min_length=1)
    design: str = Field(min_length=1)
    affected_components: list[str] = Field(min_length=1)
    security: str = Field(min_length=1)
    compatibility: str = Field(min_length=1)
    tests: list[str] = Field(min_length=1)
    rollout: str = Field(min_length=1)
    rollback: str = Field(min_length=1)
    dependencies: list[int] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(min_length=1)
    unresolved_decisions: list[str] = Field(default_factory=list)
    execution: ExecutionMode
    risk: Risk


class ReadinessResult(BaseModel):
    ready: bool
    violations: list[str] = Field(default_factory=list)
