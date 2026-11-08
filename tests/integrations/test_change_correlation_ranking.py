"""Fixed examples are part of the correlation-v1 ranking contract."""

import pytest

from app.services.change_intelligence.correlation import relevance_score


@pytest.mark.parametrize(
    ("relation", "depth", "gap", "known", "score"),
    [
        ("changed", 0, 0, True, 95),
        ("changed", 0, 7200, True, 91),
        ("changed", 0, 0, False, 94),
        ("reported_affected", 0, 0, True, 85),
        ("dependency", 1, 0, True, 75),
        ("dependency", 2, 3600, True, 68),
        ("dependency", 5, 7200, False, 50),
    ],
)
def test_fixed_ranking_examples(relation, depth, gap, known, score):
    assert relevance_score(relation, depth, gap, known) == score


def test_relation_precedes_time_and_unknown_is_not_a_match():
    assert relevance_score("changed", 0, 7200, False) > relevance_score(
        "reported_affected", 0, 0, True
    )
    assert relevance_score("reported_affected", 0, 7200, False) > relevance_score(
        "dependency", 1, 0, True
    )
    assert relevance_score("changed", 0, 0, True) > relevance_score(
        "changed", 0, 0, False
    )
