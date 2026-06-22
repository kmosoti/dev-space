from __future__ import annotations

import hashlib
import json
import re

from pydantic import ValidationError

from .models import ChangeSpecification, ExecutionMode, ReadinessResult, Risk


class SpecificationError(ValueError):
    """A Markdown change specification is missing or invalid."""


_HEADING = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_DEPENDENCY = re.compile(r"#?(\d+)")


def parse_change_specification(markdown: str, parent: int) -> ChangeSpecification:
    title_match = re.search(r"^#\s+(.+?)\s*$", markdown, re.MULTILINE)
    if not title_match:
        raise SpecificationError("change specification requires a level-one title")
    sections = _sections(markdown)
    required = {
        "problem",
        "current behavior",
        "required behavior",
        "scope",
        "non-goals",
        "design",
        "affected components",
        "security",
        "compatibility",
        "tests",
        "rollout",
        "rollback",
        "dependencies",
        "acceptance criteria",
        "unresolved decisions",
        "execution",
        "risk",
    }
    missing = sorted(required - sections.keys())
    if missing:
        raise SpecificationError(
            f"missing specification sections: {', '.join(missing)}"
        )
    try:
        return ChangeSpecification(
            title=title_match.group(1).strip(),
            parent=parent,
            problem=sections["problem"],
            current_behavior=sections["current behavior"],
            required_behavior=sections["required behavior"],
            scope=_list(sections["scope"]),
            non_goals=_list(sections["non-goals"]),
            design=sections["design"],
            affected_components=_list(sections["affected components"]),
            security=sections["security"],
            compatibility=sections["compatibility"],
            tests=_list(sections["tests"]),
            rollout=sections["rollout"],
            rollback=sections["rollback"],
            dependencies=_dependencies(sections["dependencies"]),
            acceptance_criteria=_list(sections["acceptance criteria"]),
            unresolved_decisions=_optional_list(sections["unresolved decisions"]),
            execution=ExecutionMode(sections["execution"].strip()),
            risk=Risk(sections["risk"].strip()),
        )
    except (ValidationError, ValueError) as exc:
        raise SpecificationError(f"invalid change specification: {exc}") from exc


def render_change_specification(specification: ChangeSpecification) -> str:
    def bullets(values: list[str], *, checkboxes: bool = False) -> str:
        prefix = "- [ ] " if checkboxes else "- "
        return "\n".join(f"{prefix}{value}" for value in values) or "None"

    dependencies = (
        "\n".join(f"- #{number}" for number in specification.dependencies) or "None"
    )
    return f"""# {specification.title}

## Parent Epic

#{specification.parent}

## Problem

{specification.problem}

## Current Behavior

{specification.current_behavior}

## Required Behavior

{specification.required_behavior}

## Scope

{bullets(specification.scope)}

## Non-goals

{bullets(specification.non_goals)}

## Design

{specification.design}

## Affected Components

{bullets(specification.affected_components)}

## Security

{specification.security}

## Compatibility

{specification.compatibility}

## Tests

{bullets(specification.tests)}

## Rollout

{specification.rollout}

## Rollback

{specification.rollback}

## Dependencies

{dependencies}

## Acceptance Criteria

{bullets(specification.acceptance_criteria, checkboxes=True)}

## Unresolved Decisions

{bullets(specification.unresolved_decisions)}

## Execution

{specification.execution}

## Risk

{specification.risk}
"""


def specification_hash(specification: ChangeSpecification) -> str:
    canonical = json.dumps(
        specification.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def evaluate_readiness(
    specification: ChangeSpecification, *, dependencies_complete: bool
) -> ReadinessResult:
    violations: list[str] = []
    if specification.unresolved_decisions:
        violations.append("unresolved decisions remain")
    if not dependencies_complete:
        violations.append("dependencies are incomplete")
    if specification.risk == Risk.HIGH:
        violations.append("high-risk work cannot be agent-ready")
    if specification.execution != ExecutionMode.AGENT_READY:
        violations.append("execution mode is not Agent-ready")
    return ReadinessResult(ready=not violations, violations=violations)


def readiness_attestation(
    specification: ChangeSpecification,
    *,
    actor: str,
    dependency_states: dict[int, str],
    timestamp: str,
) -> str:
    payload = {
        "actor": actor,
        "dependencies": {str(key): value for key, value in dependency_states.items()},
        "issue_specification_sha256": specification_hash(specification),
        "parent": specification.parent,
        "schema_version": 1,
        "timestamp": timestamp,
    }
    return (
        "<!-- dev-space:readiness-attestation:v1\n"
        + json.dumps(payload, indent=2, sort_keys=True)
        + "\n-->\n\nPlanner-authorized readiness attestation."
    )


def _sections(markdown: str) -> dict[str, str]:
    matches = list(_HEADING.finditer(markdown))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        sections[match.group(1).strip().casefold()] = markdown[start:end].strip()
    return sections


def _list(value: str) -> list[str]:
    items = [
        re.sub(r"^-\s+(?:\[[ xX]\]\s+)?", "", line).strip()
        for line in value.splitlines()
        if re.match(r"^-\s+", line.strip())
    ]
    if not items:
        raise SpecificationError("expected a non-empty Markdown list")
    return items


def _optional_list(value: str) -> list[str]:
    if value.strip().casefold() in {"", "none", "n/a", "not applicable"}:
        return []
    return _list(value)


def _dependencies(value: str) -> list[int]:
    if value.strip().casefold() in {"", "none", "n/a"}:
        return []
    dependencies = [int(match.group(1)) for match in _DEPENDENCY.finditer(value)]
    if not dependencies:
        raise SpecificationError("dependencies must be issue numbers or None")
    return list(dict.fromkeys(dependencies))
