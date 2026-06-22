from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MutationScore:
    killed: int
    survived: int
    assessed: int
    percentage: float


def calculate_mutation_score(payload: dict[str, object]) -> MutationScore:
    killed = int(payload.get("killed", 0))
    survived = int(payload.get("survived", 0))
    failures = sum(
        int(payload.get(name, 0))
        for name in ("suspicious", "timeout", "segfault", "no_tests")
    )
    assessed = killed + survived + failures
    percentage = 100.0 * killed / assessed if assessed else 0.0
    return MutationScore(killed, survived, assessed, percentage)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--minimum", type=float, default=80.0)
    parser.add_argument(
        "--results",
        type=Path,
        default=Path("mutants/mutmut-cicd-stats.json"),
    )
    arguments = parser.parse_args()
    payload = json.loads(arguments.results.read_text(encoding="utf-8"))
    score = calculate_mutation_score(payload)
    print(
        f"mutation score: {score.percentage:.2f}% "
        f"({score.killed}/{score.assessed} killed)"
    )
    return 0 if score.assessed and score.percentage >= arguments.minimum else 1


if __name__ == "__main__":
    raise SystemExit(main())
