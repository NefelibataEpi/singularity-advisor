import pytest
from advisor import recommend, Recommendation
from static_data import NODES


def test_generator_recommendation_score():
    # lte_human_g_heart: base_cost=100, base_production=1.0, owned=0
    # next_cost = 100 * 1.15^0 = 100
    # score = 1.0 / 100 = 0.01
    recs = recommend(
        currency=200.0,
        owned={"lte_human_g_heart": 0.0, "lte_human_r_blood": 0.0},
        nodes=NODES,
    )
    heart = next(r for r in recs if r.key == "lte_human_g_heart")
    assert heart.score == pytest.approx(0.01)
    assert heart.cost == pytest.approx(100.0)


def test_generator_cost_scales_with_owned():
    # lte_human_g_heart: base_cost=100, owned=2
    # next_cost = 100 * 1.15^2 = 132.25
    recs = recommend(
        currency=200.0,
        owned={"lte_human_g_heart": 2.0, "lte_human_r_blood": 0.0},
        nodes=NODES,
    )
    heart = next(r for r in recs if r.key == "lte_human_g_heart")
    assert heart.cost == pytest.approx(100.0 * 1.15 ** 2, rel=1e-4)
    assert heart.score == pytest.approx(1.0 / (100.0 * 1.15 ** 2), rel=1e-4)


def test_research_score():
    # lte_human_r_blood_boost: cost=500, target=lte_human_r_blood
    # target base_production=0.6, multiplier=2.0
    # score = 0.6 * (2.0 - 1) / 500 = 0.0012
    recs = recommend(
        currency=600.0,
        owned={"lte_human_g_heart": 0.0, "lte_human_r_blood": 0.0, "lte_human_r_blood_boost": 0.0},
        nodes=NODES,
    )
    boost = next(r for r in recs if r.key == "lte_human_r_blood_boost")
    assert boost.score == pytest.approx(0.0012)


def test_research_excluded_if_already_owned():
    recs = recommend(
        currency=1000.0,
        owned={"lte_human_g_heart": 0.0, "lte_human_r_blood": 0.0, "lte_human_r_blood_boost": 1.0},
        nodes=NODES,
    )
    keys = [r.key for r in recs]
    assert "lte_human_r_blood_boost" not in keys


def test_excluded_if_not_enough_currency():
    recs = recommend(
        currency=50.0,
        owned={"lte_human_g_heart": 0.0, "lte_human_r_blood": 0.0},
        nodes=NODES,
    )
    assert recs == []


def test_sorted_by_score_descending():
    recs = recommend(
        currency=1000.0,
        owned={"lte_human_g_heart": 0.0, "lte_human_r_blood": 0.0, "lte_human_r_blood_boost": 0.0},
        nodes=NODES,
    )
    scores = [r.score for r in recs]
    assert scores == sorted(scores, reverse=True)
