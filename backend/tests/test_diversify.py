import numpy as np
import pytest

from planner import diversify as dv
from planner import metrics as m


@pytest.fixture
def sample():
    rng = np.random.default_rng(1)
    scores = rng.random(60)
    cats = rng.integers(0, 6, 60)
    return scores, cats


def test_top_k_is_sorted(sample):
    scores, _ = sample
    idx = dv.top_k(scores, 10)
    assert list(scores[idx]) == sorted(scores, reverse=True)[:10]


def test_round_robin_caps_and_covers(sample):
    scores, cats = sample
    idx = dv.round_robin(scores, cats, 12, max_per_cat=2)
    assert len(idx) == len(set(idx)) == 12
    assert set(cats[idx[:6]]) == set(range(6))  # phase 1: one per category
    assert np.bincount(cats[idx]).max() <= 2


def test_round_robin_phase3_relaxes_cap():
    scores = np.linspace(1, 0, 10)
    cats = np.array([0] * 8 + [1] * 2)
    idx = dv.round_robin(scores, cats, 6, max_per_cat=2)
    assert np.bincount(cats[idx]).tolist() == [3, 2]  # cannot fill more without breaking cap + 1


def test_mmr_lambda_one_equals_top_k(sample):
    scores, cats = sample
    sim = dv.category_similarity(cats)
    assert dv.mmr(scores, sim, 12, lam=1.0) == dv.top_k(scores, 12)


def test_mmr_increases_diversity(sample):
    scores, cats = sample
    sim = dv.category_similarity(cats)
    base = m.intra_list_diversity(dv.top_k(scores, 12), sim)
    div = m.intra_list_diversity(dv.mmr(scores, sim, 12, lam=0.5), sim)
    assert div >= base


def test_xquad_lambda_zero_equals_top_k(sample):
    scores, cats = sample
    assert dv.xquad(scores, cats, 12, lam=0.0) == dv.top_k(scores, 12)


def test_xquad_respects_already_selected():
    scores = np.array([0.9, 0.88, 0.5])
    cats = np.array([0, 1, 1])
    assert dv.xquad(scores, cats, 1, lam=0.9)[0] == 0
    assert dv.xquad(scores, cats, 1, lam=0.9, already_selected=[0, 0])[0] == 1


def test_selectors_handle_small_inputs():
    scores, cats = np.array([0.3, 0.9]), np.array([0, 0])
    sim = dv.category_similarity(cats)
    for res in (dv.top_k(scores, 5), dv.round_robin(scores, cats, 5), dv.mmr(scores, sim, 5), dv.xquad(scores, cats, 5)):
        assert sorted(res) == [0, 1]
    assert dv.top_k(np.array([]), 3) == []
    assert dv.round_robin(np.array([]), np.array([]), 3) == []


def test_metrics_basic():
    assert m.recall_at_k([1, 2, 3], {2, 9}, 3) == 0.5
    assert m.precision_at_k([1, 2, 3], {2, 9}, 2) == 0.5
    assert m.ndcg_at_k([5, 6], {5, 6}, 2) == pytest.approx(1.0)
    assert m.reciprocal_rank([4, 7, 9], 7) == 0.5
    assert m.gini([1, 1, 1, 1]) == pytest.approx(0.0)
    assert m.gini([0, 0, 0, 1]) == pytest.approx(0.75)
    assert m.category_entropy([0, 1, 2, 3], 4) == pytest.approx(1.0)
    sim = dv.category_similarity(np.array([0, 0, 1]))
    assert m.intra_list_diversity([0, 1, 2], sim) == pytest.approx(2 / 3)
    assert m.alpha_ndcg_at_k([0, 1, 0], [1, 1, 1], 3) == pytest.approx(1.0)
    assert m.alpha_ndcg_at_k([0, 0, 1], [1, 1, 1], 3) < 1.0
