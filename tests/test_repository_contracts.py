from pathlib import Path
import tomllib

import pytest
import yaml
from mutmut.configuration import Config

pytestmark = pytest.mark.no_observability

REPOSITORY_ROOT = Path(__file__).parents[1]


def test_quality_configuration_cannot_be_shallowly_weakened():
    document = tomllib.loads(
        (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    tool = document["tool"]

    assert tool["coverage"]["run"]["branch"] is True
    assert tool["coverage"]["report"]["fail_under"] >= 90
    assert tool["pytest"]["ini_options"]["filterwarnings"] == ["error"]
    assert set(tool["ruff"]["lint"]["select"]) >= {
        "F",
        "E",
        "W",
        "RUF",
        "PGH",
        "BLE",
    }
    assert set(tool["ruff"]["lint"]["ignore"]) <= {"E501", "F841"}
    assert tool["ruff"]["lint"]["per-file-ignores"] == {"tests/*": ["S101"]}


def test_mutation_configuration_loads_and_covers_all_python_source():
    Config.reset()
    config = Config.get()

    assert config.source_paths == [Path("src/dev_space")]
    assert set(config.also_copy) >= {
        Path(".github"),
        Path(".dev-space"),
        Path("README.md"),
        Path("AGENTS.md"),
    }
    assert config.pytest_add_cli_args == [
        "--no-cov",
        "--strict-markers",
        "--capture=sys",
    ]
    assert config.pytest_add_cli_args_test_selection == ["tests/"]
    assert config.mutate_only_covered_lines is False
    assert config.only_mutate == []
    assert config.do_not_mutate == []


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


@pytest.mark.parametrize("workflow_name", ["pr-check.yml", "main-gate.yml"])
def test_python_and_rust_quality_gates_are_enforced(workflow_name):
    workflow = (REPOSITORY_ROOT / ".github" / "workflows" / workflow_name).read_text(
        encoding="utf-8"
    )

    assert "uv run pytest" in workflow
    assert "uv run ruff check" in workflow
    assert "cargo test --locked" in workflow
    assert (
        "cargo clippy --locked --all-targets --all-features -- -D warnings" in workflow
    )
    assert "continue-on-error" not in workflow


def test_pull_request_gate_runs_contract_critical_mutation_tests():
    workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "pr-check.yml").read_text(
        encoding="utf-8"
    )

    assert "mutmut run" in workflow
    assert "dev_space.control_plane.lifecycle.*" in workflow
    assert "dev_space.control_plane.pr_contract.*" in workflow
    assert "dev_space.control_plane.authorization.*" in workflow
    assert "mutmut export-cicd-stats" in workflow
    assert "mutation_score" in workflow
    assert "--policy .dev-space/quality.toml" in workflow
    assert "--target python-repository" in workflow


@pytest.mark.parametrize(
    "workflow_name", ["pr-check.yml", "control-plane-contract.yml"]
)
def test_pull_request_gates_run_when_draft_becomes_ready(workflow_name):
    workflow = (REPOSITORY_ROOT / ".github" / "workflows" / workflow_name).read_text(
        encoding="utf-8"
    )

    assert "ready_for_review" in workflow
