from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class QualityPolicyError(ValueError):
    """Raised when quality policy or mutation evidence is invalid."""


class MutationTool(StrEnum):
    MUTMUT = "mutmut"
    CARGO_MUTANTS = "cargo-mutants"


class CriticalityTier(StrEnum):
    CRITICAL = "critical"
    STANDARD = "standard"
    SUPPORTING = "supporting"


class MutationOutcome(StrEnum):
    KILLED = "killed"
    SURVIVED = "survived"
    TIMEOUT = "timeout"
    SUSPICIOUS = "suspicious"
    NO_TEST = "no_test"
    RUNTIME_ERROR = "runtime_error"
    UNVIABLE = "unviable"
    SKIPPED = "skipped"
    EQUIVALENT = "equivalent"


class TierPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minimum_score: float = Field(ge=0, le=100)
    target_score: float = Field(ge=0, le=100)

    @model_validator(mode="after")
    def target_is_not_lower_than_minimum(self) -> TierPolicy:
        if self.target_score < self.minimum_score:
            raise ValueError("target_score must be at least minimum_score")
        return self


class ToolOutcomePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    aliases: dict[str, MutationOutcome]
    assessed_outcomes: set[MutationOutcome]
    excluded_outcomes: set[MutationOutcome]

    @model_validator(mode="after")
    def outcomes_are_complete_and_disjoint(self) -> ToolOutcomePolicy:
        overlap = self.assessed_outcomes & self.excluded_outcomes
        if overlap:
            raise ValueError(
                f"outcomes cannot be both assessed and excluded: {overlap}"
            )
        missing = set(MutationOutcome) - (
            self.assessed_outcomes | self.excluded_outcomes
        )
        if missing:
            raise ValueError(f"outcomes require explicit treatment: {missing}")
        if MutationOutcome.KILLED not in self.assessed_outcomes:
            raise ValueError("killed must be an assessed outcome")
        if MutationOutcome.EQUIVALENT not in self.excluded_outcomes:
            raise ValueError("equivalent mutants must be excluded with evidence")
        if not self.aliases:
            raise ValueError("at least one tool outcome alias is required")
        return self


class MutationTargetPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    tool: MutationTool
    tier: CriticalityTier
    baseline_score: float = Field(ge=0, le=100)


class EquivalentMutantExclusion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: str = Field(min_length=1)
    tool: MutationTool
    mutant: str = Field(min_length=1)
    owner: str = Field(min_length=1)
    rationale: str = Field(min_length=10)
    evidence: str = Field(min_length=1)
    expires_on: date


class QualityPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    tiers: dict[CriticalityTier, TierPolicy]
    tools: dict[MutationTool, ToolOutcomePolicy]
    targets: list[MutationTargetPolicy] = Field(min_length=1)
    exclusions: list[EquivalentMutantExclusion] = Field(default_factory=list)

    @model_validator(mode="after")
    def policy_is_complete(self) -> QualityPolicy:
        if set(self.tiers) != set(CriticalityTier):
            raise ValueError(
                "policy must define critical, standard, and supporting tiers"
            )
        if set(self.tools) != set(MutationTool):
            raise ValueError("policy must define mutmut and cargo-mutants outcomes")
        names = [target.name for target in self.targets]
        if len(names) != len(set(names)):
            raise ValueError("mutation target names must be unique")
        target_by_name = {target.name: target for target in self.targets}
        for target in self.targets:
            tier = self.tiers[target.tier]
            if target.baseline_score < tier.minimum_score:
                raise ValueError(
                    f"target {target.name!r} baseline is below its tier minimum"
                )
            if target.baseline_score > tier.target_score:
                raise ValueError(
                    f"target {target.name!r} baseline exceeds its tier target"
                )
        exclusion_keys: set[tuple[str, MutationTool, str]] = set()
        for exclusion in self.exclusions:
            target = target_by_name.get(exclusion.target)
            if target is None:
                raise ValueError(
                    f"exclusion references unknown target {exclusion.target!r}"
                )
            if target.tool != exclusion.tool:
                raise ValueError(
                    f"exclusion tool does not match target {exclusion.target!r}"
                )
            key = (exclusion.target, exclusion.tool, exclusion.mutant)
            if key in exclusion_keys:
                raise ValueError(f"duplicate equivalent-mutant exclusion: {key}")
            exclusion_keys.add(key)
        return self

    def target(self, name: str) -> MutationTargetPolicy:
        for target in self.targets:
            if target.name == name:
                return target
        raise QualityPolicyError(f"unknown mutation target: {name}")


class MutationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    target: str = Field(min_length=1)
    tool: MutationTool
    generated_at: datetime
    outcomes: dict[str, int]
    equivalent_mutants: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def counts_are_non_negative(self) -> MutationResult:
        negative = {name: count for name, count in self.outcomes.items() if count < 0}
        if negative:
            raise ValueError(f"mutation outcome counts cannot be negative: {negative}")
        if len(self.equivalent_mutants) != len(set(self.equivalent_mutants)):
            raise ValueError("equivalent mutant identifiers must be unique")
        return self


@dataclass(frozen=True)
class QualityEvaluation:
    target: str
    tool: MutationTool
    tier: CriticalityTier
    counts: dict[MutationOutcome, int]
    assessed: int
    killed: int
    score: float
    baseline_score: float
    minimum_score: float
    target_score: float
    passed: bool
    violations: tuple[str, ...]


def load_quality_policy(path: Path | str) -> QualityPolicy:
    policy_path = Path(path)
    try:
        payload = tomllib.loads(policy_path.read_text(encoding="utf-8"))
        return QualityPolicy.model_validate(payload)
    except (OSError, tomllib.TOMLDecodeError, ValidationError) as exc:
        raise QualityPolicyError(
            f"invalid quality policy {policy_path}: {exc}"
        ) from exc


def load_mutation_result(path: Path | str) -> MutationResult:
    result_path = Path(path)
    try:
        return MutationResult.model_validate_json(
            result_path.read_text(encoding="utf-8")
        )
    except (OSError, ValidationError) as exc:
        raise QualityPolicyError(
            f"invalid mutation result {result_path}: {exc}"
        ) from exc


def load_mutation_evidence(
    path: Path | str, policy: QualityPolicy, target_name: str
) -> MutationResult:
    """Load canonical evidence or adapt Mutmut's exported flat count object."""
    result_path = Path(path)
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QualityPolicyError(
            f"invalid mutation evidence {result_path}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise QualityPolicyError("mutation evidence must be a JSON object")
    if "schema_version" in payload:
        try:
            return MutationResult.model_validate(payload)
        except ValidationError as exc:
            raise QualityPolicyError(
                f"invalid mutation result {result_path}: {exc}"
            ) from exc

    target = policy.target(target_name)
    if target.tool != MutationTool.MUTMUT:
        raise QualityPolicyError(
            f"raw {target.tool} evidence is unsupported; provide canonical schema v1"
        )
    total = payload.pop("total", None)
    if not isinstance(total, int) or total < 0:
        raise QualityPolicyError("raw Mutmut evidence requires a non-negative total")
    if any(not isinstance(value, int) for value in payload.values()):
        raise QualityPolicyError("raw Mutmut outcome counts must be integers")
    counted = sum(payload.values())
    if counted > total:
        raise QualityPolicyError(
            f"raw Mutmut outcome counts {counted} exceed reported total {total}"
        )
    return MutationResult(
        schema_version=1,
        target=target.name,
        tool=target.tool,
        generated_at=datetime.fromtimestamp(result_path.stat().st_mtime, timezone.utc),
        outcomes=payload,
    )


def evaluate_mutation_result(
    policy: QualityPolicy,
    result: MutationResult,
    *,
    as_of: date | None = None,
) -> QualityEvaluation:
    target = policy.target(result.target)
    if target.tool != result.tool:
        raise QualityPolicyError(
            f"result tool {result.tool} does not match target tool {target.tool}"
        )
    tool_policy = policy.tools[result.tool]
    counts = {outcome: 0 for outcome in MutationOutcome}
    unknown = sorted(set(result.outcomes) - set(tool_policy.aliases))
    if unknown:
        raise QualityPolicyError(f"unknown {result.tool} outcomes: {unknown}")
    for raw_outcome, count in result.outcomes.items():
        counts[tool_policy.aliases[raw_outcome]] += count

    equivalent_count = counts[MutationOutcome.EQUIVALENT]
    if equivalent_count != len(result.equivalent_mutants):
        raise QualityPolicyError(
            "equivalent outcome count must match equivalent_mutants evidence"
        )

    today = as_of or datetime.now(timezone.utc).date()
    applicable = {
        exclusion.mutant: exclusion
        for exclusion in policy.exclusions
        if exclusion.target == target.name and exclusion.tool == target.tool
    }
    expired = sorted(
        mutant
        for mutant, exclusion in applicable.items()
        if exclusion.expires_on < today
    )
    if expired:
        raise QualityPolicyError(f"expired equivalent-mutant exclusions: {expired}")
    uncovered = sorted(set(result.equivalent_mutants) - set(applicable))
    if uncovered:
        raise QualityPolicyError(
            f"equivalent mutants require owner, rationale, evidence, and expiry: {uncovered}"
        )

    assessed = sum(counts[outcome] for outcome in tool_policy.assessed_outcomes)
    if assessed == 0:
        raise QualityPolicyError("mutation result has an empty assessed set")
    killed = counts[MutationOutcome.KILLED]
    score = 100.0 * killed / assessed
    tier = policy.tiers[target.tier]
    violations: list[str] = []
    if score < target.baseline_score:
        violations.append(
            f"score {score:.2f}% regressed below baseline {target.baseline_score:.2f}%"
        )
    if score < tier.minimum_score:
        violations.append(
            f"score {score:.2f}% is below {target.tier} minimum {tier.minimum_score:.2f}%"
        )
    return QualityEvaluation(
        target=target.name,
        tool=target.tool,
        tier=target.tier,
        counts=counts,
        assessed=assessed,
        killed=killed,
        score=score,
        baseline_score=target.baseline_score,
        minimum_score=tier.minimum_score,
        target_score=tier.target_score,
        passed=not violations,
        violations=tuple(violations),
    )
