from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .authorization import require_authorized
from .github import GitHubClient, GitHubConflictError, GitHubError
from .models import ProjectFieldType, ProjectPolicy
from .policy import load_policy
from .project_v2 import (
    ProjectIdentity,
    ProjectIdentityStore,
    ProjectSnapshot,
    ProjectV2Adapter,
)
from .reconciliation import ReconciliationReport, build_reconciliation_report
from .reconciliation import (
    ReconciliationAction,
    ReconciliationEntry,
)


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class DoctorReport:
    checks: tuple[DoctorCheck, ...]

    @property
    def healthy(self) -> bool:
        return all(
            check.status in {"ok", "human_action_required"} for check in self.checks
        )


class ProjectService:
    def __init__(
        self,
        policy: ProjectPolicy,
        client: GitHubClient | None = None,
        identity_store: ProjectIdentityStore | None = None,
    ):
        self.policy = policy
        self.client = client or GitHubClient()
        self.adapter = ProjectV2Adapter(self.client)
        self.identity_store = identity_store or ProjectIdentityStore()

    @classmethod
    def from_repo(
        cls,
        repo: Path | str | None = None,
        client: GitHubClient | None = None,
        identity_store: ProjectIdentityStore | None = None,
    ) -> ProjectService:
        return cls(load_policy(repo), client, identity_store)

    def locate(self) -> tuple[list[dict[str, object]], ProjectSnapshot | None]:
        matches = self.adapter.find_projects(
            self.policy.project.owner, self.policy.project.title
        )
        if len(matches) > 1:
            return matches, None
        if not matches:
            return matches, None
        number = matches[0].get("number")
        if not isinstance(number, int):
            raise GitHubConflictError("matched Project v2 is missing its number")
        return matches, self.adapter.snapshot(self.policy.project.owner, number)

    def plan(self) -> ReconciliationReport:
        matches, snapshot = self.locate()
        report = build_reconciliation_report(self.policy, matches, snapshot)
        self._add_label_plan(report)
        self._add_repository_plan(report)
        return report

    def snapshot(self) -> ProjectSnapshot:
        matches, snapshot = self.locate()
        if len(matches) > 1:
            raise GitHubConflictError("multiple Projects match the configured title")
        if snapshot is None:
            raise GitHubConflictError("configured Project v2 does not exist")
        return snapshot

    def doctor(self) -> DoctorReport:
        checks: list[DoctorCheck] = []
        actor = self.client.current_user()
        checks.append(DoctorCheck("github_actor", "ok", actor))
        matches, snapshot = self.locate()
        if len(matches) > 1:
            checks.append(
                DoctorCheck("project_identity", "conflict", "duplicate project title")
            )
        elif snapshot is None:
            checks.append(
                DoctorCheck("project_identity", "missing", "Project v2 must be created")
            )
        else:
            checks.append(
                DoctorCheck(
                    "project_identity",
                    "ok",
                    f"{snapshot.owner}/{snapshot.number} ({snapshot.id})",
                )
            )
        checks.append(
            DoctorCheck(
                "saved_views",
                "human_action_required",
                "GitHub UI verification is required for saved-view fidelity",
            )
        )
        checks.append(
            DoctorCheck(
                "built_in_workflows",
                "human_action_required",
                "GitHub UI verification is required for workflow fidelity",
            )
        )
        return DoctorReport(tuple(checks))

    def apply(self) -> tuple[ReconciliationReport, ProjectSnapshot]:
        actor = self.client.current_user()
        require_authorized("project.apply", actor, self.policy)
        before = self.plan()
        if before.has_conflicts:
            raise GitHubConflictError("cannot apply with reconciliation conflicts")
        matches, snapshot = self.locate()
        if not matches:
            owner_id = self.adapter.owner_id(self.policy.project.owner)
            _, project_number = self.adapter.create_project(
                owner_id, self.policy.project.title
            )
            snapshot = self.adapter.snapshot(self.policy.project.owner, project_number)
        assert snapshot is not None
        self.adapter.update_project(
            snapshot.id,
            title=self.policy.project.title,
            short_description=self.policy.project.short_description,
            readme=self.policy.project.readme,
            public=self.policy.project.public,
        )
        if self.policy.repository.full_name not in snapshot.repositories:
            repository_id = self.adapter.repository_id(
                self.policy.repository.owner, self.policy.repository.name
            )
            self.adapter.link_repository(snapshot.id, repository_id)

        actual_fields = {field.name: field for field in snapshot.fields}
        for desired in self.policy.project.fields:
            options = [
                {
                    "name": option.name,
                    "description": option.description,
                    "color": option.color,
                }
                for option in desired.options
            ]
            actual = actual_fields.get(desired.name)
            if actual is None:
                self.adapter.create_field(
                    snapshot.id, desired.name, desired.data_type, options
                )
            elif desired.data_type == ProjectFieldType.SINGLE_SELECT:
                actual_options = [
                    {
                        "name": option.name,
                        "description": option.description,
                        "color": option.color,
                    }
                    for option in actual.options
                ]
                if options != actual_options:
                    self.adapter.update_single_select_field(
                        snapshot.id, actual.id, desired.name, options
                    )

        self._apply_labels()
        self._apply_repository_settings()

        final_snapshot = self.adapter.snapshot(
            self.policy.project.owner, snapshot.number
        )
        self.identity_store.save(self._identity(final_snapshot))
        return before, final_snapshot

    def _identity(self, snapshot: ProjectSnapshot) -> ProjectIdentity:
        return ProjectIdentity(
            owner=self.policy.repository.owner,
            repository=self.policy.repository.name,
            project_id=snapshot.id,
            project_number=snapshot.number,
            field_ids={field.name: field.id for field in snapshot.fields},
            option_ids={
                field.name: {option.name: option.id for option in field.options}
                for field in snapshot.fields
                if field.options
            },
        )

    def _live_labels(self) -> dict[str, dict[str, object]]:
        response = self.client.rest(
            f"repos/{self.policy.repository.full_name}/labels?per_page=100"
        )
        if not isinstance(response, list):
            return {}
        return {
            str(label["name"]): label
            for label in response
            if isinstance(label, dict) and isinstance(label.get("name"), str)
        }

    def _add_label_plan(self, report: ReconciliationReport) -> None:
        live = self._live_labels()
        for desired in self.policy.labels:
            actual = live.get(desired.name)
            actual_value = (
                {
                    "color": str(actual.get("color", "")),
                    "description": str(actual.get("description", "")),
                }
                if actual
                else None
            )
            desired_value = {
                "color": desired.color.lower(),
                "description": desired.description,
            }
            action = ReconciliationAction.CREATE
            detail = "create managed label"
            if actual is not None:
                action = (
                    ReconciliationAction.UNCHANGED
                    if actual_value == desired_value
                    else ReconciliationAction.UPDATE
                )
                detail = (
                    "label matches"
                    if action == ReconciliationAction.UNCHANGED
                    else "managed label drift"
                )
            report.entries.append(
                ReconciliationEntry(
                    action=action,
                    resource="label",
                    key=desired.name,
                    detail=detail,
                    desired=desired_value,
                    actual=actual_value,
                )
            )

    def _apply_labels(self) -> None:
        live = self._live_labels()
        repository = self.policy.repository.full_name
        for desired in self.policy.labels:
            payload = {
                "name": desired.name,
                "color": desired.color.lower(),
                "description": desired.description,
            }
            if desired.name not in live:
                self.client.rest(
                    f"repos/{repository}/labels", method="POST", payload=payload
                )
                continue
            actual = live[desired.name]
            if (
                str(actual.get("color", "")).lower() != desired.color.lower()
                or str(actual.get("description", "")) != desired.description
            ):
                self.client.rest(
                    f"repos/{repository}/labels/{desired.name}",
                    method="PATCH",
                    payload=payload,
                )

    def _add_repository_plan(self, report: ReconciliationReport) -> None:
        repository = self.client.rest(f"repos/{self.policy.repository.full_name}")
        auto_merge = (
            bool(repository.get("allow_auto_merge", False))
            if isinstance(repository, dict)
            else False
        )
        report.entries.append(
            ReconciliationEntry(
                action=(
                    ReconciliationAction.UPDATE
                    if auto_merge
                    else ReconciliationAction.UNCHANGED
                ),
                resource="repository_setting",
                key="allow_auto_merge",
                detail="disable auto-merge" if auto_merge else "auto-merge is disabled",
                desired=False,
                actual=auto_merge,
            )
        )
        rulesets = self.client.rest(
            f"repos/{self.policy.repository.full_name}/rulesets"
        )
        matching = (
            [
                ruleset
                for ruleset in rulesets
                if isinstance(ruleset, dict)
                and ruleset.get("name") == self.policy.ruleset.name
            ]
            if isinstance(rulesets, list)
            else []
        )
        actual_ruleset = self._ruleset_detail(matching[0]) if matching else None
        desired_ruleset = self._ruleset_payload()
        workflows_ready = self._contract_workflows_exist()
        if not workflows_ready:
            action = ReconciliationAction.HUMAN_ACTION_REQUIRED
            detail = "land both required checks on the default branch before activating ruleset"
        elif not matching:
            action = ReconciliationAction.CREATE
            detail = "create managed main ruleset"
        elif self._ruleset_matches(desired_ruleset, actual_ruleset):
            action = ReconciliationAction.UNCHANGED
            detail = "managed main ruleset matches"
        else:
            action = ReconciliationAction.UPDATE
            detail = "reconcile managed main ruleset"
        report.entries.append(
            ReconciliationEntry(
                action=action,
                resource="ruleset",
                key=self.policy.ruleset.name,
                detail=detail,
                desired=desired_ruleset,
                actual=actual_ruleset,
            )
        )

    def _apply_repository_settings(self) -> None:
        repository = self.client.rest(f"repos/{self.policy.repository.full_name}")
        if isinstance(repository, dict) and repository.get("allow_auto_merge"):
            self.client.rest(
                f"repos/{self.policy.repository.full_name}",
                method="PATCH",
                payload={"allow_auto_merge": False},
            )
        if not self._contract_workflows_exist():
            return
        rulesets = self.client.rest(
            f"repos/{self.policy.repository.full_name}/rulesets"
        )
        matching = (
            [
                ruleset
                for ruleset in rulesets
                if isinstance(ruleset, dict)
                and ruleset.get("name") == self.policy.ruleset.name
            ]
            if isinstance(rulesets, list)
            else []
        )
        payload = self._ruleset_payload()
        if matching and isinstance(matching[0].get("id"), int):
            actual = self._ruleset_detail(matching[0])
            if not self._ruleset_matches(payload, actual):
                self.client.rest(
                    f"repos/{self.policy.repository.full_name}/rulesets/{matching[0]['id']}",
                    method="PUT",
                    payload=payload,
                )
        elif not matching:
            self.client.rest(
                f"repos/{self.policy.repository.full_name}/rulesets",
                method="POST",
                payload=payload,
            )

    def _ruleset_detail(self, summary: dict[str, object]) -> dict[str, object] | None:
        ruleset_id = summary.get("id")
        if not isinstance(ruleset_id, int):
            return None
        detail = self.client.rest(
            f"repos/{self.policy.repository.full_name}/rulesets/{ruleset_id}"
        )
        return detail if isinstance(detail, dict) else None

    @staticmethod
    def _ruleset_matches(
        desired: dict[str, object], actual: dict[str, object] | None
    ) -> bool:
        if actual is None:
            return False

        def project(value: object, template: object) -> object:
            if isinstance(template, dict):
                if not isinstance(value, dict):
                    return None
                return {
                    key: project(value.get(key), expected)
                    for key, expected in template.items()
                }
            if isinstance(template, list):
                if not isinstance(value, list):
                    return None
                return [
                    project(item, expected)
                    for item, expected in zip(value, template, strict=False)
                ]
            return value

        return project(actual, desired) == desired

    def _contract_workflows_exist(self) -> bool:
        paths = (
            ".github/workflows/pr-check.yml",
            ".github/workflows/control-plane-contract.yml",
        )
        for path in paths:
            try:
                response = self.client.rest(
                    f"repos/{self.policy.repository.full_name}/contents/{path}?ref={self.policy.repository.default_branch}"
                )
            except GitHubError:
                return False
            if not isinstance(response, dict) or response.get("type") != "file":
                return False
        return True

    def _ruleset_payload(self) -> dict[str, object]:
        return {
            "name": self.policy.ruleset.name,
            "target": "branch",
            "enforcement": self.policy.ruleset.enforcement,
            "bypass_actors": [],
            "conditions": {
                "ref_name": {
                    "include": ["~DEFAULT_BRANCH"],
                    "exclude": [],
                }
            },
            "rules": [
                {"type": "deletion"},
                {"type": "non_fast_forward"},
                {
                    "type": "pull_request",
                    "parameters": {
                        "required_approving_review_count": self.policy.ruleset.approvals,
                        "dismiss_stale_reviews_on_push": self.policy.ruleset.dismiss_stale_reviews,
                        "require_code_owner_review": self.policy.ruleset.require_code_owner_review,
                        "require_last_push_approval": self.policy.ruleset.require_last_push_approval,
                        "required_review_thread_resolution": self.policy.ruleset.require_conversation_resolution,
                    },
                },
                {
                    "type": "required_status_checks",
                    "parameters": {
                        "strict_required_status_checks_policy": True,
                        "do_not_enforce_on_create": True,
                        "required_status_checks": [
                            {"context": check} for check in self.policy.checks.required
                        ],
                    },
                },
            ],
        }
