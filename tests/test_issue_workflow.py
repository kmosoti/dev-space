from __future__ import annotations

from pathlib import Path

import pytest

from dev_space.control_plane.issues import IssueError, IssueService
from dev_space.control_plane.models import ExecutionMode, LifecycleState, Risk
from dev_space.control_plane.project_v2 import (
    ProjectIdentity,
    ProjectIdentityStore,
    ProjectItemSnapshot,
    ProjectSnapshot,
)
from dev_space.control_plane.specification import (
    SpecificationError,
    evaluate_readiness,
    parse_change_specification,
    readiness_attestation,
    render_change_specification,
    specification_hash,
)

pytestmark = pytest.mark.no_observability


SPECIFICATION = """# Add control-plane contracts

## Problem

The workflow is not executable.

## Current Behavior

Rules exist only in prose.

## Required Behavior

Rules are validated before mutation.

## Scope

- Add typed models
- Add lifecycle validation

## Non-goals

- Launch Codex

## Design

Use pure domain functions and typed adapters.

## Affected Components

- CLI
- Project adapter

## Security

Keep planner and worker identities separate.

## Compatibility

Schema version one rejects future versions.

## Tests

- Validate every transition
- Validate actor boundaries

## Rollout

Land the contract before mutating GitHub.

## Rollback

Revert the contract commit before Project apply.

## Dependencies

- #10

## Acceptance Criteria

- [ ] Invalid transitions fail
- [ ] Worker cannot mark Ready

## Unresolved Decisions

None

## Execution

Agent-ready

## Risk

Medium
"""


class FakeIssueClient:
    def __init__(self, body):
        self.body = body
        self.rest_calls = []
        self.graphql_calls = []

    def current_user(self):
        return "kmosoti"

    def rest(self, endpoint, *, method="GET", payload=None):
        self.rest_calls.append((endpoint, method, payload))
        if endpoint.endswith("/issues/100"):
            return {"number": 100, "node_id": "PARENT", "body": "Epic", "labels": []}
        if endpoint.endswith("/issues/10"):
            return {
                "number": 10,
                "node_id": "DEPENDENCY",
                "state": "closed",
                "labels": [],
            }
        if endpoint.endswith("/issues/101") and method == "GET":
            return {
                "number": 101,
                "node_id": "CHILD",
                "state": "open",
                "body": self.body,
                "labels": [{"name": "unmanaged"}, {"name": "status:needs-definition"}],
            }
        if endpoint.endswith("/issues") and method == "POST":
            return {
                "number": 101,
                "node_id": "CHILD",
                "state": "open",
                "body": payload["body"],
                "labels": [{"name": name} for name in payload["labels"]],
            }
        return payload or {}

    def graphql(self, query, variables=None):
        self.graphql_calls.append((query, variables))
        return {"addSubIssue": {"issue": {"id": "PARENT"}, "subIssue": {"id": "CHILD"}}}


class FakeProjects:
    def __init__(self):
        self.calls = []

    def add_item(self, project_id, content_id):
        self.calls.append(("add", project_id, content_id))
        return "ITEM"

    def update_item_single_select(self, project_id, item_id, field_id, option_id):
        self.calls.append(("select", project_id, item_id, field_id, option_id))

    def update_item_text(self, project_id, item_id, field_id, text):
        self.calls.append(("text", project_id, item_id, field_id, text))

    def snapshot(self, owner, number):
        self.calls.append(("snapshot", owner, number))
        return ProjectSnapshot(
            owner="kmosoti",
            id="PROJECT",
            number=6,
            title="dev-space",
            items=[
                ProjectItemSnapshot(
                    id="ITEM",
                    type="ISSUE",
                    repository="kmosoti/dev-space",
                    number=101,
                    title="Add control-plane contracts",
                )
            ],
        )


def identity_store(tmp_path):
    store = ProjectIdentityStore(tmp_path)
    options = {
        "Status": {
            LifecycleState.NEEDS_DEFINITION.value: "STATUS_NEEDS",
            LifecycleState.READY.value: "STATUS_READY",
            LifecycleState.IN_PROGRESS.value: "STATUS_IN_PROGRESS",
        },
        "Work Type": {"Change": "TYPE_CHANGE"},
        "Execution": {ExecutionMode.AGENT_READY.value: "EXEC_AGENT"},
        "Risk": {Risk.MEDIUM.value: "RISK_MEDIUM"},
    }
    store.save(
        ProjectIdentity(
            owner="kmosoti",
            repository="dev-space",
            project_id="PROJECT",
            project_number=6,
            field_ids={
                "Status": "FIELD_STATUS",
                "Work Type": "FIELD_TYPE",
                "Execution": "FIELD_EXECUTION",
                "Risk": "FIELD_RISK",
                "Development Branch": "FIELD_BRANCH",
            },
            option_ids=options,
        )
    )
    return store


def test_markdown_specification_round_trip_and_hash():
    parsed = parse_change_specification(SPECIFICATION, 100)
    rendered = render_change_specification(parsed)
    reparsed = parse_change_specification(rendered, 100)

    assert parsed.execution == ExecutionMode.AGENT_READY
    assert parsed.risk == Risk.MEDIUM
    assert parsed.dependencies == [10]
    assert parsed.unresolved_decisions == []
    assert reparsed == parsed
    assert specification_hash(reparsed) == specification_hash(parsed)


def test_specification_rejects_missing_sections_and_readiness_gates():
    with pytest.raises(SpecificationError, match="missing specification sections"):
        parse_change_specification("# Too small\n\n## Problem\n\nNo contract", 1)

    parsed = parse_change_specification(SPECIFICATION, 100)
    accepted = evaluate_readiness(parsed, dependencies_complete=True)
    blocked = evaluate_readiness(parsed, dependencies_complete=False)
    assert accepted.ready is True
    assert blocked.ready is False
    assert blocked.violations == ["dependencies are incomplete"]


def test_readiness_attestation_is_machine_readable_and_stable():
    parsed = parse_change_specification(SPECIFICATION, 100)
    comment = readiness_attestation(
        parsed,
        actor="kmosoti",
        dependency_states={10: "closed"},
        timestamp="2026-06-18T12:00:00+00:00",
    )

    assert "dev-space:readiness-attestation:v1" in comment
    assert '"actor": "kmosoti"' in comment
    assert specification_hash(parsed) in comment


def test_create_change_links_hierarchy_project_and_initial_fields(tmp_path):
    client = FakeIssueClient(SPECIFICATION)
    service = IssueService(
        Path(__file__).parents[1],
        client=client,
        identity_store=identity_store(tmp_path),
    )
    projects = FakeProjects()
    service.projects = projects

    issue = service.create_change(100, SPECIFICATION)

    assert issue["number"] == 101
    assert len(client.graphql_calls) == 1
    assert projects.calls[0] == ("add", "PROJECT", "CHILD")
    assert sum(call[0] == "select" for call in projects.calls) == 4


def test_mark_ready_updates_project_before_labels_and_attests(tmp_path):
    parsed = parse_change_specification(SPECIFICATION, 100)
    body = render_change_specification(parsed)
    client = FakeIssueClient(body)
    service = IssueService(
        Path(__file__).parents[1],
        client=client,
        identity_store=identity_store(tmp_path),
    )
    projects = FakeProjects()
    service.projects = projects

    issue = service.mark_ready(101)
    patch_call = next(call for call in client.rest_calls if call[1] == "PATCH")
    comment_call = next(
        call for call in client.rest_calls if call[0].endswith("/comments")
    )

    assert issue["number"] == 101
    assert projects.calls[-1] == (
        "select",
        "PROJECT",
        "ITEM",
        "FIELD_STATUS",
        "STATUS_READY",
    )
    assert "unmanaged" in patch_call[2]["labels"]
    assert "status:ready" in patch_call[2]["labels"]
    assert "status:needs-definition" not in patch_call[2]["labels"]
    assert "readiness-attestation" in comment_call[2]["body"]


def test_mark_ready_refuses_missing_project_identity(tmp_path):
    client = FakeIssueClient(
        render_change_specification(parse_change_specification(SPECIFICATION, 100))
    )
    service = IssueService(
        Path(__file__).parents[1],
        client=client,
        identity_store=ProjectIdentityStore(tmp_path),
    )
    service.projects = FakeProjects()

    with pytest.raises(IssueError, match="Project identity is missing"):
        service.mark_ready(101)
    assert client.current_user() == "kmosoti"


def test_set_project_state_updates_authoritative_status_branch_and_projection(tmp_path):
    body = render_change_specification(parse_change_specification(SPECIFICATION, 100))
    client = FakeIssueClient(body)
    service = IssueService(
        Path(__file__).parents[1],
        client=client,
        identity_store=identity_store(tmp_path),
    )
    projects = FakeProjects()
    service.projects = projects

    service.set_project_state(
        101,
        LifecycleState.IN_PROGRESS,
        development_branch="mutation/issue-101-contract",
    )

    assert projects.calls[-2] == (
        "select",
        "PROJECT",
        "ITEM",
        "FIELD_STATUS",
        "STATUS_IN_PROGRESS",
    )
    assert projects.calls[-1] == (
        "text",
        "PROJECT",
        "ITEM",
        "FIELD_BRANCH",
        "mutation/issue-101-contract",
    )
    patch = next(call for call in client.rest_calls if call[1] == "PATCH")
    assert "status:in-progress" in patch[2]["labels"]


def test_parent_parser_and_specification_optional_values_reject_bad_input():
    with pytest.raises(IssueError, match="missing Parent Epic"):
        IssueService._parent_from_body("no parent")
    with pytest.raises(IssueError, match="not an issue number"):
        IssueService._parent_from_body("## Parent Epic\n\nunknown")
    with pytest.raises(SpecificationError, match="dependencies must be issue numbers"):
        parse_change_specification(SPECIFICATION.replace("- #10", "- unknown"), 100)
    assert IssueService._parent_from_body("## Parent Epic\n\n#12") == 12
