from __future__ import annotations

import json
import os
import tempfile
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .github import GitHubClient, GitHubResponseError


class Capability(StrEnum):
    API_READ_WRITE = "api_read_write"
    API_READ_ONLY = "api_read_only"
    UI_ONLY = "ui_only"
    UNSUPPORTED = "unsupported"
    HUMAN_ACTION_REQUIRED = "human_action_required"


class ProjectOptionSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str = ""
    color: str = "GRAY"
    position: int


class ProjectFieldSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    data_type: str
    position: int
    options: list[ProjectOptionSnapshot] = Field(default_factory=list)


class ProjectItemSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: str
    archived: bool = False
    content_id: str | None = None
    repository: str | None = None
    number: int | None = None
    title: str = ""
    url: str | None = None
    field_values: dict[str, object] = Field(default_factory=dict)


class CapabilityRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concern: str
    capability: Capability
    detail: str


class ProjectSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner: str
    id: str
    number: int
    title: str
    short_description: str = ""
    readme: str = ""
    public: bool = False
    closed: bool = False
    url: str = ""
    repositories: list[str] = Field(default_factory=list)
    fields: list[ProjectFieldSnapshot] = Field(default_factory=list)
    items: list[ProjectItemSnapshot] = Field(default_factory=list)
    capabilities: list[CapabilityRecord] = Field(default_factory=list)

    def normalized_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True) + "\n"


class ProjectIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner: str
    repository: str
    project_id: str
    project_number: int
    field_ids: dict[str, str] = Field(default_factory=dict)
    option_ids: dict[str, dict[str, str]] = Field(default_factory=dict)


def default_project_state_root() -> Path:
    configured = os.environ.get("XDG_STATE_HOME")
    state_home = (
        Path(configured).expanduser() if configured else Path.home() / ".local/state"
    )
    return state_home / "dev-space" / "projects"


class ProjectIdentityStore:
    def __init__(self, root: Path | None = None):
        self.root = (root or default_project_state_root()).resolve()

    def path_for(self, owner: str, repository: str) -> Path:
        if not owner or not repository or "/" in owner or "/" in repository:
            raise ValueError("owner and repository must be simple GitHub names")
        return self.root / owner / f"{repository}.json"

    def load(self, owner: str, repository: str) -> ProjectIdentity | None:
        path = self.path_for(owner, repository)
        if not path.exists():
            return None
        return ProjectIdentity.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, identity: ProjectIdentity) -> Path:
        path = self.path_for(identity.owner, identity.repository)
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            dir=path.parent, prefix=".project-", suffix=".tmp", text=True
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(identity.model_dump_json(indent=2))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return path


_LIST_PROJECTS = """
query DevSpaceProjects($login: String!, $cursor: String) {
  user(login: $login) {
    projectsV2(first: 100, after: $cursor) {
      nodes { id number title shortDescription readme public closed url }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""

_PROJECT_SNAPSHOT = """
query DevSpaceProjectSnapshot($login: String!, $number: Int!, $itemCursor: String) {
  user(login: $login) {
    projectV2(number: $number) {
      id number title shortDescription readme public closed url
      repositories(first: 100) { nodes { nameWithOwner } }
      fields(first: 100) {
        nodes {
          ... on ProjectV2Field { id name dataType }
          ... on ProjectV2SingleSelectField {
            id name dataType
            options { id name description color }
          }
          ... on ProjectV2IterationField { id name dataType }
        }
      }
      items(first: 100, after: $itemCursor) {
        nodes {
          id type isArchived
          content {
            ... on Issue { id number title url repository { nameWithOwner } }
            ... on PullRequest { id number title url repository { nameWithOwner } }
            ... on DraftIssue { id title }
          }
          fieldValues(first: 100) {
            nodes {
              ... on ProjectV2ItemFieldTextValue { text field { ... on ProjectV2FieldCommon { name } } }
              ... on ProjectV2ItemFieldNumberValue { number field { ... on ProjectV2FieldCommon { name } } }
              ... on ProjectV2ItemFieldDateValue { date field { ... on ProjectV2FieldCommon { name } } }
              ... on ProjectV2ItemFieldSingleSelectValue { name optionId field { ... on ProjectV2FieldCommon { name } } }
              ... on ProjectV2ItemFieldIterationValue { title iterationId field { ... on ProjectV2FieldCommon { name } } }
              ... on ProjectV2ItemFieldRepositoryValue { repository { nameWithOwner } field { ... on ProjectV2FieldCommon { name } } }
              ... on ProjectV2ItemFieldMilestoneValue { milestone { title } field { ... on ProjectV2FieldCommon { name } } }
            }
          }
        }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""


class ProjectV2Adapter:
    def __init__(self, client: GitHubClient):
        self.client = client

    def list_projects(self, owner: str) -> list[dict[str, object]]:
        projects: list[dict[str, object]] = []
        cursor: str | None = None
        while True:
            data = self.client.graphql(
                _LIST_PROJECTS, {"login": owner, "cursor": cursor}
            )
            connection = self._connection(data, "projectsV2")
            projects.extend(
                node for node in connection.get("nodes", []) if isinstance(node, dict)
            )
            page_info = connection.get("pageInfo", {})
            if not isinstance(page_info, dict) or not page_info.get("hasNextPage"):
                return projects
            cursor_value = page_info.get("endCursor")
            if not isinstance(cursor_value, str):
                raise GitHubResponseError("projectsV2 pagination is missing endCursor")
            cursor = cursor_value

    def find_projects(self, owner: str, title: str) -> list[dict[str, object]]:
        return [
            project
            for project in self.list_projects(owner)
            if project.get("title") == title
        ]

    def snapshot(self, owner: str, number: int) -> ProjectSnapshot:
        item_nodes: list[dict[str, object]] = []
        project_data: dict[str, object] | None = None
        cursor: str | None = None
        while True:
            data = self.client.graphql(
                _PROJECT_SNAPSHOT,
                {"login": owner, "number": number, "itemCursor": cursor},
            )
            user = data.get("user")
            if not isinstance(user, dict) or not isinstance(
                user.get("projectV2"), dict
            ):
                raise GitHubResponseError(f"Project v2 {owner}/{number} was not found")
            project_data = user["projectV2"]
            items = project_data.get("items")
            if not isinstance(items, dict):
                raise GitHubResponseError("Project v2 response is missing items")
            item_nodes.extend(
                node for node in items.get("nodes", []) if isinstance(node, dict)
            )
            page_info = items.get("pageInfo", {})
            if not isinstance(page_info, dict) or not page_info.get("hasNextPage"):
                break
            cursor_value = page_info.get("endCursor")
            if not isinstance(cursor_value, str):
                raise GitHubResponseError(
                    "Project item pagination is missing endCursor"
                )
            cursor = cursor_value
        assert project_data is not None
        return self._parse_snapshot(owner, project_data, item_nodes)

    def owner_id(self, login: str) -> str:
        data = self.client.graphql(
            "query DevSpaceOwner($login: String!) { user(login: $login) { id } }",
            {"login": login},
        )
        user = data.get("user")
        if not isinstance(user, dict) or not isinstance(user.get("id"), str):
            raise GitHubResponseError(f"GitHub user was not found: {login}")
        return user["id"]

    def repository_id(self, owner: str, name: str) -> str:
        data = self.client.graphql(
            "query DevSpaceRepository($owner: String!, $name: String!) { repository(owner: $owner, name: $name) { id } }",
            {"owner": owner, "name": name},
        )
        repository = data.get("repository")
        if not isinstance(repository, dict) or not isinstance(
            repository.get("id"), str
        ):
            raise GitHubResponseError(
                f"GitHub repository was not found: {owner}/{name}"
            )
        return repository["id"]

    def create_project(self, owner_id: str, title: str) -> tuple[str, int]:
        data = self.client.graphql(
            """
            mutation DevSpaceCreateProject($owner: ID!, $title: String!) {
              createProjectV2(input: {ownerId: $owner, title: $title}) {
                projectV2 { id number }
              }
            }
            """,
            {"owner": owner_id, "title": title},
        )
        payload = data.get("createProjectV2")
        project = payload.get("projectV2") if isinstance(payload, dict) else None
        if not isinstance(project, dict):
            raise GitHubResponseError("createProjectV2 response is missing projectV2")
        project_id, number = project.get("id"), project.get("number")
        if not isinstance(project_id, str) or not isinstance(number, int):
            raise GitHubResponseError("created Project v2 is missing id or number")
        return project_id, number

    def update_project(
        self,
        project_id: str,
        *,
        title: str,
        short_description: str,
        readme: str,
        public: bool,
    ) -> None:
        self.client.graphql(
            """
            mutation DevSpaceUpdateProject($input: UpdateProjectV2Input!) {
              updateProjectV2(input: $input) { projectV2 { id } }
            }
            """,
            {
                "input": {
                    "projectId": project_id,
                    "title": title,
                    "shortDescription": short_description,
                    "readme": readme,
                    "public": public,
                }
            },
        )

    def link_repository(self, project_id: str, repository_id: str) -> None:
        self.client.graphql(
            """
            mutation DevSpaceLinkRepository($project: ID!, $repository: ID!) {
              linkProjectV2ToRepository(input: {projectId: $project, repositoryId: $repository}) {
                repository { id }
              }
            }
            """,
            {"project": project_id, "repository": repository_id},
        )

    def create_field(
        self,
        project_id: str,
        name: str,
        data_type: str,
        options: list[dict[str, str]],
    ) -> str:
        field_input: dict[str, object] = {
            "projectId": project_id,
            "name": name,
            "dataType": data_type,
        }
        if options:
            field_input["singleSelectOptions"] = options
        data = self.client.graphql(
            """
            mutation DevSpaceCreateField($input: CreateProjectV2FieldInput!) {
              createProjectV2Field(input: $input) { projectV2Field { ... on ProjectV2FieldCommon { id } } }
            }
            """,
            {"input": field_input},
        )
        payload = data.get("createProjectV2Field")
        field = payload.get("projectV2Field") if isinstance(payload, dict) else None
        if not isinstance(field, dict) or not isinstance(field.get("id"), str):
            raise GitHubResponseError(
                "createProjectV2Field response is missing field id"
            )
        return field["id"]

    def update_single_select_field(
        self, _project_id: str, field_id: str, name: str, options: list[dict[str, str]]
    ) -> None:
        self.client.graphql(
            """
            mutation DevSpaceUpdateField($input: UpdateProjectV2FieldInput!) {
              updateProjectV2Field(input: $input) { projectV2Field { ... on ProjectV2FieldCommon { id } } }
            }
            """,
            {
                "input": {
                    "fieldId": field_id,
                    "name": name,
                    "singleSelectOptions": options,
                }
            },
        )

    def add_item(self, project_id: str, content_id: str) -> str:
        data = self.client.graphql(
            """
            mutation DevSpaceAddProjectItem($project: ID!, $content: ID!) {
              addProjectV2ItemById(input: {projectId: $project, contentId: $content}) {
                item { id }
              }
            }
            """,
            {"project": project_id, "content": content_id},
        )
        payload = data.get("addProjectV2ItemById")
        item = payload.get("item") if isinstance(payload, dict) else None
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise GitHubResponseError(
                "addProjectV2ItemById response is missing item id"
            )
        return item["id"]

    def update_item_single_select(
        self,
        project_id: str,
        item_id: str,
        field_id: str,
        option_id: str,
    ) -> None:
        self._update_item_field(
            project_id,
            item_id,
            field_id,
            {"singleSelectOptionId": option_id},
        )

    def update_item_text(
        self, project_id: str, item_id: str, field_id: str, text: str
    ) -> None:
        self._update_item_field(project_id, item_id, field_id, {"text": text})

    def _update_item_field(
        self,
        project_id: str,
        item_id: str,
        field_id: str,
        value: dict[str, str],
    ) -> None:
        self.client.graphql(
            """
            mutation DevSpaceUpdateItemField($input: UpdateProjectV2ItemFieldValueInput!) {
              updateProjectV2ItemFieldValue(input: $input) { projectV2Item { id } }
            }
            """,
            {
                "input": {
                    "projectId": project_id,
                    "itemId": item_id,
                    "fieldId": field_id,
                    "value": value,
                }
            },
        )

    @staticmethod
    def _connection(data: dict[str, object], key: str) -> dict[str, object]:
        user = data.get("user")
        connection = user.get(key) if isinstance(user, dict) else None
        if not isinstance(connection, dict):
            raise GitHubResponseError(f"GraphQL response is missing user.{key}")
        return connection

    @staticmethod
    def _parse_snapshot(
        owner: str, raw: dict[str, object], item_nodes: list[dict[str, object]]
    ) -> ProjectSnapshot:
        field_connection = raw.get("fields", {})
        raw_fields = (
            field_connection.get("nodes", [])
            if isinstance(field_connection, dict)
            else []
        )
        fields: list[ProjectFieldSnapshot] = []
        for position, field in enumerate(raw_fields):
            if not isinstance(field, dict):
                continue
            options = [
                ProjectOptionSnapshot(
                    id=str(option.get("id", "")),
                    name=str(option.get("name", "")),
                    description=str(option.get("description", "")),
                    color=str(option.get("color", "GRAY")),
                    position=option_position,
                )
                for option_position, option in enumerate(field.get("options", []))
                if isinstance(option, dict)
            ]
            fields.append(
                ProjectFieldSnapshot(
                    id=str(field.get("id", "")),
                    name=str(field.get("name", "")),
                    data_type=str(field.get("dataType", "UNKNOWN")),
                    position=position,
                    options=options,
                )
            )
        items = [ProjectV2Adapter._parse_item(item) for item in item_nodes]
        repository_connection = raw.get("repositories", {})
        repository_nodes = (
            repository_connection.get("nodes", [])
            if isinstance(repository_connection, dict)
            else []
        )
        repositories = sorted(
            str(node["nameWithOwner"])
            for node in repository_nodes
            if isinstance(node, dict) and isinstance(node.get("nameWithOwner"), str)
        )
        capabilities = [
            CapabilityRecord(
                concern="metadata_fields_items",
                capability=Capability.API_READ_WRITE,
                detail="GraphQL API supports snapshot and reconciliation.",
            ),
            CapabilityRecord(
                concern="views",
                capability=Capability.UI_ONLY,
                detail="Saved view configuration is not exposed with full fidelity.",
            ),
            CapabilityRecord(
                concern="built_in_workflows",
                capability=Capability.UI_ONLY,
                detail="Built-in workflow configuration requires UI verification.",
            ),
        ]
        return ProjectSnapshot(
            owner=owner,
            id=str(raw.get("id", "")),
            number=int(raw.get("number", 0)),
            title=str(raw.get("title", "")),
            short_description=str(raw.get("shortDescription", "")),
            readme=str(raw.get("readme", "")),
            public=bool(raw.get("public", False)),
            closed=bool(raw.get("closed", False)),
            url=str(raw.get("url", "")),
            repositories=repositories,
            fields=fields,
            items=items,
            capabilities=capabilities,
        )

    @staticmethod
    def _parse_item(raw: dict[str, object]) -> ProjectItemSnapshot:
        content = raw.get("content")
        content = content if isinstance(content, dict) else {}
        repository = content.get("repository")
        repository_name = (
            repository.get("nameWithOwner") if isinstance(repository, dict) else None
        )
        values: dict[str, object] = {}
        connection = raw.get("fieldValues")
        nodes = connection.get("nodes", []) if isinstance(connection, dict) else []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            field = node.get("field")
            field_name = field.get("name") if isinstance(field, dict) else None
            if not isinstance(field_name, str):
                continue
            for key in ("text", "number", "date", "name", "title"):
                if key in node and node[key] is not None:
                    values[field_name] = node[key]
                    break
            else:
                repository_value = node.get("repository")
                milestone_value = node.get("milestone")
                if isinstance(repository_value, dict):
                    values[field_name] = repository_value.get("nameWithOwner")
                elif isinstance(milestone_value, dict):
                    values[field_name] = milestone_value.get("title")
        number = content.get("number")
        return ProjectItemSnapshot(
            id=str(raw.get("id", "")),
            type=str(raw.get("type", "")),
            archived=bool(raw.get("isArchived", False)),
            content_id=str(content["id"]) if content.get("id") else None,
            repository=str(repository_name) if repository_name else None,
            number=number if isinstance(number, int) else None,
            title=str(content.get("title", "")),
            url=str(content["url"]) if content.get("url") else None,
            field_values=values,
        )


def snapshot_as_dict(snapshot: ProjectSnapshot) -> dict[str, object]:
    return json.loads(snapshot.normalized_json())
