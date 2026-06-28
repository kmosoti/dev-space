from __future__ import annotations

from pathlib import Path

import pytest

from dev_space.control_plane.github import GitHubConflictError, GitHubResponseError
from dev_space.control_plane.policy import load_policy
from dev_space.control_plane.project_service import ProjectService
from dev_space.control_plane.project_v2 import (
    ProjectIdentity,
    ProjectIdentityStore,
    ProjectSnapshot,
    ProjectV2Adapter,
)
from dev_space.control_plane.reconciliation import ReconciliationAction

pytestmark = pytest.mark.no_observability


class QueueClient:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []

    def graphql(self, query, variables=None):
        self.calls.append((query, variables))
        return self.responses.pop(0)


class EndpointClient:
    def __init__(self, *, workflows=True, auto_merge=True, rulesets=None):
        self.workflows = workflows
        self.auto_merge = auto_merge
        self.rulesets = list(rulesets or [])
        self.calls = []

    def current_user(self):
        return "kmosoti"

    def rest(self, endpoint, *, method="GET", payload=None):
        self.calls.append((endpoint, method, payload))
        if "/labels" in endpoint and method == "GET":
            return []
        if "/contents/.github/workflows/" in endpoint:
            return {"type": "file"} if self.workflows else {}
        if endpoint.endswith("/rulesets") and method == "GET":
            return self.rulesets
        if endpoint == "repos/kmosoti/dev-space" and method == "GET":
            return {"allow_auto_merge": self.auto_merge}
        return payload or {}


def empty_project(number=6, project_id="PROJECT"):
    return ProjectSnapshot(
        owner="kmosoti",
        id=project_id,
        number=number,
        title="dev-space",
        url=f"https://github.com/users/kmosoti/projects/{number}",
    )


def test_project_adapter_paginates_projects_and_items():
    project = {
        "id": "PROJECT",
        "number": 6,
        "title": "dev-space",
        "shortDescription": "",
        "readme": "",
        "public": False,
        "closed": False,
        "url": "https://example.test/6",
        "repositories": {"nodes": []},
        "fields": {"nodes": []},
        "items": {
            "nodes": [],
            "pageInfo": {"hasNextPage": True, "endCursor": "NEXT"},
        },
    }
    project_last = dict(project)
    project_last["items"] = {
        "nodes": [
            {
                "id": "ITEM",
                "type": "DRAFT_ISSUE",
                "isArchived": False,
                "content": {"id": "DRAFT", "title": "Draft"},
                "fieldValues": {"nodes": []},
            }
        ],
        "pageInfo": {"hasNextPage": False, "endCursor": None},
    }
    client = QueueClient(
        [
            {
                "user": {
                    "projectsV2": {
                        "nodes": [{"number": 5, "title": "other"}],
                        "pageInfo": {"hasNextPage": True, "endCursor": "P2"},
                    }
                }
            },
            {
                "user": {
                    "projectsV2": {
                        "nodes": [{"number": 6, "title": "dev-space"}],
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                    }
                }
            },
            {"user": {"projectV2": project}},
            {"user": {"projectV2": project_last}},
        ]
    )
    adapter = ProjectV2Adapter(client)

    matches = adapter.find_projects("kmosoti", "dev-space")
    snapshot = adapter.snapshot("kmosoti", 6)

    assert matches == [{"number": 6, "title": "dev-space"}]
    assert snapshot.items[0].title == "Draft"
    assert len(client.calls) == 4


def test_project_adapter_executes_all_supported_mutations():
    client = QueueClient(
        [
            {"user": {"id": "OWNER"}},
            {"repository": {"id": "REPO"}},
            {"createProjectV2": {"projectV2": {"id": "PROJECT", "number": 6}}},
            {"updateProjectV2": {"projectV2": {"id": "PROJECT"}}},
            {"linkProjectV2ToRepository": {"repository": {"id": "REPO"}}},
            {"createProjectV2Field": {"projectV2Field": {"id": "FIELD"}}},
            {"updateProjectV2Field": {"projectV2Field": {"id": "FIELD"}}},
            {"addProjectV2ItemById": {"item": {"id": "ITEM"}}},
            {"updateProjectV2ItemFieldValue": {"projectV2Item": {"id": "ITEM"}}},
            {"updateProjectV2ItemFieldValue": {"projectV2Item": {"id": "ITEM"}}},
        ]
    )
    adapter = ProjectV2Adapter(client)

    assert adapter.owner_id("kmosoti") == "OWNER"
    assert adapter.repository_id("kmosoti", "dev-space") == "REPO"
    assert adapter.create_project("OWNER", "dev-space") == ("PROJECT", 6)
    adapter.update_project(
        "PROJECT",
        title="dev-space",
        short_description="short",
        readme="readme",
        public=False,
    )
    adapter.link_repository("PROJECT", "REPO")
    assert adapter.create_field("PROJECT", "Risk", "SINGLE_SELECT", []) == "FIELD"
    adapter.update_single_select_field("PROJECT", "FIELD", "Risk", [])
    assert client.calls[6][1] == {
        "input": {"fieldId": "FIELD", "name": "Risk", "singleSelectOptions": []}
    }
    assert adapter.add_item("PROJECT", "ISSUE") == "ITEM"
    adapter.update_item_single_select("PROJECT", "ITEM", "FIELD", "OPTION")
    adapter.update_item_text("PROJECT", "ITEM", "FIELD", "branch")
    assert len(client.calls) == 10


@pytest.mark.parametrize(
    ("method", "response", "message"),
    [
        ("owner_id", {"user": None}, "user was not found"),
        ("repository_id", {"repository": None}, "repository was not found"),
        ("create_project", {"createProjectV2": {}}, "missing projectV2"),
        ("add_item", {"addProjectV2ItemById": {}}, "missing item id"),
    ],
)
def test_project_adapter_rejects_incomplete_mutation_responses(
    method, response, message
):
    adapter = ProjectV2Adapter(QueueClient([response]))
    arguments = {
        "owner_id": ("missing",),
        "repository_id": ("owner", "missing"),
        "create_project": ("OWNER", "title"),
        "add_item": ("PROJECT", "ISSUE"),
    }[method]

    with pytest.raises(GitHubResponseError, match=message):
        getattr(adapter, method)(*arguments)
    assert arguments


def test_project_identity_store_round_trip(tmp_path):
    store = ProjectIdentityStore(tmp_path)
    identity = ProjectIdentity(
        owner="kmosoti",
        repository="dev-space",
        project_id="PROJECT",
        project_number=6,
    )
    path = store.save(identity)

    assert store.load("kmosoti", "dev-space") == identity
    assert path.read_text(encoding="utf-8").endswith("\n")
    assert store.load("kmosoti", "missing") is None


def test_project_service_plans_and_applies_repository_protection(monkeypatch, tmp_path):
    configured = load_policy(Path(__file__).parents[1])
    client = EndpointClient(workflows=True, auto_merge=True)
    service = ProjectService(
        configured, client=client, identity_store=ProjectIdentityStore(tmp_path)
    )
    snapshot = empty_project()
    monkeypatch.setattr(service, "locate", lambda: ([{"number": 6}], snapshot))

    report = service.plan()
    service._apply_repository_settings()

    ruleset = next(entry for entry in report.entries if entry.resource == "ruleset")
    auto_merge = next(
        entry for entry in report.entries if entry.resource == "repository_setting"
    )
    assert ruleset.action == ReconciliationAction.CREATE
    assert auto_merge.action == ReconciliationAction.UPDATE
    assert any(call[1] == "PATCH" for call in client.calls)
    assert any(
        call[1] == "POST" and call[0].endswith("rulesets") for call in client.calls
    )


def test_project_service_gates_ruleset_until_workflows_land(monkeypatch):
    configured = load_policy(Path(__file__).parents[1])
    client = EndpointClient(workflows=False, auto_merge=False)
    service = ProjectService(configured, client=client)
    monkeypatch.setattr(service, "locate", lambda: ([], None))

    report = service.plan()
    ruleset = next(entry for entry in report.entries if entry.resource == "ruleset")

    assert ruleset.action == ReconciliationAction.HUMAN_ACTION_REQUIRED
    assert "before activating" in ruleset.detail


def test_project_service_snapshot_rejects_missing_and_duplicate(monkeypatch):
    service = ProjectService(
        load_policy(Path(__file__).parents[1]), client=EndpointClient()
    )
    monkeypatch.setattr(service, "locate", lambda: ([], None))
    with pytest.raises(GitHubConflictError, match="does not exist"):
        service.snapshot()
    monkeypatch.setattr(service, "locate", lambda: ([{}, {}], None))
    with pytest.raises(GitHubConflictError, match="multiple Projects"):
        service.snapshot()
    assert service.policy.project.title == "dev-space"


@pytest.mark.parametrize(
    ("matches", "snapshot_value", "status"),
    [
        ([], None, "missing"),
        ([{}, {}], None, "conflict"),
        ([{"number": 6}], empty_project(), "ok"),
    ],
)
def test_project_doctor_reports_identity_states(
    monkeypatch, matches, snapshot_value, status
):
    service = ProjectService(
        load_policy(Path(__file__).parents[1]), client=EndpointClient()
    )
    monkeypatch.setattr(service, "locate", lambda: (matches, snapshot_value))
    monkeypatch.setattr(
        service.adapter,
        "list_projects",
        lambda _owner: [
            {
                "number": 6,
                "title": "dev-space",
                "viewerCanUpdate": True,
                "closed": False,
            }
        ],
    )

    report = service.doctor()
    project_check = next(
        check for check in report.checks if check.name == "project_identity"
    )

    assert project_check.status == status
    assert len(report.checks) == 5
    assert report.healthy is (status == "ok")


@pytest.mark.parametrize(
    ("actor", "projects", "healthy"),
    [
        (
            "kmosoti",
            [
                {
                    "number": 6,
                    "title": "dev-space",
                    "viewerCanUpdate": True,
                    "closed": False,
                },
                {
                    "number": 3,
                    "title": "archive",
                    "viewerCanUpdate": True,
                    "closed": True,
                },
            ],
            True,
        ),
        (
            "kz-harbringer",
            [
                {
                    "number": 6,
                    "title": "dev-space",
                    "viewerCanUpdate": True,
                    "closed": False,
                }
            ],
            False,
        ),
        (
            "kmosoti",
            [
                {
                    "number": 6,
                    "title": "dev-space",
                    "viewerCanUpdate": False,
                    "closed": False,
                }
            ],
            False,
        ),
        (
            "kmosoti",
            [{"number": 6, "title": "dev-space"}],
            False,
        ),
    ],
)
def test_project_doctor_checks_every_owner_project(
    monkeypatch, actor, projects, healthy
):
    client = EndpointClient()
    monkeypatch.setattr(client, "current_user", lambda: actor)
    service = ProjectService(load_policy(Path(__file__).parents[1]), client=client)
    monkeypatch.setattr(service, "locate", lambda: ([{"number": 6}], empty_project()))
    monkeypatch.setattr(service.adapter, "list_projects", lambda _owner: projects)

    report = service.doctor()

    assert report.healthy is healthy
    assert len(
        [check for check in report.checks if check.name.startswith("project_access:")]
    ) == len(projects)


class CreateAdapter:
    def __init__(self, final):
        self.final = final
        self.created = False
        self.calls = []

    def find_projects(self, owner, title):
        self.calls.append(("find", owner, title))
        return (
            [] if not self.created else [{"number": self.final.number, "title": title}]
        )

    def owner_id(self, owner):
        return "OWNER"

    def create_project(self, owner, title):
        self.calls.append(("create_project", owner, title))
        self.created = True
        return self.final.id, self.final.number

    def snapshot(self, owner, number):
        self.calls.append(("snapshot", owner, number))
        return self.final

    def update_project(self, project_id, **kwargs):
        self.calls.append(("update_project", project_id, kwargs))

    def repository_id(self, owner, name):
        return "REPOSITORY"

    def link_repository(self, project_id, repository_id):
        self.calls.append(("link", project_id, repository_id))

    def create_field(self, project_id, name, data_type, options):
        self.calls.append(("field", project_id, name, data_type, options))
        return name

    def update_single_select_field(self, *args):
        self.calls.append(("update_field", *args))


def test_project_apply_creates_missing_project_and_all_fields(tmp_path):
    configured = load_policy(Path(__file__).parents[1])
    client = EndpointClient(workflows=False, auto_merge=False)
    service = ProjectService(
        configured, client=client, identity_store=ProjectIdentityStore(tmp_path)
    )
    adapter = CreateAdapter(empty_project(number=9, project_id="NEW"))
    service.adapter = adapter

    before, final = service.apply()
    identity = service.identity_store.load("kmosoti", "dev-space")
    names = [call[0] for call in adapter.calls]

    assert before.requires_changes is True
    assert final.id == "NEW"
    assert "create_project" in names
    assert names.count("field") == len(configured.project.fields)
    assert identity is not None
    assert identity.project_number == 9
