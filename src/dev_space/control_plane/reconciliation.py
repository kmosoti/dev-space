from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from .models import ProjectPolicy, ProjectV2Policy
from .project_v2 import ProjectSnapshot


class ReconciliationAction(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    UNCHANGED = "unchanged"
    CONFLICT = "conflict"
    UNSUPPORTED = "unsupported"
    HUMAN_ACTION_REQUIRED = "human_action_required"


class ReconciliationEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: ReconciliationAction
    resource: str
    key: str
    detail: str
    desired: object | None = None
    actual: object | None = None


class ReconciliationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repository: str
    project_owner: str
    project_title: str
    entries: list[ReconciliationEntry] = Field(default_factory=list)

    @property
    def has_conflicts(self) -> bool:
        return any(
            entry.action == ReconciliationAction.CONFLICT for entry in self.entries
        )

    @property
    def requires_changes(self) -> bool:
        return any(
            entry.action in {ReconciliationAction.CREATE, ReconciliationAction.UPDATE}
            for entry in self.entries
        )

    def markdown(self) -> str:
        lines = [
            f"# Reconciliation: {self.project_owner}/{self.project_title}",
            "",
            "| Action | Resource | Key | Detail |",
            "| --- | --- | --- | --- |",
        ]
        lines.extend(
            f"| {entry.action} | {entry.resource} | {entry.key} | {entry.detail} |"
            for entry in self.entries
        )
        return "\n".join(lines) + "\n"


def build_reconciliation_report(
    policy: ProjectPolicy,
    matches: list[dict[str, object]],
    snapshot: ProjectSnapshot | None,
) -> ReconciliationReport:
    report = ReconciliationReport(
        repository=policy.repository.full_name,
        project_owner=policy.project.owner,
        project_title=policy.project.title,
    )
    if len(matches) > 1:
        report.entries.append(
            ReconciliationEntry(
                action=ReconciliationAction.CONFLICT,
                resource="project",
                key=policy.project.title,
                detail=f"{len(matches)} Projects have the configured title",
                desired=1,
                actual=len(matches),
            )
        )
        return report
    if snapshot is None:
        report.entries.append(
            ReconciliationEntry(
                action=ReconciliationAction.CREATE,
                resource="project",
                key=policy.project.title,
                detail="create the user-owned Project v2",
            )
        )
        _add_desired_resources(report, policy.project, creating=True)
        return report

    metadata = {
        "title": (policy.project.title, snapshot.title),
        "short_description": (
            policy.project.short_description,
            snapshot.short_description,
        ),
        "readme": (policy.project.readme, snapshot.readme),
        "public": (policy.project.public, snapshot.public),
    }
    for key, (desired, actual) in metadata.items():
        report.entries.append(
            ReconciliationEntry(
                action=(
                    ReconciliationAction.UNCHANGED
                    if desired == actual
                    else ReconciliationAction.UPDATE
                ),
                resource="project_metadata",
                key=key,
                detail="metadata matches" if desired == actual else "metadata drift",
                desired=desired,
                actual=actual,
            )
        )
    repository = policy.repository.full_name
    report.entries.append(
        ReconciliationEntry(
            action=(
                ReconciliationAction.UNCHANGED
                if repository in snapshot.repositories
                else ReconciliationAction.UPDATE
            ),
            resource="repository_link",
            key=repository,
            detail=(
                "repository is linked"
                if repository in snapshot.repositories
                else "link repository to Project v2"
            ),
        )
    )

    actual_fields = {field.name: field for field in snapshot.fields}
    for desired_field in policy.project.fields:
        actual_field = actual_fields.get(desired_field.name)
        if actual_field is None:
            report.entries.append(
                ReconciliationEntry(
                    action=ReconciliationAction.CREATE,
                    resource="project_field",
                    key=desired_field.name,
                    detail=f"create {desired_field.data_type} field",
                )
            )
            continue
        desired_options = [
            option.model_dump(mode="json") for option in desired_field.options
        ]
        actual_options = [
            {
                "name": option.name,
                "description": option.description,
                "color": option.color,
            }
            for option in actual_field.options
        ]
        type_matches = actual_field.data_type == desired_field.data_type
        options_match = desired_options == actual_options
        report.entries.append(
            ReconciliationEntry(
                action=(
                    ReconciliationAction.CONFLICT
                    if not type_matches
                    else (
                        ReconciliationAction.UNCHANGED
                        if options_match
                        else ReconciliationAction.UPDATE
                    )
                ),
                resource="project_field",
                key=desired_field.name,
                detail=(
                    "field matches"
                    if type_matches and options_match
                    else (
                        "field type cannot be changed in place"
                        if not type_matches
                        else "field options drift"
                    )
                ),
                desired={
                    "data_type": desired_field.data_type,
                    "options": desired_options,
                },
                actual={
                    "data_type": actual_field.data_type,
                    "options": actual_options,
                },
            )
        )

    _add_manual_resources(report, policy.project)
    return report


def _add_desired_resources(
    report: ReconciliationReport, policy: ProjectV2Policy, *, creating: bool
) -> None:
    action = ReconciliationAction.CREATE if creating else ReconciliationAction.UPDATE
    for field in policy.fields:
        report.entries.append(
            ReconciliationEntry(
                action=action,
                resource="project_field",
                key=field.name,
                detail=f"reconcile {field.data_type} field and options",
            )
        )
    _add_manual_resources(report, policy)


def _add_manual_resources(
    report: ReconciliationReport, policy: ProjectV2Policy
) -> None:
    for view in policy.views:
        report.entries.append(
            ReconciliationEntry(
                action=ReconciliationAction.HUMAN_ACTION_REQUIRED,
                resource="project_view",
                key=view.name,
                detail="configure and verify saved view in the GitHub UI",
                desired=view.model_dump(mode="json"),
            )
        )
    for workflow in policy.workflows:
        report.entries.append(
            ReconciliationEntry(
                action=ReconciliationAction.HUMAN_ACTION_REQUIRED,
                resource="project_workflow",
                key=workflow.name,
                detail="configure and verify built-in workflow in the GitHub UI",
                desired=workflow.model_dump(mode="json"),
            )
        )
