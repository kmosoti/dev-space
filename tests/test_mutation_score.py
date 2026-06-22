from __future__ import annotations

import pytest

import json
import sys

from dev_space.control_plane.mutation_score import calculate_mutation_score, main

pytestmark = pytest.mark.no_observability


def test_mutation_score_counts_all_non_killed_outcomes_as_failures():
    score = calculate_mutation_score(
        {
            "killed": 80,
            "survived": 10,
            "suspicious": 2,
            "timeout": 3,
            "segfault": 4,
            "no_tests": 1,
        }
    )

    assert score.assessed == 100
    assert score.percentage == 80.0


def test_mutation_score_rejects_empty_results():
    score = calculate_mutation_score({})

    assert score.assessed == 0
    assert score.percentage == 0.0


@pytest.mark.parametrize(("killed", "expected"), [(8, 0), (7, 1)])
def test_mutation_score_cli_enforces_minimum(
    killed, expected, monkeypatch, tmp_path, capsys
):
    results = tmp_path / "results.json"
    results.write_text(
        json.dumps({"killed": killed, "survived": 10 - killed}), encoding="utf-8"
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["mutation-score", "--minimum", "80", "--results", str(results)],
    )

    assert main() == expected
    assert "mutation score:" in capsys.readouterr().out
