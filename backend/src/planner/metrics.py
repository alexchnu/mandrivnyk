"""Evaluation metrics for recommendation lists and routes."""

from __future__ import annotations

from collections.abc import Collection, Sequence

import numpy as np


def recall_at_k(ranked: Sequence, relevant: Collection, k: int) -> float:
    if not relevant:
        return 0.0
    return len(set(ranked[:k]) & set(relevant)) / len(set(relevant))


def precision_at_k(ranked: Sequence, relevant: Collection, k: int) -> float:
    if k <= 0:
        return 0.0
    return len(set(ranked[:k]) & set(relevant)) / k


def f1_at_k(ranked: Sequence, relevant: Collection, k: int) -> float:
    p, r = precision_at_k(ranked, relevant, k), recall_at_k(ranked, relevant, k)
    return 0.0 if p + r == 0 else 2 * p * r / (p + r)


def ndcg_at_k(ranked: Sequence, relevant: Collection, k: int) -> float:
    """Binary-gain nDCG."""
    rel = set(relevant)
    if not rel:
        return 0.0
    dcg = sum(1.0 / np.log2(i + 2) for i, item in enumerate(ranked[:k]) if item in rel)
    ideal = sum(1.0 / np.log2(i + 2) for i in range(min(k, len(rel))))
    return dcg / ideal


def reciprocal_rank(ranked: Sequence, target) -> float:
    for i, item in enumerate(ranked):
        if item == target:
            return 1.0 / (i + 1)
    return 0.0


def intra_list_diversity(indices: Sequence[int], similarity: np.ndarray) -> float:
    """ILD: mean pairwise dissimilarity (1 - sim) inside a list."""
    idx = np.asarray(indices, int)
    n = len(idx)
    if n < 2:
        return 0.0
    sub = similarity[np.ix_(idx, idx)]
    return float((1.0 - sub)[np.triu_indices(n, 1)].mean())


def category_coverage(cats: Sequence, n_categories: int) -> float:
    return len(set(cats)) / n_categories if n_categories else 0.0


def category_entropy(cats: Sequence, n_categories: int) -> float:
    """Shannon entropy of the category distribution, normalised to [0, 1]."""
    if not len(cats) or n_categories < 2:
        return 0.0
    _, counts = np.unique(np.asarray(cats), return_counts=True)
    p = counts / counts.sum()
    return float(-(p * np.log(p)).sum() / np.log(n_categories))


def alpha_ndcg_at_k(cats: Sequence, gains: Sequence[float], k: int, alpha: float = 0.5) -> float:
    """alpha-nDCG (Clarke et al., 2008) with categories as information nuggets.

    ``gains`` are graded relevances of the ranked items; repeated categories are
    discounted by ``(1 - alpha) ** seen``. The ideal ranking is built greedily.
    """
    cats, gains = list(cats), list(gains)

    def dcg(order: list[int]) -> float:
        seen: dict = {}
        total = 0.0
        for pos, i in enumerate(order[:k]):
            total += gains[i] * (1 - alpha) ** seen.get(cats[i], 0) / np.log2(pos + 2)
            seen[cats[i]] = seen.get(cats[i], 0) + 1
        return total

    remaining = list(range(len(cats)))
    ideal: list[int] = []
    seen: dict = {}
    while remaining and len(ideal) < k:
        best = max(remaining, key=lambda i: gains[i] * (1 - alpha) ** seen.get(cats[i], 0))
        ideal.append(best)
        remaining.remove(best)
        seen[cats[best]] = seen.get(cats[best], 0) + 1
    denom = dcg(ideal)
    return dcg(list(range(len(cats)))) / denom if denom > 0 else 0.0


def gini(values: Sequence[float]) -> float:
    """Gini coefficient of an exposure distribution (0 = equal, 1 = concentrated)."""
    x = np.sort(np.asarray(values, float))
    n = len(x)
    if n == 0 or x.sum() == 0:
        return 0.0
    return float((2 * np.arange(1, n + 1) - n - 1).dot(x) / (n * x.sum()))


def bootstrap_ci(values: Sequence[float], n_boot: int = 2000, level: float = 0.95, seed: int = 0):
    """Mean with a percentile bootstrap confidence interval."""
    x = np.asarray(values, float)
    if len(x) == 0:
        return float("nan"), float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    means = x[rng.integers(0, len(x), size=(n_boot, len(x)))].mean(axis=1)
    lo, hi = np.quantile(means, [(1 - level) / 2, (1 + level) / 2])
    return float(x.mean()), float(lo), float(hi)
