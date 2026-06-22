from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest

from dev_space.control_plane.mutation_score import main
from dev_space.control_plane.quality_policy import (
    MutationOutcome,
    MutationResult,
    QualityPolicy,
    QualityPolicyError,
    evaluate_mutation_result,
    load_mutation_evidence,
    load_mutation_result,
    load_quality_policy,
)

pytestmark = pytest.mark.no_observability

ROOT = Path(__file__).parents[1]
POLICY_PATH = ROOT / ".dev-space" / "quality.toml"
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "quality"


def test_historical_mutmut_fixture_counts_every_unsafe_outcome():
    policy = load_quality_policy(POLICY_PATH)
    result = load_mutation_result(FIXTURE_ROOT / "mutmut-standard-pass.json")

    evaluation = evaluate_mutation_result(policy, result)

    assert evaluation.passed is True
    assert evaluation.assessed == 100
    assert evaluation.score == 80.0
    assert evaluation.counts[MutationOutcome.SKIPPED] == 5
    assert evaluation.counts[MutationOutcome.UNVIABLE] == 7


def test_mutmut_export_is_adapted_to_canonical_evidence():
    policy = load_quality_policy(POLICY_PATH)
    result = load_mutation_evidence(
        FIXTURE_ROOT / "mutmut-export-pass.json", policy, "python-repository"
    )

    evaluation = evaluate_mutation_result(policy, result)

    assert result.schema_version == 1
    assert result.target == "python-repository"
    assert evaluation.assessed == 100
    assert evaluation.counts[MutationOutcome.RUNTIME_ERROR] == 4
    assert evaluation.score == 80.0


@pytest.mark.parametrize(
    ("payload", "target", "message"),
    [
        ("[", "python-repository", "invalid mutation evidence"),
        ("[]", "python-repository", "must be a JSON object"),
        ("{}", "rust-contract-critical", "raw cargo-mutants evidence is unsupported"),
        ("{}", "python-repository", "requires a non-negative total"),
        ('{"total": -1}', "python-repository", "requires a non-negative total"),
        (
            '{"total": 1, "killed": "1"}',
            "python-repository",
            "outcome counts must be integers",
        ),
        (
            '{"total": 1, "killed": 2}',
            "python-repository",
            "outcome counts 2 exceed reported total 1",
        ),
        (
            '{"schema_version": 1}',
            "python-repository",
            "invalid mutation result",
        ),
    ],
)
def test_invalid_tool_evidence_fails_closed(tmp_path, payload, target, message):
    policy = load_quality_policy(POLICY_PATH)
    evidence = tmp_path / "evidence.json"
    evidence.write_text(payload, encoding="utf-8")

    with pytest.raises(QualityPolicyError) as error:
        load_mutation_evidence(evidence, policy, target)

    assert message in str(error.value)


def test_historical_cargo_fixture_excludes_unviable_and_skipped_from_denominator():
    policy = load_quality_policy(POLICY_PATH)
    result = load_mutation_result(FIXTURE_ROOT / "cargo-critical-pass.json")

    evaluation = evaluate_mutation_result(policy, result)

    assert evaluation.passed is True
    assert evaluation.assessed == 100
    assert evaluation.score == 90.0
    assert evaluation.counts[MutationOutcome.UNVIABLE] == 12
    assert evaluation.counts[MutationOutcome.SKIPPED] == 3


def test_historical_regression_fixture_fails_the_ratchet():
    policy = load_quality_policy(POLICY_PATH)
    result = load_mutation_result(FIXTURE_ROOT / "mutmut-standard-regression.json")

    evaluation = evaluate_mutation_result(policy, result)

    assert evaluation.passed is False
    assert evaluation.score == 79.0
    assert evaluation.violations == (
        "score 79.00% regressed below baseline 80.00%",
        "score 79.00% is below standard minimum 80.00%",
    )


def test_unknown_outcome_is_rejected():
    policy = load_quality_policy(POLICY_PATH)
    result = MutationResult.model_validate(
        {
            "schema_version": 1,
            "target": "python-repository",
            "tool": "mutmut",
            "generated_at": "2026-06-22T00:00:00Z",
            "outcomes": {"killed": 1, "pretend_killed": 99},
        }
    )

    with pytest.raises(QualityPolicyError) as error:
        evaluate_mutation_result(policy, result)

    assert str(error.value) == "unknown mutmut outcomes: ['pretend_killed']"


def test_empty_assessed_set_is_rejected():
    policy = load_quality_policy(POLICY_PATH)
    result = MutationResult.model_validate(
        {
            "schema_version": 1,
            "target": "python-repository",
            "tool": "mutmut",
            "generated_at": "2026-06-22T00:00:00Z",
            "outcomes": {"skipped": 4, "unviable": 2, "equivalent": 0},
        }
    )

    with pytest.raises(QualityPolicyError) as error:
        evaluate_mutation_result(policy, result)

    assert str(error.value) == "mutation result has an empty assessed set"


def test_expired_equivalent_exclusion_is_rejected():
    policy_data = load_quality_policy(POLICY_PATH).model_dump(mode="json")
    policy_data["exclusions"] = [
        {
            "target": "python-repository",
            "tool": "mutmut",
            "mutant": "dev_space.lifecycle:42",
            "owner": "kmosoti",
            "rationale": "The replacement is semantically identical for this domain.",
            "evidence": "tests/fixtures/quality/equivalent-42.md",
            "expires_on": "2026-06-01",
        }
    ]
    policy = QualityPolicy.model_validate(policy_data)
    result = MutationResult.model_validate(
        {
            "schema_version": 1,
            "target": "python-repository",
            "tool": "mutmut",
            "generated_at": "2026-06-22T00:00:00Z",
            "outcomes": {"killed": 10, "equivalent": 1},
            "equivalent_mutants": ["dev_space.lifecycle:42"],
        }
    )

    with pytest.raises(QualityPolicyError) as error:
        evaluate_mutation_result(policy, result, as_of=date(2026, 6, 22))

    assert "expired equivalent-mutant exclusion" in str(error.value)
    assert "dev_space.lifecycle:42" in str(error.value)


def test_equivalent_mutant_requires_matching_policy_evidence():
    policy = load_quality_policy(POLICY_PATH)
    result = MutationResult.model_validate(
        {
            "schema_version": 1,
            "target": "python-repository",
            "tool": "mutmut",
            "generated_at": "2026-06-22T00:00:00Z",
            "outcomes": {"killed": 10, "equivalent": 1},
            "equivalent_mutants": ["dev_space.lifecycle:42"],
        }
    )

    with pytest.raises(QualityPolicyError) as error:
        evaluate_mutation_result(policy, result, as_of=date(2026, 6, 22))

    assert "require owner, rationale, evidence, and expiry" in str(error.value)
    assert "dev_space.lifecycle:42" in str(error.value)


def test_result_tool_must_match_the_named_target():
    policy = load_quality_policy(POLICY_PATH)
    result = MutationResult.model_validate(
        {
            "schema_version": 1,
            "target": "python-repository",
            "tool": "cargo-mutants",
            "generated_at": "2026-06-22T00:00:00Z",
            "outcomes": {"caught": 10},
        }
    )

    with pytest.raises(QualityPolicyError) as error:
        evaluate_mutation_result(policy, result)

    assert str(error.value) == (
        "result tool cargo-mutants does not match target tool mutmut"
    )


def test_policy_schema_forbids_unknown_fields():
    policy_data = load_quality_policy(POLICY_PATH).model_dump(mode="json")
    policy_data["minimum"] = 1

    with pytest.raises(ValueError) as error:
        QualityPolicy.model_validate(policy_data)

    assert "Extra inputs are not permitted" in str(error.value)


@pytest.mark.parametrize(
    ("fixture", "expected"),
    [("mutmut-standard-pass.json", 0), ("mutmut-standard-regression.json", 1)],
)
def test_mutation_score_cli_uses_versioned_policy(
    fixture, expected, monkeypatch, capsys
):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mutation-score",
            "--policy",
            str(POLICY_PATH),
            "--target",
            "python-repository",
            "--results",
            str(FIXTURE_ROOT / fixture),
        ],
    )

    assert main() == expected
    assert "mutation score:" in capsys.readouterr().out


def test_mutation_score_cli_fails_closed_on_invalid_evidence(
    tmp_path, monkeypatch, capsys
):
    invalid_result = tmp_path / "invalid-result.json"
    invalid_result.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mutation-score",
            "--policy",
            str(POLICY_PATH),
            "--target",
            "python-repository",
            "--results",
            str(invalid_result),
        ],
    )

    assert main() == 2
    assert "mutation policy rejected result:" in capsys.readouterr().out


def test_policy_and_result_schemas_are_machine_readable():
    policy_schema = QualityPolicy.model_json_schema()
    result_schema = MutationResult.model_json_schema()

    assert policy_schema["additionalProperties"] is False
    assert set(policy_schema["required"]) == {
        "schema_version",
        "tiers",
        "tools",
        "targets",
    }
    assert result_schema["additionalProperties"] is False
    assert set(result_schema["required"]) == {
        "schema_version",
        "target",
        "tool",
        "generated_at",
        "outcomes",
    }
    assert json.dumps(
        {"policy": policy_schema, "result": result_schema}, sort_keys=True
    )
