"""Selection of a diversified top-k list from scored candidates.

Every selector has the same contract: given per-candidate relevance and
category codes it returns the indices of the chosen candidates in display
order. All selectors are deterministic.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def _order(scores: np.ndarray) -> np.ndarray:
    """Indices by descending score; ties are broken by index for determinism."""
    return np.lexsort((np.arange(len(scores)), -np.asarray(scores, float)))


def minmax(scores: np.ndarray) -> np.ndarray:
    scores = np.asarray(scores, float)
    if scores.size == 0:
        return scores
    lo, hi = scores.min(), scores.max()
    return np.ones_like(scores) if hi - lo < 1e-12 else (scores - lo) / (hi - lo)


def top_k(scores: np.ndarray, k: int) -> list[int]:
    """Baseline without diversification: pure ranking by relevance."""
    return _order(scores)[:k].tolist()


def round_robin(scores: np.ndarray, cats: np.ndarray, k: int, max_per_cat: int = 2) -> list[int]:
    """Three-phase category round-robin (the heuristic from the coursework).

    Phase 1 takes the best item of every category, phase 2 a second item per
    category while the cap allows, phase 3 fills the list by score with the cap
    relaxed by one.
    """
    scores = np.asarray(scores, float)
    cats = np.asarray(cats)
    by_cat: dict[int, list[int]] = {}
    for i in _order(scores):
        by_cat.setdefault(int(cats[i]), []).append(int(i))
    cat_order = sorted(by_cat, key=lambda c: (-scores[by_cat[c][0]], c))

    result: list[int] = []
    picked: set[int] = set()
    count: dict[int, int] = {c: 0 for c in by_cat}

    def take_next(cat: int) -> None:
        for i in by_cat[cat]:
            if i not in picked:
                result.append(i)
                picked.add(i)
                count[cat] += 1
                return

    for cat in cat_order:
        if len(result) >= k:
            return result
        take_next(cat)
    for cat in cat_order:
        if len(result) >= k:
            return result
        if count[cat] < max_per_cat:
            take_next(cat)
    for i in _order(scores):
        if len(result) >= k:
            break
        i = int(i)
        if i not in picked and count[int(cats[i])] < max_per_cat + 1:
            result.append(i)
            picked.add(i)
            count[int(cats[i])] += 1
    return result


def mmr(scores: np.ndarray, similarity: np.ndarray, k: int, lam: float = 0.7) -> list[int]:
    """Maximal Marginal Relevance (Carbonell & Goldstein, 1998).

    ``lam`` = 1 reproduces pure ranking, ``lam`` = 0 maximises novelty only.
    ``similarity`` is an (n, n) matrix with values in [0, 1].
    """
    rel = minmax(scores)
    n = len(rel)
    selected: list[int] = []
    max_sim = np.zeros(n)
    available = np.ones(n, bool)
    for _ in range(min(k, n)):
        value = lam * rel - (1 - lam) * max_sim
        value[~available] = -np.inf
        # argmax over (value, relevance, -index) keeps the choice deterministic
        best = int(np.lexsort((np.arange(n), -rel, -value))[0])
        selected.append(best)
        available[best] = False
        max_sim = np.maximum(max_sim, similarity[best])
    return selected


def xquad(
    scores: np.ndarray,
    cats: np.ndarray,
    k: int,
    lam: float = 0.5,
    aspect_weights: dict[int, float] | None = None,
    already_selected: Sequence[int] = (),
) -> list[int]:
    """Explicit query aspect diversification (Santos et al., 2010).

    Aspects are POI categories. ``aspect_weights`` is P(c | user): uniform by
    default, otherwise the user's category preferences. ``already_selected``
    holds category codes of items the user has already put into the trip, so
    that their aspects count as partly covered (the interactive setting).
    """
    rel = minmax(scores)
    cats = np.asarray(cats)
    n = len(rel)
    present = sorted({int(c) for c in cats})
    if aspect_weights:
        raw = {c: max(float(aspect_weights.get(c, 0.0)), 0.0) for c in present}
    else:
        raw = {c: 1.0 for c in present}
    total = sum(raw.values()) or 1.0
    p_aspect = {c: w / total for c, w in raw.items()}

    # Probability that aspect c is still *not* satisfied by what is selected.
    not_covered = {c: 1.0 for c in present}
    for c in already_selected:
        if int(c) in not_covered:
            not_covered[int(c)] *= 0.5

    selected: list[int] = []
    available = np.ones(n, bool)
    for _ in range(min(k, n)):
        diversity = np.array([p_aspect[int(c)] * not_covered[int(c)] for c in cats]) * rel
        scale = diversity.max()
        if scale > 0:
            diversity = diversity / scale
        value = (1 - lam) * rel + lam * diversity
        value[~available] = -np.inf
        best = int(np.lexsort((np.arange(n), -rel, -value))[0])
        selected.append(best)
        available[best] = False
        not_covered[int(cats[best])] *= 1.0 - rel[best] * 0.999
    return selected


def category_similarity(cats: np.ndarray, subtypes: np.ndarray | None = None) -> np.ndarray:
    """Item similarity for MMR and ILD: 1 same subtype, 0.7 same category, else 0."""
    cats = np.asarray(cats)
    sim = (cats[:, None] == cats[None, :]).astype(float)
    if subtypes is not None:
        subtypes = np.asarray(subtypes)
        same_sub = subtypes[:, None] == subtypes[None, :]
        sim = np.where(same_sub & (sim > 0), 1.0, sim * 0.7)
    np.fill_diagonal(sim, 1.0)
    return sim
