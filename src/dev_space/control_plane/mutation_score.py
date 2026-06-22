from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from .quality_policy import (
    QualityPolicyError,
    evaluate_mutation_result,
    load_mutation_evidence,
    load_quality_policy,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, default=Path(".dev-space/quality.toml"))
    parser.add_argument("--target", default="python-repository")
    parser.add_argument(
        "--results",
        type=Path,
        default=Path("mutants/mutmut-cicd-stats.json"),
    )
    parser.add_argument("--as-of", type=date.fromisoformat)
    arguments = parser.parse_args()
    try:
        policy = load_quality_policy(arguments.policy)
        result = load_mutation_evidence(arguments.results, policy, arguments.target)
        if result.target != arguments.target:
            raise QualityPolicyError(
                f"result target {result.target!r} does not match {arguments.target!r}"
            )
        evaluation = evaluate_mutation_result(policy, result, as_of=arguments.as_of)
    except QualityPolicyError as exc:
        print(f"mutation policy rejected result: {exc}")
        return 2
    print(
        f"mutation score: {evaluation.score:.2f}% "
        f"({evaluation.killed}/{evaluation.assessed} killed; "
        f"baseline {evaluation.baseline_score:.2f}%; "
        f"target {evaluation.target_score:.2f}%)"
    )
    for violation in evaluation.violations:
        print(f"violation: {violation}")
    return 0 if evaluation.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
