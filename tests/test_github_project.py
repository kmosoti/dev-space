from __future__ import annotations

import json
from pathlib import Path

import pytest

from dev_space.control_plane.github import (
    GitHubClient,
    GitHubResponseError,
)
from dev_space.control_plane.policy import load_policy
from dev_space.control_plane.project_service import ProjectService
from dev_space.control_plane.project_v2 import (
    ProjectFieldSnapshot,
    ProjectIdentityStore,
    ProjectOptionSnapshot,
    ProjectSnapshot,
    ProjectV2Adapter,
)
from dev_space.control_plane.reconciliation import (
    ReconciliationAction,
    build_reconciliation_report,
)

pytestmark = pytest.mark.no_observability


class FakeRunner:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def run(self, arguments, input_text=None):
        self.calls.append((arguments, input_text))
        return json.dumps(self.responses.pop(0))


class FakeClient:
    def __init__(self):
        self.calls = []

    def current_user(self):
        return "kmosoti"

    def rest(self, endpoint, *, method="GET", payload=None):
        self.calls.append((endpoint, method, payload))
        if method == "GET":
            return []
        return payload


class FakeAdapter:
    def __init__(self, snapshots):
        self.snapshots = list(snapshots)
        self.calls = []

    def find_projects(self, owner, title):
        self.calls.append(("find", owner, title))
        snapshot = self.snapshots[0] if self.snapshots else None
        return [] if snapshot is None else [{"number": snapshot.number, "title": title}]

    def snapshot(self, owner, number):
        self.calls.append(("snapshot", owner, number))
        return self.snapshots.pop(0)

    def owner_id(self, login):
        self.calls.append(("owner_id", login))
        return "U_owner"

    def create_project(self, owner_id, title):
        self.calls.append(("create_project", owner_id, title))
        return "P_new", 7

    def update_project(self, project_id, **metadata):
        self.calls.append(("update_project", project_id, metadata))

    def repository_id(self, owner, name):
        self.calls.append(("repository_id", owner, name))
        return "R_repo"

    def link_repository(self, project_id, repository_id):
        self.calls.append(("link_repository", project_id, repository_id))

    def create_field(self, project_id, name, data_type, options):
        self.calls.append(("create_field", project_id, name, data_type, options))
        return f"FIELD_{name}"

    def update_single_select_field(self, project_id, field_id, name, options):
        self.calls.append(("update_field", project_id, field_id, name, options))


def policy():
    return load_policy(Path(__file__).parents[1])


def snapshot(*, complete=False):
    configured = policy()
    fields = []
    if complete:
        for position, desired in enumerate(configured.project.fields):
            fields.append(
                ProjectFieldSnapshot(
                    id=f"FIELD_{position}",
                    name=desired.name,
                    data_type=desired.data_type,
                    position=position,
                    options=[
                        ProjectOptionSnapshot(
                            id=f"OPTION_{position}_{option_position}",
                            name=option.name,
                            description=option.description,
                            color=option.color,
                            position=option_position,
                        )
                        for option_position, option in enumerate(desired.options)
                    ],
                )
            )
    return ProjectSnapshot(
        owner="kmosoti",
        id="PVT_project",
        number=6,
        title="dev-space",
        short_description=(configured.project.short_description if complete else "old"),
        readme=configured.project.readme if complete else "",
        public=False,
        url="https://github.com/users/kmosoti/projects/6",
        repositories=["kmosoti/dev-space"] if complete else [],
        fields=fields,
    )


def test_github_client_uses_structured_stdin_and_validates_graphql():
    runner = FakeRunner([{"data": {"viewer": {"login": "kmosoti"}}}])
    client = GitHubClient(runner)

    data = client.graphql("query($value: String!) { viewer { login } }", {"value": "x"})
    arguments, input_text = runner.calls[0]
    assert data == {"viewer": {"login": "kmosoti"}}
    assert arguments == ["api", "graphql", "--input", "-"]
    assert json.loads(input_text)["variables"] == {"value": "x"}

    error_client = GitHubClient(FakeRunner([{"errors": [{"message": "denied"}]}]))
    with pytest.raises(GitHubResponseError, match="GraphQL errors"):
        error_client.graphql("query { viewer { login } }")


def test_github_client_rest_and_invalid_json():
    runner = FakeRunner([{"login": "kmosoti"}])
    assert GitHubClient(runner).current_user() == "kmosoti"
    assert runner.calls[0][0] == ["api", "user", "--method", "GET"]

    invalid = FakeRunner([])
    invalid.run = lambda arguments, input_text=None: "not-json"
    with pytest.raises(GitHubResponseError, match="invalid JSON"):
        GitHubClient(invalid).rest("user")


def test_project_snapshot_parser_preserves_fields_items_and_capabilities():
    raw = {
        "id": "P1",
        "number": 6,
        "title": "dev-space",
        "shortDescription": "Control plane",
        "readme": "README",
        "public": False,
        "closed": False,
        "url": "https://example.test/project",
        "repositories": {"nodes": [{"nameWithOwner": "kmosoti/dev-space"}]},
        "fields": {
            "nodes": [
                {
                    "id": "F1",
                    "name": "Status",
                    "dataType": "SINGLE_SELECT",
                    "options": [
                        {
                            "id": "O1",
                            "name": "Ready",
                            "description": "Ready",
                            "color": "BLUE",
                        }
                    ],
                }
            ]
        },
    }
    items = [
        {
            "id": "I1",
            "type": "ISSUE",
            "isArchived": False,
            "content": {
                "id": "ISSUE1",
                "number": 12,
                "title": "Implement",
                "url": "https://example.test/issues/12",
                "repository": {"nameWithOwner": "kmosoti/dev-space"},
            },
            "fieldValues": {
                "nodes": [
                    {
                        "name": "Ready",
                        "optionId": "O1",
                        "field": {"name": "Status"},
                    }
                ]
            },
        }
    ]

    parsed = ProjectV2Adapter._parse_snapshot("kmosoti", raw, items)
    assert parsed.fields[0].options[0].name == "Ready"
    assert parsed.items[0].field_values == {"Status": "Ready"}
    assert parsed.repositories == ["kmosoti/dev-space"]
    assert [record.concern for record in parsed.capabilities] == [
        "metadata_fields_items",
        "views",
        "built_in_workflows",
    ]


def test_reconciliation_plans_creation_and_manual_fidelity():
    report = build_reconciliation_report(policy(), [], None)
    actions = [entry.action for entry in report.entries]

    assert actions[0] == ReconciliationAction.CREATE
    assert sum(action == ReconciliationAction.CREATE for action in actions) == 6
    assert (
        sum(action == ReconciliationAction.HUMAN_ACTION_REQUIRED for action in actions)
        == 8
    )
    assert report.requires_changes is True
    assert report.has_conflicts is False
    assert "project_view" in report.markdown()


def test_reconciliation_detects_duplicate_and_unchanged_project():
    configured = policy()
    duplicate = build_reconciliation_report(
        configured,
        [{"number": 1}, {"number": 2}],
        None,
    )
    unchanged = build_reconciliation_report(
        configured, [{"number": 6}], snapshot(complete=True)
    )

    assert duplicate.has_conflicts is True
    assert duplicate.entries[0].action == ReconciliationAction.CONFLICT
    assert not any(
        entry.action == ReconciliationAction.UPDATE
        for entry in unchanged.entries
        if entry.resource not in {"project_view", "project_workflow"}
    )


def test_project_service_apply_reconciles_and_persists_identity(tmp_path):
    configured = policy()
    initial = snapshot(complete=False)
    final = snapshot(complete=True)
    client = FakeClient()
    service = ProjectService(
        configured,
        client=client,
        identity_store=ProjectIdentityStore(tmp_path),
    )
    adapter = FakeAdapter([initial, initial, final])
    service.adapter = adapter

    before, applied = service.apply()
    identity = service.identity_store.load("kmosoti", "dev-space")
    call_names = [call[0] for call in adapter.calls]

    assert before.requires_changes is True
    assert applied.fields[0].name == "Status"
    assert "update_project" in call_names
    assert "link_repository" in call_names
    assert call_names.count("create_field") == 5
    assert sum(
        call[1] == "POST" and call[0].endswith("/labels") for call in client.calls
    ) == len(configured.labels)
    assert identity is not None
    assert identity.project_number == 6
    assert identity.field_ids["Status"] == "FIELD_0"


def test_project_identity_store_rejects_unsafe_names(tmp_path):
    store = ProjectIdentityStore(tmp_path)
    assert store.root == tmp_path
    with pytest.raises(ValueError, match="simple GitHub names"):
        store.path_for("bad/owner", "repo")
