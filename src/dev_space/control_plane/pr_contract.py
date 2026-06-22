from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime


_ISSUE_LINK = re.compile(
    r"(?im)^\s*(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)\s*$"
)
_BRANCH_ISSUE = re.compile(r"(?:^|/)issue-(\d+)(?:-|$)")
_ATTESTATION = re.compile(
    r"<!--\s*dev-space:readiness-attestation:v1\s*(\{.*?\})\s*-->", re.DOTALL
)
_REQUIRED_SECTIONS = (
    "Implementation issue",
    "Scope summary",
    "Acceptance criteria",
    "Verification evidence",
    "Risk and compatibility",
    "Rollback",
    "Scope integrity",
)


@dataclass(frozen=True)
class ContractResult:
    valid: bool
    issue_number: int | None
    violations: tuple[str, ...]


def validate_pull_request_contract(
    *,
    body: str,
    head_ref: str,
    author: str,
    issue: dict[str, object] | None,
    comments: list[dict[str, object]],
    first_commit_at: datetime,
    planner: str,
    worker: str,
) -> ContractResult:
    violations: list[str] = []
    links = [int(value) for value in _ISSUE_LINK.findall(body)]
    unique_links = list(dict.fromkeys(links))
    issue_number = unique_links[0] if len(unique_links) == 1 else None
    if len(unique_links) != 1:
        violations.append("pull request must close exactly one implementation issue")

    branch_match = _BRANCH_ISSUE.search(head_ref)
    branch_issue = int(branch_match.group(1)) if branch_match else None
    if branch_issue is None:
        violations.append("branch name must contain issue-N")
    elif issue_number is not None and branch_issue != issue_number:
        violations.append("branch issue number does not match the linked issue")

    for section in _REQUIRED_SECTIONS:
        match = re.search(rf"(?im)^##\s+{re.escape(section)}\s*$", body)
        if not match:
            violations.append(f"missing PR section: {section}")
    if "- [x]" not in body.casefold():
        violations.append("acceptance or scope-integrity checklist is incomplete")
    evidence = _section(body, "Verification evidence")
    if not evidence or "exit 0" not in evidence:
        violations.append(
            "verification evidence must contain successful command results"
        )

    if issue is None:
        violations.append("linked implementation issue was not found")
    else:
        labels = {
            str(label.get("name"))
            for label in issue.get("labels", [])
            if isinstance(label, dict)
        }
        work_type_labels = labels & {
            "type:change",
            "type:bug",
            "type:maintenance",
        }
        if len(work_type_labels) != 1:
            violations.append(
                "linked issue must have exactly one implementation work type"
            )
        if "execution:agent-ready" in labels and author.casefold() != worker.casefold():
            violations.append(
                "Agent-ready pull request author is not the configured worker"
            )

    if not _valid_attestation(comments, first_commit_at, planner):
        violations.append("planner readiness attestation is missing or postdates work")

    return ContractResult(not violations, issue_number, tuple(violations))


def _valid_attestation(
    comments: list[dict[str, object]], first_commit_at: datetime, planner: str
) -> bool:
    for comment in comments:
        body = comment.get("body")
        user = comment.get("user")
        login = user.get("login") if isinstance(user, dict) else None
        if not isinstance(body, str) or not isinstance(login, str):
            continue
        match = _ATTESTATION.search(body)
        if not match or login.casefold() != planner.casefold():
            continue
        try:
            payload = json.loads(match.group(1))
            timestamp = datetime.fromisoformat(str(payload["timestamp"]))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
        if str(payload.get("actor", "")).casefold() != planner.casefold():
            continue
        if timestamp <= first_commit_at:
            return True
    return False


def _section(body: str, name: str) -> str:
    match = re.search(rf"(?ims)^##\s+{re.escape(name)}\s*$\s*(.*?)(?=^##\s+|\Z)", body)
    return match.group(1).strip() if match else ""
