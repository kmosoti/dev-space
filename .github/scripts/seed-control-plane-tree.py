#!/usr/bin/env python3
"""Seed the control-plane Epic tree from the canonical implementation plan."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

from dev_space.control_plane.authorization import require_authorized
from dev_space.control_plane.github import GitHubClient, GitHubResponseError
from dev_space.control_plane.policy import load_policy
from dev_space.control_plane.project_v2 import (
    ProjectIdentityStore,
    ProjectV2Adapter,
)

KEY_MARKER = re.compile(r"<!-- dev-space:planning-key=([^ ]+) -->")
TREE_ENTRY = re.compile(
    r"(?P<key>EPIC-CP\d+|CP\d+-\d{2})\s{2,}(?P<title>.*?)(?:\s{2,}<-\s(?P<dependencies>.*))?$"
)


@dataclass(frozen=True)
class PlannedIssue:
    key: str
    title: str
    parent: str | None
    dependencies: tuple[str, ...]

    @property
    def work_type(self) -> str:
        if self.key.startswith("EPIC-"):
            return "Epic"
        if self.title.casefold().startswith("decision:") or self.key == "CP7-06":
            return "Decision"
        return "Change"

    @property
    def execution(self) -> str:
        if self.work_type in {"Epic", "Decision"}:
            return "Human-only"
        if self.key in {"CP3-08", "CP7-03", "CP8-01", "CP8-03", "CP8-04"}:
            return "Agent-assisted"
        return "Agent-ready"

    @property
    def risk(self) -> str:
        return "High" if self.work_type == "Decision" else "Medium"


def parse_tree(plan: Path) -> list[PlannedIssue]:
    text = plan.read_text(encoding="utf-8")
    section = text.split("## Epic and issue dependency tree", 1)
    if len(section) != 2:
        raise ValueError("plan is missing the Epic and issue dependency tree")
    code_block = section[1].split("```text", 1)
    if len(code_block) != 2:
        raise ValueError("plan is missing the issue-tree text block")
    tree_text = code_block[1].split("```", 1)[0]

    result: list[PlannedIssue] = []
    keys: set[str] = set()
    for line in tree_text.splitlines():
        match = TREE_ENTRY.search(line)
        if match is None:
            continue
        key = match.group("key")
        if key in keys:
            raise ValueError(f"duplicate planning key: {key}")
        keys.add(key)
        parent = None
        if key != "EPIC-CP0":
            parent = (
                "EPIC-CP0"
                if key.startswith("EPIC-")
                else f"EPIC-{key.split('-', 1)[0]}"
            )
        raw_dependencies = match.group("dependencies") or ""
        dependencies = tuple(
            dependency.strip()
            for dependency in raw_dependencies.split(",")
            if dependency.strip()
        )
        result.append(
            PlannedIssue(
                key=key,
                title=match.group("title").strip(),
                parent=parent,
                dependencies=dependencies,
            )
        )

    if not result or result[0].key != "EPIC-CP0":
        raise ValueError("issue tree must begin with EPIC-CP0")
    unknown = {
        reference
        for item in result
        for reference in (item.parent, *item.dependencies)
        if reference is not None and reference not in keys
    }
    if unknown:
        raise ValueError(f"issue tree contains unknown references: {sorted(unknown)}")
    return result


class TreeSeeder:
    def __init__(self, repository: Path, plan: Path):
        self.repository = repository
        self.plan = plan
        self.policy = load_policy(repository)
        self.client = GitHubClient()
        self.projects = ProjectV2Adapter(self.client)
        self.items = parse_tree(plan)

    def run(self, *, dry_run: bool) -> dict[str, object]:
        actor = self.client.current_user()
        require_authorized("issue.create-change", actor, self.policy)
        existing = self._existing_issues()
        if dry_run:
            return {
                "actor": actor,
                "desired": len(self.items),
                "existing": len(existing),
                "create": [item.key for item in self.items if item.key not in existing],
            }

        issues = dict(existing)
        created: set[str] = set()
        for item in self.items:
            if item.key in issues:
                continue
            response = self.client.rest(
                f"repos/{self.policy.repository.full_name}/issues",
                method="POST",
                payload={
                    "title": f"[{item.key}] {item.title}",
                    "body": self._render_body(item, {}),
                    "labels": self._labels(item),
                },
            )
            issues[item.key] = self._issue(response)
            created.add(item.key)

        for item in self.items:
            issue = issues[item.key]
            if item.key in created or "<!-- dev-space:seed-managed=v1 -->" in str(
                issue.get("body", "")
            ):
                updated = self.client.rest(
                    f"repos/{self.policy.repository.full_name}/issues/{issue['number']}",
                    method="PATCH",
                    payload={
                        "title": f"[{item.key}] {item.title}",
                        "body": self._render_body(item, issues),
                        "labels": self._labels(item),
                    },
                )
                issues[item.key] = self._issue(updated)

        self._reconcile_relationships(issues)
        self._reconcile_project(issues)
        return {
            "actor": actor,
            "desired": len(self.items),
            "created": len(created),
            "issues": {item.key: issues[item.key]["number"] for item in self.items},
        }

    def _existing_issues(self) -> dict[str, dict[str, object]]:
        result: dict[str, dict[str, object]] = {}
        for page in range(1, 100):
            response = self.client.rest(
                f"repos/{self.policy.repository.full_name}/issues?state=all&per_page=100&page={page}"
            )
            if not isinstance(response, list):
                raise GitHubResponseError("GitHub issue list is not an array")
            for raw in response:
                if not isinstance(raw, dict) or "pull_request" in raw:
                    continue
                body = raw.get("body")
                marker = KEY_MARKER.search(body) if isinstance(body, str) else None
                if marker is not None:
                    key = marker.group(1)
                    if key in result:
                        raise RuntimeError(f"duplicate live planning key: {key}")
                    result[key] = self._issue(raw)
            if len(response) < 100:
                break
        return result

    def _reconcile_relationships(self, issues: dict[str, dict[str, object]]) -> None:
        for item in self.items:
            issue_id = str(issues[item.key]["node_id"])
            relationships = self.client.graphql(
                """
                query DevSpaceIssueRelationships($id: ID!) {
                  node(id: $id) {
                    ... on Issue {
                      subIssues(first: 100) { nodes { id } }
                      blockedBy(first: 100) { nodes { id } }
                    }
                  }
                }
                """,
                {"id": issue_id},
            )
            node = relationships.get("node")
            if not isinstance(node, dict):
                raise GitHubResponseError("issue relationship query is missing node")
            sub_issue_ids = self._connection_ids(node, "subIssues")
            blocked_by_ids = self._connection_ids(node, "blockedBy")
            if item.parent is not None:
                parent_id = str(issues[item.parent]["node_id"])
                parent_relationships = self.client.graphql(
                    """
                    query DevSpaceParentRelationships($id: ID!) {
                      node(id: $id) { ... on Issue { subIssues(first: 100) { nodes { id } } } }
                    }
                    """,
                    {"id": parent_id},
                )
                parent_node = parent_relationships.get("node")
                if not isinstance(parent_node, dict):
                    raise GitHubResponseError(
                        "parent relationship query is missing node"
                    )
                parent_children = self._connection_ids(parent_node, "subIssues")
                if issue_id not in parent_children:
                    self.client.graphql(
                        """
                        mutation DevSpaceAddSubIssue($parent: ID!, $child: ID!) {
                          addSubIssue(input: {issueId: $parent, subIssueId: $child}) {
                            issue { id }
                          }
                        }
                        """,
                        {"parent": parent_id, "child": issue_id},
                    )
            for dependency in item.dependencies:
                dependency_id = str(issues[dependency]["node_id"])
                if dependency_id not in blocked_by_ids:
                    self.client.graphql(
                        """
                        mutation DevSpaceAddBlockedBy($issue: ID!, $blocking: ID!) {
                          addBlockedBy(input: {issueId: $issue, blockingIssueId: $blocking}) {
                            issue { id }
                          }
                        }
                        """,
                        {"issue": issue_id, "blocking": dependency_id},
                    )
            if (
                sub_issue_ids
                and item.key != "EPIC-CP0"
                and not item.key.startswith("EPIC-")
            ):
                raise RuntimeError(
                    f"bounded issue {item.key} unexpectedly has children"
                )

    def _reconcile_project(self, issues: dict[str, dict[str, object]]) -> None:
        identity = ProjectIdentityStore().load(
            self.policy.repository.owner, self.policy.repository.name
        )
        if identity is None:
            raise RuntimeError("Project identity is missing; run project apply first")
        snapshot = self.projects.snapshot(identity.owner, identity.project_number)
        project_items = {
            item.number: item.id
            for item in snapshot.items
            if item.repository == self.policy.repository.full_name
            and item.number is not None
        }
        for item in self.items:
            issue = issues[item.key]
            number = int(issue["number"])
            item_id = project_items.get(number)
            if item_id is None:
                item_id = self.projects.add_item(
                    identity.project_id, str(issue["node_id"])
                )
                project_items[number] = item_id
                values = {
                    "Status": "Needs Definition",
                    "Work Type": item.work_type,
                    "Execution": item.execution,
                    "Risk": item.risk,
                }
                for field, option in values.items():
                    self.projects.update_item_single_select(
                        identity.project_id,
                        item_id,
                        identity.field_ids[field],
                        identity.option_ids[field][option],
                    )

    def _render_body(
        self, item: PlannedIssue, issues: dict[str, dict[str, object]]
    ) -> str:
        def reference(key: str) -> str:
            issue = issues.get(key)
            return f"#{issue['number']} (`{key}`)" if issue else f"`{key}`"

        parent = (
            reference(item.parent) if item.parent else "None (root control-plane Epic)"
        )
        dependencies = (
            "\n".join(f"- Blocked by {reference(key)}" for key in item.dependencies)
            if item.dependencies
            else "- None"
        )
        kind = (
            "overall plan"
            if item.work_type == "Epic"
            else "bounded implementation slice"
        )
        return f"""<!-- dev-space:planning-key={item.key} -->
<!-- dev-space:seed-managed=v1 -->

## Outcome

Deliver the {kind}: **{item.title}**.

## Parent Epic

{parent}

## Dependencies

{dependencies}

## Scope

This issue owns only the `{item.key}` slice defined in `docs/github-control-plane-plan.md`. Unrelated work and child-issue implementation are excluded.

## Acceptance criteria

- The bounded result described by `{item.key}` is implemented or recorded with reviewable evidence.
- The declared dependency edges remain satisfied.
- The smallest relevant verification from the source plan passes.
- Any new follow-up is captured as a separate bounded issue.

## Classification

- Work Type: {item.work_type}
- Execution: {item.execution}
- Risk: {item.risk}

## Source of truth

The issue body and native GitHub relationships own this slice's live scope. The repository plan records the bootstrap design; Project v2 owns operational status.
"""

    @staticmethod
    def _labels(item: PlannedIssue) -> list[str]:
        return [
            f"type:{item.work_type.casefold()}",
            f"execution:{item.execution.casefold()}",
            f"risk:{item.risk.casefold()}",
            "status:needs-definition",
        ]

    @staticmethod
    def _issue(response: object) -> dict[str, object]:
        if not isinstance(response, dict):
            raise GitHubResponseError("GitHub issue response is not an object")
        if not isinstance(response.get("number"), int) or not isinstance(
            response.get("node_id"), str
        ):
            raise GitHubResponseError("GitHub issue response is missing identity")
        return response

    @staticmethod
    def _connection_ids(node: dict[str, object], key: str) -> set[str]:
        connection = node.get(key)
        nodes = connection.get("nodes") if isinstance(connection, dict) else None
        if not isinstance(nodes, list):
            raise GitHubResponseError(f"issue relationship query is missing {key}")
        return {
            str(entry["id"])
            for entry in nodes
            if isinstance(entry, dict) and isinstance(entry.get("id"), str)
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    arguments = parser.parse_args()
    report = TreeSeeder(arguments.repo.resolve(), arguments.plan.resolve()).run(
        dry_run=arguments.dry_run
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
