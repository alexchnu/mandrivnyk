"""Figures for the thesis, drawn from the CSV results of experiments E1-E4.

Run: ``uv run python -m planner.experiments.figures``
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker
import numpy as np
import pandas as pd

from ..data.flickr import MAIN_CITIES
from ..data.paths import RESULTS_DIR

FIG_DIR = RESULTS_DIR.parent / "figures"
# Categorical palette validated for colour-vision deficiencies (dataviz reference palette);
# every series also differs by marker or hatch because the thesis is printed.
BLUE, ORANGE, AQUA, YELLOW, MAGENTA, VIOLET = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#6250d6"
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#dddcd6"
SEQ = ["#b7d3f6", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"]

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": MUTED, "axes.labelcolor": INK,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.color": GRID,
    "grid.linewidth": 0.6, "axes.axisbelow": True, "xtick.color": MUTED, "ytick.color": MUTED,
    "legend.frameon": False, "figure.dpi": 100, "savefig.dpi": 300, "savefig.bbox": "tight",
    "axes.titlesize": 10, "axes.titleweight": "bold", "axes.titlelocation": "left",
})  # fmt: skip

SCORER_NAME = {
    "manual": "Ручні ваги (курсова)", "n_tags": "Кількість тегів", "sitelinks": "Sitelinks Wikidata",
    "pageviews": "Перегляди Wikipedia", "lgbm:osm": "Модель: OSM", "logreg:osm": "Лог. регресія: OSM",
    "lgbm:osm+sitelinks": "Модель: OSM + sitelinks", "lgbm:osm+wiki": "Модель: OSM + sitelinks + перегляди",
    "logreg:osm+wiki": "Лог. регресія: OSM + Wiki",
}  # fmt: skip
SELECTOR_NAME = {
    "top_k": "Без диверсифікації",
    "round_robin": "Round-robin (курсова)",
    "mmr": "MMR",
    "xquad": "xQuAD",
}


def _comma(value: float, _pos=None) -> str:
    return f"{value:g}".replace(".", ",")


def _save(fig, name: str) -> None:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    for ax in fig.axes:  # Ukrainian typography: decimal comma on numeric axes
        for axis in (ax.xaxis, ax.yaxis):
            if not isinstance(axis.get_major_formatter(), matplotlib.ticker.FixedFormatter):
                axis.set_major_formatter(matplotlib.ticker.FuncFormatter(_comma))
    fig.savefig(FIG_DIR / f"{name}.png")
    plt.close(fig)
    print("saved", name)


def _num(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def fig_e1() -> None:
    df = pd.read_csv(RESULTS_DIR / "e1_spearman.csv")
    pooled = df[df.city == "all"].set_index("signal").loc[["manual", "n_tags", "sitelinks", "pageviews"]]
    fig, ax = plt.subplots(figsize=(6.2, 2.9))
    y = np.arange(len(pooled))[::-1]
    err = [pooled.rho - pooled.ci_lo, pooled.ci_hi - pooled.rho]
    ax.barh(
        y,
        pooled.rho,
        height=0.55,
        color=BLUE,
        xerr=err,
        error_kw={"ecolor": INK, "elinewidth": 1, "capsize": 3},
    )
    ax.set_yticks(y, [SCORER_NAME[s] for s in pooled.index])
    for yi, (rho, hi) in zip(y, zip(pooled.rho, pooled.ci_hi, strict=True), strict=True):
        ax.text(hi + 0.012, yi, _num(rho), va="center", color=INK)
    ax.set_xlim(0, 0.62)
    ax.set_xlabel("Коефіцієнт рангової кореляції Спірмена ρ з кількістю відвідувачів (Flickr)")
    ax.grid(axis="y", visible=False)
    _save(fig, "e1_spearman")

    by_city = df[df.city.isin(MAIN_CITIES)].pivot(index="city", columns="signal", values="rho")
    fig, ax = plt.subplots(figsize=(6.2, 3.2))
    x = np.arange(len(by_city))
    for k, (sig, color, hatch) in enumerate(
        [("manual", ORANGE, "//"), ("sitelinks", BLUE, ""), ("pageviews", AQUA, "..")]
    ):
        ax.bar(
            x + (k - 1) * 0.27,
            by_city[sig],
            width=0.25,
            color=color,
            hatch=hatch,
            edgecolor="white",
            linewidth=0.5,
            label=SCORER_NAME[sig],
        )
    ax.axhline(0, color=MUTED, linewidth=0.8)
    ax.set_xticks(x, [c.capitalize() for c in by_city.index], rotation=20)
    ax.set_ylabel("ρ Спірмена")
    ax.grid(axis="x", visible=False)
    ax.legend(ncol=3, loc="upper center", bbox_to_anchor=(0.5, 1.16), fontsize=8)
    _save(fig, "e1_by_city")


def fig_e2() -> None:
    roc = pd.read_csv(RESULTS_DIR / "e2_roc.csv")
    metrics = pd.read_csv(RESULTS_DIR / "e2_metrics.csv")
    macro = metrics[metrics.city == "macro"].set_index("method")
    series = [
        ("manual", ORANGE, "--"),
        ("sitelinks", YELLOW, "-."),
        ("lgbm:osm", AQUA, "-"),
        ("lgbm:osm+sitelinks", BLUE, "-"),
    ]
    fig, axes = plt.subplots(1, 2, figsize=(7.4, 3.5))
    for ax, xmax in zip(axes, (1.0, 0.1), strict=True):
        for name, color, style in series:
            cur = roc[roc.method == name]
            ax.plot(
                cur.fpr,
                cur.tpr,
                color=color,
                linestyle=style,
                linewidth=2,
                label=f"{SCORER_NAME[name]} (AUC {_num(macro.loc[name, 'roc_auc'], 3)})",
            )
        ax.plot([0, 1], [0, 1], color=GRID, linewidth=1)
        ax.set_xlim(0, xmax)
        ax.set_ylim(0, 1.01)
        ax.set_xlabel("Частка хибно позитивних (FPR)")
    axes[0].set_ylabel("Частка істинно позитивних (TPR)")
    axes[0].set_title("а) повна крива")
    axes[1].set_title("б) область малих FPR")
    axes[0].legend(loc="lower right", fontsize=8)
    _save(fig, "e2_roc")

    order = [
        "manual",
        "n_tags",
        "sitelinks",
        "pageviews",
        "logreg:osm",
        "lgbm:osm",
        "lgbm:osm+sitelinks",
        "lgbm:osm+wiki",
    ]
    fig, ax = plt.subplots(figsize=(6.4, 3.4))
    y = np.arange(len(order))[::-1]
    values = macro.loc[order, "pr_auc"]
    colors = [ORANGE if m == "manual" else BLUE if m.startswith(("lgbm", "logreg")) else MUTED for m in order]
    ax.barh(y, values, height=0.6, color=colors)
    for yi, v in zip(y, values, strict=True):
        ax.text(v + 0.006, yi, _num(v, 3), va="center", color=INK)
    ax.set_yticks(y, [SCORER_NAME[m] for m in order])
    ax.set_xlim(0, values.max() * 1.18)
    ax.set_xlabel("PR-AUC (середнє за 8 містами, місто-тест не бачене моделлю)")
    ax.grid(axis="y", visible=False)
    _save(fig, "e2_pr_auc")

    cm = pd.read_csv(RESULTS_DIR / "e2_confusion.csv").set_index("method")
    fig, axes = plt.subplots(1, 3, figsize=(7.6, 2.7))
    for ax, name in zip(axes, ["manual", "lgbm:osm", "lgbm:osm+sitelinks"], strict=True):
        row = cm.loc[name]
        grid = np.array([[row.tn, row.fp], [row.fn, row.tp]])
        share = grid / grid.sum(axis=1, keepdims=True)
        ax.imshow(share, cmap="Blues", vmin=0, vmax=1)
        for (i, j), v in np.ndenumerate(grid):
            ax.text(
                j,
                i,
                f"{int(v):,}".replace(",", " "),
                ha="center",
                va="center",
                color="white" if share[i, j] > 0.55 else INK,
                fontsize=11,
                fontweight="bold",
            )
        ax.set_xticks([0, 1], ["не значуще", "значуще"])
        ax.set_yticks(
            [0, 1], ["не значуще", "значуще"] if ax is axes[0] else ["", ""], rotation=90, va="center"
        )
        ax.set_xlabel("Передбачено")
        ax.set_title(f"{SCORER_NAME[name]}\nF1 = {_num(row.f1)}", fontsize=9)
        ax.grid(False)
        ax.tick_params(length=0)
    axes[0].set_ylabel("Фактично")
    _save(fig, "e2_confusion")

    lc = pd.read_csv(RESULTS_DIR / "e2_learning_curve.csv")
    fig, ax = plt.subplots(figsize=(6.0, 3.2))
    for name, color, marker in [("lgbm:osm+sitelinks", BLUE, "o"), ("lgbm:osm", AQUA, "s")]:
        cur = lc[lc.model == name].groupby("n_train_cities")
        mean, sd = cur.test_auc.mean(), cur.test_auc.std()
        ax.plot(
            mean.index,
            mean,
            color=color,
            marker=marker,
            markersize=6,
            linewidth=2,
            label=f"{SCORER_NAME[name]}: тест",
        )
        ax.fill_between(mean.index, mean - sd, mean + sd, color=color, alpha=0.15, linewidth=0)
        train = cur.train_auc.mean()
        ax.plot(
            train.index,
            train,
            color=color,
            linestyle=":",
            linewidth=1.5,
            label=f"{SCORER_NAME[name]}: навчання",
        )
    ax.set_xlabel("Кількість міст у навчальній вибірці")
    ax.set_ylabel("ROC-AUC")
    ax.set_ylim(0.86, 1.005)
    ax.legend(fontsize=8, loc="lower right")
    _save(fig, "e2_learning_curve")

    imp = pd.read_csv(RESULTS_DIR / "e2_importance.csv").head(12).iloc[::-1]
    labels = {
        "has_wikipedia": "Є тег wikipedia", "has_wikidata": "Є тег wikidata", "dist_centre_km": "Відстань до центру",
        "notable_500m": "Відомі об'єкти в радіусі 500 м", "n_tags_log": "Кількість тегів (log)",
        "density_300m": "Щільність POI в радіусі 300 м", "food_200m": "Заклади харчування в радіусі 200 м",
        "is_attraction": "tourism=attraction", "has_name_en": "Є назва англійською", "is_relation": "Об'єкт-відношення",
        "has_image": "Є зображення", "has_website": "Є сайт", "is_way": "Об'єкт-лінія/полігон", "is_node": "Об'єкт-точка",
        "has_heritage": "Статус спадщини", "has_opening_hours": "Є години роботи", "has_start_date": "Є дата заснування",
    }  # fmt: skip
    fig, ax = plt.subplots(figsize=(6.2, 3.6))
    ax.barh(
        [labels.get(f, f.replace("cat_", "Категорія: ")) for f in imp.feature],
        imp.lgbm_gain,
        height=0.6,
        color=BLUE,
    )
    ax.set_xlabel("Частка сумарного приросту (gain) у моделі LightGBM на ознаках OSM")
    ax.grid(axis="y", visible=False)
    _save(fig, "e2_importance")


def fig_e3() -> None:
    summary = pd.read_csv(RESULTS_DIR / "e3_explore_summary.csv")
    sens = pd.read_csv(RESULTS_DIR / "e3_sensitivity.csv").set_index("config")
    scorers = [("manual", ORANGE), ("sitelinks", YELLOW), ("lgbm:osm", AQUA), ("lgbm:osm+sitelinks", BLUE)]
    markers = {"top_k": "o", "round_robin": "s", "mmr": "^", "xquad": "D"}
    fig, ax = plt.subplots(figsize=(6.6, 4.2))
    for scorer, color in scorers:
        for selector, marker in markers.items():
            row = summary[(summary.scorer == scorer) & (summary.selector == selector)].iloc[0]
            ax.scatter(
                row.ild, row.ndcg, s=70, color=color, marker=marker, edgecolor="white", linewidth=1, zorder=3
            )
    best = sens.loc["lgbm:osm+sitelinks|w=0.15|lam=0.25"]
    ax.scatter(best.ild, best.ndcg, s=260, marker="*", color=BLUE, edgecolor=INK, linewidth=1, zorder=4)
    ax.annotate(
        "Обрана конфігурація\n(w = 0,15; λ = 0,25)",
        (best.ild, best.ndcg),
        xytext=(-70, -4),
        textcoords="offset points",
        ha="right",
        va="center",
        color=INK,
        fontsize=9,
        arrowprops={"arrowstyle": "-", "color": MUTED, "linewidth": 0.8},
    )
    old = summary[summary.config == "manual|round_robin"].iloc[0]
    ax.annotate(
        "Алгоритм курсової",
        (old.ild, old.ndcg),
        xytext=(-60, 22),
        textcoords="offset points",
        ha="right",
        color=INK,
        fontsize=9,
        arrowprops={"arrowstyle": "-", "color": MUTED, "linewidth": 0.8},
    )
    handles = [
        plt.Line2D([], [], marker="o", linestyle="", color=c, markersize=8, label=SCORER_NAME[s])
        for s, c in scorers
    ]
    handles += [
        plt.Line2D([], [], marker=m, linestyle="", color=MUTED, markersize=7, label=SELECTOR_NAME[s])
        for s, m in markers.items()
    ]
    ax.legend(handles=handles, fontsize=8, ncol=2, loc="upper center", bbox_to_anchor=(0.5, -0.16))
    ax.set_ylim(top=best.ndcg + 0.012)
    ax.set_xlabel("Різноманіття списку (ILD@12)")
    ax.set_ylabel("Якість ранжування (nDCG@12)")
    _save(fig, "e3_tradeoff")

    fig, axes = plt.subplots(1, 2, figsize=(7.4, 3.2), sharex=True)
    lams = [0.0, 0.25, 0.5, 0.75, 1.0]
    for w, color, marker in zip([0.0, 0.15, 0.33, 0.5, 0.7], SEQ, "ovs^D", strict=True):
        rows = [sens.loc[f"lgbm:osm+sitelinks|w={w:.2f}|lam={lam:.2f}"] for lam in lams]
        for ax, metric in zip(axes, ("ndcg", "ild"), strict=True):
            ax.plot(
                lams,
                [r[metric] for r in rows],
                color=color,
                marker=marker,
                markersize=5,
                linewidth=2,
                label=f"w = {_num(w)}",
            )
    axes[0].set_ylabel("nDCG@12")
    axes[1].set_ylabel("ILD@12")
    for ax in axes:
        ax.set_xlabel("Сила диверсифікації λ (xQuAD)")
    axes[0].set_title("а) якість")
    axes[1].set_title("б) різноманіття")
    axes[1].legend(title="Вага відстані", fontsize=8, title_fontsize=8, loc="lower right")
    _save(fig, "e3_sensitivity")

    inter = pd.read_csv(RESULTS_DIR / "e3_interactive_summary.csv").set_index("config")
    rows = [
        ("distance_only", "Лише відстань", MUTED), ("manual|round_robin", "Алгоритм курсової", ORANGE),
        ("lgbm:osm|top_k", "Модель: OSM", AQUA), ("lgbm:osm+sitelinks|round_robin", "Модель + round-robin", BLUE),
        ("proposed", "Обрана конфігурація", BLUE), ("lgbm:osm+sitelinks|top_k|w=0.15", "Модель без диверсифікації", BLUE),
    ]  # fmt: skip
    fig, ax = plt.subplots(figsize=(6.2, 3.0))
    y = np.arange(len(rows))[::-1]
    vals = np.array([inter.loc[k, "hit"] for k, _, _ in rows])
    lo = np.array([inter.loc[k, "hit_lo"] for k, _, _ in rows])
    hi = np.array([inter.loc[k, "hit_hi"] for k, _, _ in rows])
    ax.barh(
        y,
        vals,
        height=0.6,
        color=[c for _, _, c in rows],
        xerr=[vals - lo, hi - vals],
        error_kw={"ecolor": INK, "elinewidth": 1, "capsize": 3},
    )
    for yi, v, h in zip(y, vals, hi, strict=True):
        ax.text(h + 0.008, yi, _num(v, 3), va="center", color=INK)
    ax.set_yticks(y, [name for _, name, _ in rows])
    ax.set_xlim(0, vals.max() * 1.2)
    ax.set_xlabel("Частка кроків, де наступна реальна зупинка є серед 8 пропозицій (hit@8)")
    ax.grid(axis="y", visible=False)
    _save(fig, "e3_interactive")

    abl = pd.read_csv(RESULTS_DIR / "e3_ablation.csv").set_index("config")
    jitter = abl[abl.index.str.startswith("jitter")]
    rows = [("full", "Повний алгоритм"), ("no_diversification", "Без диверсифікації"), ("no_distance", "Без відстані"),
            ("no_popularity", "Без популярності")]  # fmt: skip
    names = [n for _, n in rows] + ["З випадковим джитером"]
    ndcg = [abl.loc[k, "ndcg"] for k, _ in rows] + [jitter.ndcg.mean()]
    ild = [abl.loc[k, "ild"] for k, _ in rows] + [jitter.ild.mean()]
    fig, axes = plt.subplots(1, 2, figsize=(7.4, 2.8), sharey=True)
    y = np.arange(len(names))[::-1]
    for ax, vals, label in zip(axes, (ndcg, ild), ("nDCG@12", "ILD@12"), strict=True):
        ax.barh(y, vals, height=0.6, color=[ORANGE] + [MUTED] * 4)
        for yi, v in zip(y, vals, strict=True):
            ax.text(v + max(vals) * 0.015, yi, _num(v, 3), va="center", color=INK)
        ax.set_xlim(0, max(vals) * 1.2)
        ax.set_xlabel(label)
        ax.grid(axis="y", visible=False)
    axes[0].set_yticks(y, names)
    _save(fig, "e3_ablation")


def fig_e4() -> None:
    summary = pd.read_csv(RESULTS_DIR / "e4_ordering_summary.csv")
    pooled = summary[summary.city == "all"].set_index("method")
    rows = [("random", "Випадковий порядок", MUTED), ("user", "Порядок туриста", ORANGE), ("nearest", "Найближчий сусід", AQUA),
            ("nearest_2opt", "Найближчий сусід + 2-opt", AQUA), ("ortools", "OR-Tools", BLUE), ("exact", "Точний розв'язок", BLUE)]  # fmt: skip
    fig, ax = plt.subplots(figsize=(6.2, 3.0))
    y = np.arange(len(rows))[::-1]
    vals = np.array([(pooled.loc[k, "ratio_to_best"] - 1) * 100 for k, _, _ in rows])
    ax.barh(y, vals, height=0.6, color=[c for _, _, c in rows])
    for yi, v in zip(y, vals, strict=True):
        ax.text(v + 0.8, yi, f"+{_num(v, 1)} %" if v > 0.05 else "0", va="center", color=INK)
    ax.set_yticks(y, [n for _, n, _ in rows])
    ax.set_xlim(0, vals.max() * 1.18)
    ax.set_xlabel("Перевищення часу ходьби над оптимальним порядком, %")
    ax.grid(axis="y", visible=False)
    _save(fig, "e4_ratio")

    by_n = pd.read_csv(RESULTS_DIR / "e4_ordering_by_size.csv")
    by_n = by_n[by_n.routes >= 10]
    fig, ax = plt.subplots(figsize=(6.0, 3.1))
    ax.plot(by_n.n, by_n.user, color=ORANGE, marker="s", markersize=6, linewidth=2, label="Порядок туриста")
    ax.plot(
        by_n.n, by_n.exact, color=BLUE, marker="o", markersize=6, linewidth=2, label="Оптимальний порядок"
    )
    ax.fill_between(by_n.n, by_n.exact, by_n.user, color=ORANGE, alpha=0.12, linewidth=0)
    ax.set_xlabel("Кількість зупинок у маршруті")
    ax.set_ylabel("Час ходьби, хв")
    ax.set_xticks(by_n.n)
    ax.legend(loc="upper left")
    _save(fig, "e4_by_size")


def main() -> None:
    for fn in (fig_e1, fig_e2, fig_e3, fig_e4):
        fn()


if __name__ == "__main__":
    main()
