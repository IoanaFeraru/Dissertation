import argparse
import json
from pathlib import Path
from collections import defaultdict

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import stats

# ──────────────────────────────────────────────
# STYLE
# ──────────────────────────────────────────────
plt.style.use("seaborn-v0_8-whitegrid")
matplotlib.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 10,
    "axes.titlesize": 13,
    "axes.labelsize": 11,
    "legend.fontsize": 9,
})

# ──────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────
QUERIES = [f"Q{i}" for i in range(1, 8)]

DB_DISPLAY = {
    "postgres": "PostgreSQL",
    "mongodb_naive": "MongoDB (N)",
    "mongodb_optimised": "MongoDB (O)",
    "cassandra_naive": "Cassandra (N)",
    "cassandra_optimised": "Cassandra (O)",
    "neo4j_naive": "Neo4j (N)",
    "neo4j_optimised": "Neo4j (O)",
    "elasticsearch_naive": "Elastic (N)",
    "elasticsearch_optimised": "Elastic (O)",
    "timescaledb_naive": "Timescale (N)",
    "timescaledb_optimised": "Timescale (O)",
}

ROW_ORDER = list(DB_DISPLAY.keys())

COLOR_MAP = {
    "postgres": "#4C72B0",

    "mongodb_naive": "#DD8452",
    "mongodb_optimised": "#C44E52",

    "cassandra_naive": "#55A868",
    "cassandra_optimised": "#2E8B57",

    "neo4j_naive": "#8172B2",
    "neo4j_optimised": "#5A4E9C",

    "elasticsearch_naive": "#937860",
    "elasticsearch_optimised": "#6B4F3F",

    "timescaledb_naive": "#DA8BC3",
    "timescaledb_optimised": "#A55194",
}

ENGINE_PAIRS = [
    ("mongodb_naive", "postgres"),
    ("cassandra_naive", "postgres"),
    ("neo4j_naive", "postgres"),
    ("elasticsearch_naive", "postgres"),
    ("timescaledb_naive", "postgres"),
]

SCHEMA_PAIRS = [
    ("mongodb_naive", "mongodb_optimised"),
    ("cassandra_naive", "cassandra_optimised"),
    ("neo4j_naive", "neo4j_optimised"),
    ("elasticsearch_naive", "elasticsearch_optimised"),
    ("timescaledb_naive", "timescaledb_optimised"),
]

ENGINE_NAMES = ["MongoDB", "Cassandra", "Neo4j", "Elastic", "Timescale"]

# ──────────────────────────────────────────────
def load_results(results_dir):
    data = defaultdict(dict)
    for f in Path(results_dir).glob("*.jsonl"):
        for line in open(f, encoding="utf-8"):
            rec = json.loads(line)
            data[rec["db"]][rec["query_id"]] = rec
    return dict(data)

def significance_marker(p):
    if p < 0.001: return "***"
    if p < 0.01: return "**"
    if p < 0.05: return "*"
    return ""

# ──────────────────────────────────────────────
# FIG 1 — OVERLAY
# ──────────────────────────────────────────────
def fig_overview_bars(data, path):
    fig, ax = plt.subplots(figsize=(13, 6))

    x = np.arange(len(QUERIES))
    width = 0.07  # many DBs → narrow bars

    dbs = [d for d in ROW_ORDER if d in data]

    for i, db in enumerate(dbs):
        vals = [data[db][q]["latency_ms"]["p50"] for q in QUERIES]

        ax.bar(
            x + i * width,
            vals,
            width,
            label=DB_DISPLAY[db],
            color=COLOR_MAP[db],
            alpha=0.9
        )

    ax.set_yscale("log")
    ax.set_xticks(x + width * len(dbs) / 2)
    ax.set_xticklabels(QUERIES)

    ax.set_title("Latency Comparison Across Databases and Queries",
                 fontweight="bold", pad=12)
    ax.set_ylabel("p50 latency (ms, log scale)")

    ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, -0.2),
        ncol=4,
        frameon=False
    )

    fig.text(
        0.5, 0.02,
        "Each group represents a query. Lower values indicate better performance.",
        ha="center",
        fontsize=9,
        alpha=0.7
    )

    plt.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close()

# ──────────────────────────────────────────────
# FIG 2 — ENGINE SPEEDUP
# ──────────────────────────────────────────────
def fig_engine_speedup(data, path):
    fig, ax = plt.subplots(figsize=(12, 5))

    x = np.arange(len(QUERIES))
    width = 0.15

    for i, (naive, pg) in enumerate(ENGINE_PAIRS):
        vals, sigs = [], []

        for q in QUERIES:
            n = data[naive][q]["raw_timings_ms"]
            p = data[pg][q]["raw_timings_ms"]

            speed = np.median(n) / np.median(p)
            vals.append(speed)

            _, pval = stats.ttest_ind(n, p, equal_var=False)
            sigs.append(significance_marker(pval))

        bars = ax.bar(
            x + i * width, vals, width,
            color=COLOR_MAP[naive],
            label=ENGINE_NAMES[i]
        )

        for b, v, s in zip(bars, vals, sigs):
            ax.text(
                b.get_x() + b.get_width()/2,
                v * 1.1,
                f"{v:.1f}×{s}",
                ha="center",
                fontsize=8
            )

    ax.set_yscale("log")
    ax.set_xticks(x + width * 2)
    ax.set_xticklabels(QUERIES)

    ax.set_title("Engine Effect (vs PostgreSQL)", pad=12, fontweight="bold")
    ax.set_ylabel("Speedup (×, log scale)")

    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=3, frameon=False)

    fig.text(0.5, -0.08,
        "Values >1 indicate PostgreSQL is faster. Asterisks denote statistical significance.",
        ha="center", fontsize=9, alpha=0.7)

    plt.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close()

# ──────────────────────────────────────────────
# FIG 3 — SCHEMA SPEEDUP
# ──────────────────────────────────────────────
def fig_schema_speedup(data, path):
    fig, ax = plt.subplots(figsize=(12, 5))

    x = np.arange(len(QUERIES))
    width = 0.15

    for i, (naive, opt) in enumerate(SCHEMA_PAIRS):
        vals = []

        for q in QUERIES:
            n = data[naive][q]["latency_ms"]["p50"]
            o = data[opt][q]["latency_ms"]["p50"]
            vals.append(n / o)

        bars = ax.bar(
            x + i * width, vals, width,
            color=COLOR_MAP[opt],
            label=ENGINE_NAMES[i]
        )

        for b, v in zip(bars, vals):
            ax.text(
                b.get_x() + b.get_width()/2,
                v * 1.05,
                f"{v:.1f}×",
                ha="center",
                fontsize=8
            )

    ax.set_yscale("log")
    ax.set_xticks(x + width * 2)
    ax.set_xticklabels(QUERIES)

    ax.set_title("Schema Effect (Optimised vs Naïve)", pad=12, fontweight="bold")
    ax.set_ylabel("Speedup (×, log scale)")

    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=3, frameon=False)

    fig.text(0.5, -0.08,
        "Speedup relative to naïve schema design.",
        ha="center", fontsize=9, alpha=0.7)

    plt.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close()

# ──────────────────────────────────────────────
# FIG 4 — DISTRIBUTION GRID
# ──────────────────────────────────────────────
def fig_distribution(data, path):
    valid_queries = [q for q in QUERIES if any(q in data[d] for d in data)]
    cols = 4
    rows = int(np.ceil(len(valid_queries) / cols))

    fig, axes = plt.subplots(rows, cols, figsize=(16, 4 * rows))
    axes = axes.flatten()

    for i, q in enumerate(valid_queries):
        ax = axes[i]

        raw = []
        for db in ROW_ORDER:
            if db in data and q in data[db]:
                raw.append(data[db][q]["raw_timings_ms"])

        ax.boxplot(raw, showfliers=False)
        ax.set_title(q, fontsize=10, pad=6)
        ax.set_yscale("log")

    for j in range(i + 1, len(axes)):
        fig.delaxes(axes[j])

    fig.suptitle("Latency Distribution Across Queries", fontsize=14, fontweight="bold", y=0.98)

    legend_labels = [
        f"{i + 1} = {DB_DISPLAY[db]}"
        for i, db in enumerate(ROW_ORDER)
    ]

    fig.legend(
        legend_labels,
        loc="lower center",
        ncol=4,
        fontsize=9,
        frameon=False,
        bbox_to_anchor=(0.5, -0.01)
    )

    ax.set_xticks(range(1, len(raw) + 1))
    ax.set_xticklabels(range(1, len(raw) + 1))
    plt.subplots_adjust(bottom=0.15)

    plt.subplots_adjust(hspace=0.35, wspace=0.15, top=0.88)
    fig.savefig(path, dpi=160)
    plt.close()


# ──────────────────────────────────────────────
# FIG 5 — HEATMAP (clean, no internal lines)
# ──────────────────────────────────────────────
def fig_heatmap(data, path):
    dbs = [d for d in ROW_ORDER if d in data]

    mat = np.array([
        [data[d][q]["latency_ms"]["p50"] for q in QUERIES]
        for d in dbs
    ])

    log_mat = np.log10(mat)

    fig, ax = plt.subplots(figsize=(12, 5))

    im = ax.imshow(
        log_mat,
        cmap="RdYlBu_r",
        aspect="auto",
        interpolation="nearest"
    )

    for i in range(len(dbs)):
        for j in range(len(QUERIES)):
            # Add rectangle border around each cell
            rect = plt.Rectangle((j - 0.5, i - 0.5), 1, 1,
                                 fill=False,
                                 edgecolor="white",
                                 linewidth=0.5)
            ax.add_patch(rect)

            val = mat[i, j]
            ax.text(
                j, i,
                f"{val:.1f}",
                ha="center",
                va="center",
                fontsize=8,
                color="black"
            )

    ax.set_xticks(range(len(QUERIES)))
    ax.set_xticklabels(QUERIES, fontsize=10)
    ax.set_yticks(range(len(dbs)))
    ax.set_yticklabels([DB_DISPLAY[d] for d in dbs], fontsize=9)

    ax.set_title("p50 Latency Heatmap (log₁₀ scale, ms)", fontweight="normal", pad=12)

    cbar = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02)
    cbar.set_label("log₁₀ latency (ms)", fontsize=9)

    ax.grid(False)

    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_color("gray")
        spine.set_linewidth(0.5)

    fig.text(
        0.5, 0.02,
        "Blue = faster (lower latency), Red = slower (higher latency). Values in milliseconds.",
        ha="center",
        fontsize=9,
        alpha=0.7
    )

    plt.subplots_adjust(left=0.2, right=0.92, top=0.88, bottom=0.15)
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close()
    print(f"Saved: {path}")

# ──────────────────────────────────────────────
# FIG 6 — SCHEMA HEATMAP (clean, no internal lines)
# ──────────────────────────────────────────────
def fig_schema_heatmap(data, path):
    mat = []

    for naive, opt in SCHEMA_PAIRS:
        row = []
        for q in QUERIES:
            n = data[naive][q]["latency_ms"]["p50"]
            o = data[opt][q]["latency_ms"]["p50"]
            row.append(n / o if o > 0 else float('inf'))
        mat.append(row)

    mat = np.array(mat)
    log_mat = np.log2(mat)

    fig, ax = plt.subplots(figsize=(12, 4))

    vmax = max(np.nanmax(np.abs(log_mat)), 1.0)
    im = ax.imshow(
        log_mat,
        cmap="RdYlGn",  # Red → Yellow → Green
        vmin=-vmax,
        vmax=vmax,
        aspect="auto",
        interpolation="nearest"
    )

    # Add thin white borders around each cell
    for i in range(len(mat)):
        for j in range(len(mat[0])):
            rect = plt.Rectangle((j - 0.5, i - 0.5), 1, 1,
                                 fill=False,
                                 edgecolor="white",
                                 linewidth=0.5)
            ax.add_patch(rect)

            val = mat[i, j]
            if np.isinf(val) or np.isnan(val):
                text = "N/A"
            else:
                text = f"{val:.1f}×"

            ax.text(
                j, i,
                text,
                ha="center",
                va="center",
                fontsize=9,
                color="black"
            )

    ax.set_xticks(range(len(QUERIES)))
    ax.set_xticklabels(QUERIES, fontsize=10)
    ax.set_yticks(range(len(ENGINE_NAMES)))
    ax.set_yticklabels(ENGINE_NAMES, fontsize=9)

    ax.set_title("Schema Optimisation Speedup (p50 latency)", fontweight="normal", pad=12)

    # Remove all internal grid lines
    ax.grid(False)

    # Set outer border only
    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_color("gray")
        spine.set_linewidth(0.5)

    # Colorbar
    cbar = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02)
    cbar.set_label("log₂ speedup (positive = optimised faster)", fontsize=9)

    ticks = [-vmax, 0, vmax]
    cbar.set_ticks(ticks)
    cbar.set_ticklabels(
        [f"{2 ** t:.1f}× slower" if t < 0 else f"{2 ** t:.1f}× faster" if t > 0 else "1×" for t in ticks])

    fig.text(
        0.5, 0.02,
        "Values >1.0× indicate optimisation improved performance. Green = faster, Red = slower.",
        ha="center",
        fontsize=9,
        alpha=0.7
    )

    plt.subplots_adjust(left=0.2, right=0.92, top=0.88, bottom=0.18)
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close()
    print(f"Saved: {path}")

# ──────────────────────────────────────────────
# FIG 7 — ENGINE HEATMAP (PostgreSQL vs Naïve)
# ──────────────────────────────────────────────
def fig_engine_heatmap(data, path):
    mat = []

    for naive, pg in ENGINE_PAIRS:
        row = []
        for q in QUERIES:
            n = data[naive][q]["latency_ms"]["p50"]
            p = data[pg][q]["latency_ms"]["p50"]

            if p > 0:
                row.append(n / p)
            else:
                row.append(float('inf'))
        mat.append(row)

    mat = np.array(mat)
    log_mat = np.log2(mat)

    fig, ax = plt.subplots(figsize=(12, 4))

    vmax = max(np.nanmax(np.abs(log_mat)), 1.0)

    im = ax.imshow(
        log_mat,
        cmap="RdYlBu_r",  # Blue = faster PG, Red = slower PG
        vmin=-vmax,
        vmax=vmax,
        aspect="auto",
        interpolation="nearest"
    )

    # Draw clean white borders and annotate values
    for i in range(len(mat)):
        for j in range(len(mat[0])):
            rect = plt.Rectangle(
                (j - 0.5, i - 0.5),
                1, 1,
                fill=False,
                edgecolor="white",
                linewidth=0.5
            )
            ax.add_patch(rect)

            val = mat[i, j]

            if np.isinf(val) or np.isnan(val):
                text = "N/A"
            else:
                text = f"{val:.1f}×"

            ax.text(
                j, i,
                text,
                ha="center",
                va="center",
                fontsize=9,
                color="black"
            )

    ax.set_xticks(range(len(QUERIES)))
    ax.set_xticklabels(QUERIES, fontsize=10)

    ax.set_yticks(range(len(ENGINE_NAMES)))
    ax.set_yticklabels(ENGINE_NAMES, fontsize=9)

    ax.set_title(
        "Engine Speedup vs PostgreSQL (p50 latency)",
        pad=12
    )

    ax.grid(False)

    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_color("gray")
        spine.set_linewidth(0.5)

    # Colorbar
    cbar = fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02)
    cbar.set_label("log₂ speedup (positive = PostgreSQL faster)", fontsize=9)

    ticks = [-vmax, 0, vmax]
    cbar.set_ticks(ticks)
    cbar.set_ticklabels([
        f"{2 ** t:.1f}× PG slower" if t < 0 else
        f"{2 ** t:.1f}× PG faster" if t > 0 else
        "1×"
        for t in ticks
    ])

    fig.text(
        0.5, 0.02,
        "Values >1.0× indicate PostgreSQL is faster. Blue = PostgreSQL advantage, Red = naïve engine advantage.",
        ha="center",
        fontsize=9,
        alpha=0.7
    )

    plt.subplots_adjust(left=0.2, right=0.92, top=0.88, bottom=0.18)
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close()

    print(f"Saved: {path}")


# ──────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", required=True)
    parser.add_argument("--out-dir", default="outputs")
    args = parser.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    data = load_results(args.results_dir)

    #fig_overview_bars(data, out / "fig_1_overlay.png")
    #fig_engine_speedup(data, out / "fig_2_engine.png")
    #fig_schema_speedup(data, out / "fig_3_schema.png")
    fig_distribution(data, out / "fig_4_distribution.png")
    #fig_heatmap(data, out / "fig_5_heatmap.png")
    #fig_schema_heatmap(data, out / "fig_6_schema_heatmap.png")
    #fig_engine_heatmap(data, out / "fig_7_engine_heatmap.png")
    print(f"Done → {out.resolve()}")

if __name__ == "__main__":
    main()