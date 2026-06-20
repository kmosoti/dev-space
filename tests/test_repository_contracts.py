from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.no_observability

REPOSITORY_ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize(
    "workflow_path",
    sorted((REPOSITORY_ROOT / ".github" / "workflows").glob("*.y*ml")),
    ids=lambda path: path.name,
)
def test_github_workflow_yaml_is_valid(workflow_path):
    document = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))

    assert isinstance(document, dict)
    assert isinstance(document.get("name"), str)
    assert isinstance(document.get("jobs"), dict)


@pytest.mark.parametrize(
    "form_path",
    sorted((REPOSITORY_ROOT / ".github" / "ISSUE_TEMPLATE").glob("*.y*ml")),
    ids=lambda path: path.name,
)
def test_github_issue_form_yaml_is_valid(form_path):
    document = yaml.safe_load(form_path.read_text(encoding="utf-8"))

    assert isinstance(document, dict)
    if form_path.name == "config.yml":
        assert isinstance(document.get("blank_issues_enabled"), bool)
    else:
        assert isinstance(document.get("name"), str)
        assert isinstance(document.get("description"), str)
        assert isinstance(document.get("body"), list)
