from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from .authorization import require_authorized
from .github import GitHubClient, GitHubResponseError
from .models import ChangeSpecification, LifecycleState
from .policy import load_policy
from .project_v2 import ProjectIdentityStore, ProjectV2Adapter
from .specification import (
    evaluate_readiness,
    parse_change_specification,
    readiness_attestation,
    render_change_specification,
)


class IssueError(RuntimeError):
    """An issue operation cannot satisfy the control-plane contract."""


class IssueAdapter:
    def __init__(self, client: GitHubClient, repository: str):
        self.client = client
        self.repository = repository

    def create(self, title: str, body: str, labels: list[str]) -> dict[str, object]:
        response = self.client.rest(
            f"repos/{self.repository}/issues",
            method="POST",
            payload={"title": title, "body": body, "labels": labels},
        )
        return self._issue(response)

    def get(self, number: int) -> dict[str, object]:
        return self._issue(self.client.rest(f"repos/{self.repository}/issues/{number}"))

    def replace_labels(self, number: int, labels: list[str]) -> None:
        self.client.rest(
            f"repos/{self.repository}/issues/{number}",
            method="PATCH",
            payload={"labels": labels},
        )

    def comment(self, number: int, body: str) -> None:
        self.client.rest(
            f"repos/{self.repository}/issues/{number}/comments",
            method="POST",
            payload={"body": body},
        )

    def add_sub_issue(self, parent_node_id: str, child_node_id: str) -> None:
        self.client.graphql(
            """
            mutation DevSpaceAddSubIssue($parent: ID!, $child: ID!) {
              addSubIssue(input: {issueId: $parent, subIssueId: $child}) {
                issue { id }
                subIssue { id }
              }
            }
            """,
            {"parent": parent_node_id, "child": child_node_id},
        )

    @staticmethod
    def _issue(response: object) -> dict[str, object]:
        if not isinstance(response, dict):
            raise GitHubResponseError("GitHub issue response is not an object")
        if not isinstance(response.get("number"), int):
            raise GitHubResponseError("GitHub issue response is missing number")
        return response


class IssueService:
    def __init__(
        self,
        repo: Path | str | None = None,
        *,
        client: GitHubClient | None = None,
        identity_store: ProjectIdentityStore | None = None,
    ):
        self.policy = load_policy(repo)
        self.client = client or GitHubClient()
        self.issues = IssueAdapter(self.client, self.policy.repository.full_name)
        self.projects = ProjectV2Adapter(self.client)
        self.identity_store = identity_store or ProjectIdentityStore()

    def create_change(self, parent: int, markdown: str) -> dict[str, object]:
        actor = self.client.current_user()
        require_authorized("issue.create-change", actor, self.policy)
        specification = parse_change_specification(markdown, parent)
        parent_issue = self.issues.get(parent)
        issue = self.issues.create(
            specification.title,
            render_change_specification(specification),
            self._labels(specification, LifecycleState.NEEDS_DEFINITION),
        )
        parent_node_id = parent_issue.get("node_id")
        child_node_id = issue.get("node_id")
        if not isinstance(parent_node_id, str) or not isinstance(child_node_id, str):
            raise IssueError("native hierarchy requires parent and child node IDs")
        self.issues.add_sub_issue(parent_node_id, child_node_id)
        item_id = self._add_to_project(child_node_id)
        self._set_initial_fields(item_id, specification)
        return issue

    def mark_ready(self, number: int) -> dict[str, object]:
        actor = self.client.current_user()
        require_authorized("issue.mark-ready", actor, self.policy)
        issue = self.issues.get(number)
        body = issue.get("body")
        if not isinstance(body, str):
            raise IssueError("issue body is missing the change specification")
        parent = self._parent_from_body(body)
        specification = parse_change_specification(body, parent)
        dependency_states = {
            dependency: str(self.issues.get(dependency).get("state", "unknown"))
            for dependency in specification.dependencies
        }
        readiness = evaluate_readiness(
            specification,
            dependencies_complete=all(
                state.casefold() == "closed" for state in dependency_states.values()
            ),
        )
        if not readiness.ready:
            raise IssueError("; ".join(readiness.violations))
        snapshot = self._project_snapshot()
        item = next(
            (
                item
                for item in snapshot.items
                if item.repository == self.policy.repository.full_name
                and item.number == number
            ),
            None,
        )
        if item is None:
            raise IssueError("issue is not present in the configured Project v2")
        identity = self._identity()
        self.projects.update_item_single_select(
            identity.project_id,
            item.id,
            identity.field_ids["Status"],
            identity.option_ids["Status"][LifecycleState.READY.value],
        )
        self.issues.replace_labels(
            number,
            self._replace_managed_labels(
                issue, self._labels(specification, LifecycleState.READY)
            ),
        )
        self.issues.comment(
            number,
            readiness_attestation(
                specification,
                actor=actor,
                dependency_states=dependency_states,
                timestamp=datetime.now(UTC).isoformat(),
            ),
        )
        return issue

    def issue_with_project_item(self, number: int):
        issue = self.issues.get(number)
        snapshot = self._project_snapshot()
        item = next(
            (
                item
                for item in snapshot.items
                if item.repository == self.policy.repository.full_name
                and item.number == number
            ),
            None,
        )
        if item is None:
            raise IssueError("issue is not present in the configured Project v2")
        return issue, item

    def set_project_state(
        self,
        number: int,
        state: LifecycleState,
        *,
        development_branch: str | None = None,
    ) -> None:
        issue, item = self.issue_with_project_item(number)
        identity = self._identity()
        self.projects.update_item_single_select(
            identity.project_id,
            item.id,
            identity.field_ids["Status"],
            identity.option_ids["Status"][state.value],
        )
        if development_branch is not None:
            self.projects.update_item_text(
                identity.project_id,
                item.id,
                identity.field_ids["Development Branch"],
                development_branch,
            )
        body = issue.get("body")
        if not isinstance(body, str):
            raise IssueError("issue body is missing the change specification")
        specification = parse_change_specification(body, self._parent_from_body(body))
        labels = self._replace_managed_labels(issue, self._labels(specification, state))
        self.issues.replace_labels(number, labels)

    def _add_to_project(self, content_id: str) -> str:
        return self.projects.add_item(self._identity().project_id, content_id)

    def _set_initial_fields(
        self, item_id: str, specification: ChangeSpecification
    ) -> None:
        identity = self._identity()
        values = {
            "Status": LifecycleState.NEEDS_DEFINITION.value,
            "Work Type": "Change",
            "Execution": specification.execution.value,
            "Risk": specification.risk.value,
        }
        for field, option in values.items():
            self.projects.update_item_single_select(
                identity.project_id,
                item_id,
                identity.field_ids[field],
                identity.option_ids[field][option],
            )

    def _identity(self):
        identity = self.identity_store.load(
            self.policy.repository.owner, self.policy.repository.name
        )
        if identity is None:
            raise IssueError("Project identity is missing; run project apply first")
        return identity

    def _project_snapshot(self):
        identity = self._identity()
        return self.projects.snapshot(identity.owner, identity.project_number)

    def _labels(
        self, specification: ChangeSpecification, status: LifecycleState
    ) -> list[str]:
        return [
            "type:change",
            f"execution:{specification.execution.value.casefold()}",
            f"risk:{specification.risk.value.casefold()}",
            f"status:{status.value.casefold().replace(' ', '-')}",
        ]

    def _replace_managed_labels(
        self, issue: dict[str, object], desired: list[str]
    ) -> list[str]:
        configured = {label.name for label in self.policy.labels}
        raw_labels = issue.get("labels", [])
        existing = {
            label.get("name")
            for label in raw_labels
            if isinstance(label, dict) and isinstance(label.get("name"), str)
        }
        return sorted((existing - configured) | set(desired))

    @staticmethod
    def _parent_from_body(body: str) -> int:
        marker = "## Parent Epic"
        if marker not in body:
            raise IssueError("issue body is missing Parent Epic")
        remainder = body.split(marker, 1)[1]
        import re

        match = re.search(r"#(\d+)", remainder)
        if not match:
            raise IssueError("Parent Epic is not an issue number")
        return int(match.group(1))
