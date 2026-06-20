from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from dev_space.control_plane.pr_contract import validate_pull_request_contract

pytestmark = pytest.mark.no_observability


BODY = """## Implementation issue

Closes #42

## Scope summary

Implement one bounded slice.

## Acceptance criteria

- [x] The contract passes.

## Verification evidence

```text
uv run pytest: exit 0
```

## Risk and compatibility

Low; compatible.

## Rollback

Revert the commit.

## Scope integrity

- [x] This pull request contains no unrelated work.
"""


def attestation(created_at):
    payload = {
        "actor": "kmosoti",
        "dependencies": {},
        "issue_specification_sha256": "abc",
        "parent": 1,
        "schema_version": 1,
        "timestamp": created_at.isoformat(),
    }
    return {
        "user": {"login": "kmosoti"},
        "body": "<!-- dev-space:readiness-attestation:v1\n"
        + json.dumps(payload)
        + "\n-->",
    }


def issue():
    return {
        "number": 42,
        "labels": [
            {"name": "type:change"},
            {"name": "execution:agent-ready"},
            {"name": "status:in-review"},
        ],
    }


def test_pull_request_contract_accepts_worker_and_prior_planner_attestation():
    first_commit = datetime(2026, 6, 18, 12, tzinfo=UTC)
    result = validate_pull_request_contract(
        body=BODY,
        head_ref="mutation/issue-42-contract",
        author="kz-harbringer",
        issue=issue(),
        comments=[attestation(first_commit - timedelta(minutes=5))],
        first_commit_at=first_commit,
        planner="kmosoti",
        worker="kz-harbringer",
    )

    assert result.valid is True
    assert result.issue_number == 42
    assert result.violations == ()


def test_pull_request_contract_rejects_wrong_actor_branch_and_late_attestation():
    first_commit = datetime(2026, 6, 18, 12, tzinfo=UTC)
    result = validate_pull_request_contract(
        body=BODY.replace("issue", "issue", 1),
        head_ref="mutation/issue-99-contract",
        author="kmosoti",
        issue=issue(),
        comments=[attestation(first_commit + timedelta(minutes=5))],
        first_commit_at=first_commit,
        planner="kmosoti",
        worker="kz-harbringer",
    )

    assert result.valid is False
    assert "branch issue number does not match" in " ".join(result.violations)
    assert "configured worker" in " ".join(result.violations)
    assert "postdates work" in " ".join(result.violations)


def test_pull_request_contract_rejects_missing_sections_and_multiple_links():
    first_commit = datetime(2026, 6, 18, 12, tzinfo=UTC)
    result = validate_pull_request_contract(
        body="Closes #1\nCloses #2",
        head_ref="bad-branch",
        author="kz-harbringer",
        issue=None,
        comments=[],
        first_commit_at=first_commit,
        planner="kmosoti",
        worker="kz-harbringer",
    )

    assert result.valid is False
    assert result.issue_number is None
    assert any("exactly one" in violation for violation in result.violations)
    assert any("missing PR section" in violation for violation in result.violations)
