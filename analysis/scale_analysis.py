"""
scale_analysis.py — Scalability Analysis (10% / 50% / 100%)
============================================================
Produces:
  outputs/scale_stats.csv               — p50/p95/p99 per DB × query × scale
  outputs/scale_fig1_factor_heatmap.png — latency growth factor heatmap (10→100%)
  outputs/scale_fig2_growth_lines.png   — latency growth lines per DB (all queries)
  outputs/scale_fig3_naive_opt_grid.png — naive vs optimised scaling comparison grid

Usage:
  python scale_analysis.py
      --scale-dir   path/to/scale_results      (10% and 50% records)
      --baseline-dir path/to/baseline_results  (100% records)
      --out-dir     outputs_scale
"""

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

# ── STYLE ──────────────────────────────────────────────────────────────────
plt.style.use("seaborn-v0_8-whitegrid")
matplotlib.rcParams.update({
    "font.family":    "DejaVu Sans",
    "font.size":      10,
    "axes.titlesize": 12,
    "axes.labelsize": 10,
    "legend.fontsize": 9,
    "axes.spines.top":   False,
    "axes.spines.right": False,
})

# ── CONFIG ─────────────────────────────────────────────────────────────────
QUERIES   = [f"Q{i}" for i in range(1, 8)]
SCALES    = [10, 50, 100]
SCALE_LABELS = ["10%", "50%", "100%"]

DB_PAIRS = [
    ("mongodb_naive",       "mongodb_optimised",       "MongoDB"),
    ("cassandra_naive",     "cassandra_optimised",     "Cassandra"),
    ("neo4j_naive",         "neo4j_optimised",         "Neo4j"),
    ("elasticsearch_naive", "elasticsearch_optimised", "Elasticsearch"),
    ("timescaledb_naive",   "timescaledb_optimised",   "TimescaleDB"),
]
ALL_DBS = (
    ["postgres"]
    + [n for n, _, _ in DB_PAIRS]
    + [o for _, o, _ in DB_PAIRS]
)

DB_DISPLAY = {
    "postgres":              "PostgreSQL",
    "mongodb_naive":         "MongoDB (N)",
    "mongodb_optimised":     "MongoDB (O)",
    "cassandra_naive":       "Cassandra (N)",
    "cassandra_optimised":   "Cassandra (O)",
    "neo4j_naive":           "Neo4j (N)",
    "neo4j_optimised":       "Neo4j (O)",
    "elasticsearch_naive":   "Elastic (N)",
    "elasticsearch_optimised":"Elastic (O)",
    "timescaledb_naive":     "Timescale (N)",
    "timescaledb_optimised": "Timescale (O)",
}

COLOR_MAP = {
    "postgres":              "#4C72B0",
    "mongodb_naive":         "#DD8452",
    "mongodb_optimised":     "#C44E52",
    "cassandra_naive":       "#55A868",
    "cassandra_optimised":   "#2E8B57",
    "neo4j_naive":           "#8172B2",
    "neo4j_optimised":       "#5A4E9C",
    "elasticsearch_naive":   "#937860",
    "elasticsearch_optimised":"#6B4F3F",
    "timescaledb_naive":     "#DA8BC3",
    "timescaledb_optimised": "#A55194",
}


# ── LOAD ───────────────────────────────────────────────────────────────────
def _parse_scale(label: str) -> int | None:
    """Extract scale percentage from label string."""
    m = re.search(r"(\d+)%", label)
    if m:
        return int(m.group(1))
    return None


def load_scale_results(scale_dir: str) -> dict:
    """
    Returns: {db: {query_id: {scale_pct: record}}}
    scale_pct in {10, 50}
    """
    data = defaultdict(lambda: defaultdict(dict))
    for f in Path(scale_dir).glob("*.jsonl"):
        for line in open(f, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if not isinstance(rec, dict):
                continue
            db  = rec.get("db", "").strip()
            qid = rec.get("query_id", "").strip()
            lbl = rec.get("label", "")
            scale = _parse_scale(lbl)
            if db and qid and scale:
                data[db][qid][scale] = rec
    print(f"Loaded scale results ({scale_dir}): {sorted(data.keys())}")
    return {k: dict(v) for k, v in data.items()}


def load_baseline_results(baseline_dir: str) -> dict:
    """
    Returns: {db: {query_id: record}}  — these are the 100% scale records
    """
    data = defaultdict(dict)
    for f in Path(baseline_dir).glob("*.jsonl"):
        for line in open(f, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if not isinstance(rec, dict):
                continue
            db  = rec.get("db", "").strip()
            qid = rec.get("query_id", "").strip()
            if db and qid:
                data[db][qid] = rec
    print(f"Loaded baseline results ({baseline_dir}): {sorted(data.keys())}")
    return dict(data)


def merge(scale_data: dict, baseline_data: dict) -> dict:
    """
    Returns: {db: {query_id: {10: p50, 50: p50, 100: p50}}}
    """
    merged = defaultdict(lambda: defaultdict(dict))

    # From baseline (100%)
    for db, queries in baseline_data.items():
        for qid, rec in queries.items():
            p50 = rec.get("latency_ms", {}).get("p50")
            if p50 is not None:
                merged[db][qid][100] = {
                    "p50": rec["latency_ms"]["p50"],
                    "p95": rec["latency_ms"].get("p95"),
                    "p99": rec["latency_ms"].get("p99"),
                }

    # From scale (10%, 50%)
    for db, queries in scale_data.items():
        for qid, scales in queries.items():
            for scale_pct, rec in scales.items():
                p50 = rec.get("latency_ms", {}).get("p50")
                if p50 is not None:
                    merged[db][qid][scale_pct] = {
                        "p50": rec["latency_ms"]["p50"],
                        "p95": rec["latency_ms"].get("p95"),
                        "p99": rec["latency_ms"].get("p99"),
                    }

    return {k: dict(v) for k, v in merged.items()}


# ── CSV ────────────────────────────────────────────────────────────────────
def save_csv(merged: dict, path: Path):
    rows = []
    for db in ALL_DBS:
        if db not in merged:
            continue
        for qid in QUERIES:
            if qid not in merged[db]:
                continue
            for scale in SCALES:
                rec = merged[db][qid].get(scale)
                if rec is None:
                    continue
                rows.append({
                    "db":         db,
                    "db_display": DB_DISPLAY.get(db, db),
                    "query":      qid,
                    "scale_pct":  scale,
                    "p50_ms":     round(rec["p50"], 4) if rec["p50"] else None,
                    "p95_ms":     round(rec["p95"], 4) if rec.get("p95") else None,
                    "p99_ms":     round(rec["p99"], 4) if rec.get("p99") else None,
                })
    if not rows:
        print("No data to write to CSV.")
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    print(f"Saved: {path}")


# ── FIG 1 — GROWTH FACTOR HEATMAP ─────────────────────────────────────────
def fig_factor_heatmap(merged: dict, path: Path):
    """
    For each DB × query: compute factor = p50(100%) / p50(10%).
    Two heatmaps side by side: naive and optimised.
    """
    naive_dbs = ["postgres"] + [n for n, _, _ in DB_PAIRS]
    opt_dbs   = [o for _, o, _ in DB_PAIRS]
    # PostgreSQL has no naive/opt split — put it alone on left
    left_dbs  = naive_dbs
    right_dbs = opt_dbs

    def _build_factor_mat(dbs):
        mat = np.full((len(dbs), len(QUERIES)), np.nan)
        for i, db in enumerate(dbs):
            for j, qid in enumerate(QUERIES):
                v10  = merged.get(db, {}).get(qid, {}).get(10,  {}).get("p50")
                v100 = merged.get(db, {}).get(qid, {}).get(100, {}).get("p50")
                if v10 and v100 and v10 > 0:
                    mat[i, j] = v100 / v10
        return mat

    mat_left  = _build_factor_mat(left_dbs)
    mat_right = _build_factor_mat(right_dbs)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.5))

    def _draw(ax, mat, dbs, title):
        log_mat = np.where(np.isnan(mat), np.nan,
                           np.log2(np.where(mat == 0, 1e-9, mat)))
        vmax = max(np.nanmax(np.abs(log_mat)), 0.5) if not np.all(np.isnan(log_mat)) else 1
        im = ax.imshow(log_mat, cmap="RdYlGn_r",
                       vmin=0, vmax=vmax,
                       aspect="auto", interpolation="nearest")

        for i in range(len(dbs)):
            for j in range(len(QUERIES)):
                v = mat[i, j]
                if not np.isnan(v):
                    ax.add_patch(plt.Rectangle(
                        (j-0.5, i-0.5), 1, 1,
                        fill=False, edgecolor="white", lw=0.6))
                    txt = f"{v:.1f}×" if v >= 1 else "–"
                    ax.text(j, i, txt, ha="center", va="center",
                            fontsize=9, fontweight="bold")

        ax.set_xticks(range(len(QUERIES)))
        ax.set_xticklabels(QUERIES, fontsize=9)
        ax.set_yticks(range(len(dbs)))
        ax.set_yticklabels([DB_DISPLAY.get(d, d) for d in dbs], fontsize=9)
        ax.set_title(title, fontsize=11, pad=8)
        ax.grid(False)

        cbar = fig.colorbar(im, ax=ax, fraction=0.04, pad=0.02)
        cbar.set_label("log₂(p50 at 100% / p50 at 10%)", fontsize=8)
        return im

    _draw(ax1, mat_left,  left_dbs,  "Naïve Implementations")
    _draw(ax2, mat_right, right_dbs, "Optimised Implementations")

    fig.suptitle("Scalability — Latency Growth Factor (100% vs 10% Dataset)",
                 fontsize=13, fontweight="bold", y=1.02)
    fig.text(0.5, -0.01,
             "Values show how many times slower queries become as dataset grows from 10% to full size. "
             "Green = low growth (scales well). Red = high growth (scales poorly).",
             ha="center", fontsize=8.5, alpha=0.7)

    plt.tight_layout()
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close()
    print(f"Saved: {path}")


# ── FIG 2 — LATENCY GROWTH LINES (per DB, all queries overlaid) ───────────
def fig_growth_lines(merged: dict, path: Path):
    """
    One subplot per database pair (naive + optimised side by side within each engine).
    X = scale (10/50/100), Y = p50 latency (log), one line per query.
    """
    # We do one panel per engine family (showing both naive and opt)
    engines = [("PostgreSQL", ["postgres"], None)] + [
        (name, [n], o) for n, o, name in DB_PAIRS
    ]

    n_panels = len(engines)
    cols = 3
    rows = int(np.ceil(n_panels / cols))

    query_colors = plt.cm.tab10(np.linspace(0, 0.9, len(QUERIES)))

    fig, axes = plt.subplots(rows, cols, figsize=(15, 5 * rows))
    axes = axes.flatten()

    for idx, (engine_name, naive_dbs, opt_db) in enumerate(engines):
        ax = axes[idx]

        for qi, qid in enumerate(QUERIES):
            for db in naive_dbs:
                vals = []
                for scale in SCALES:
                    v = merged.get(db, {}).get(qid, {}).get(scale, {}).get("p50")
                    vals.append(v)
                if any(v is not None for v in vals):
                    ys = [v if v is not None else np.nan for v in vals]
                    ax.plot(SCALE_LABELS, ys,
                            "o-", color=query_colors[qi],
                            linewidth=2, markersize=6,
                            label=qid, alpha=0.9)

            # Optimised as dashed overlay
            if opt_db:
                vals_opt = []
                for scale in SCALES:
                    v = merged.get(opt_db, {}).get(qid, {}).get(scale, {}).get("p50")
                    vals_opt.append(v)
                if any(v is not None for v in vals_opt):
                    ys_opt = [v if v is not None else np.nan for v in vals_opt]
                    ax.plot(SCALE_LABELS, ys_opt,
                            "s--", color=query_colors[qi],
                            linewidth=1.3, markersize=4,
                            alpha=0.45)

        ax.set_yscale("log")
        ax.set_title(engine_name, fontsize=10, fontweight="bold")
        ax.set_ylabel("p50 latency ms (log)", fontsize=8)
        ax.tick_params(labelsize=8)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(
            lambda x, _: f"{x:.0f}" if x < 1000 else f"{x/1000:.0f}s"))

    # Shared legend for queries
    handles = [plt.Line2D([0], [0], color=query_colors[i], linewidth=2,
                          marker="o", label=q)
               for i, q in enumerate(QUERIES)]
    handles += [
        plt.Line2D([0], [0], color="gray", linewidth=2, linestyle="-",  label="Naïve"),
        plt.Line2D([0], [0], color="gray", linewidth=1.3, linestyle="--", label="Optimised"),
    ]
    fig.legend(handles=handles, loc="lower center", ncol=9,
               frameon=False, fontsize=8.5, bbox_to_anchor=(0.5, -0.04))

    for j in range(idx + 1, len(axes)):
        fig.delaxes(axes[j])

    fig.suptitle("Scalability — p50 Latency Across Dataset Scales (10% / 50% / 100%)",
                 fontsize=13, fontweight="bold", y=1.01)

    plt.tight_layout()
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close()
    print(f"Saved: {path}")


# ── FIG 3 — NAIVE vs OPTIMISED SCALING COMPARISON ─────────────────────────
def fig_naive_opt_comparison(merged: dict, path: Path):
    """
    For each engine: 3 grouped bars (one per scale) showing naive vs opt p50
    side by side for a representative query per engine.
    Instead: show all queries, arranged as a heatmap of absolute p50 at each scale.
    3 heatmaps stacked: 10% / 50% / 100%.
    """
    naive_dbs = [n for n, _, _ in DB_PAIRS]
    opt_dbs   = [o for _, o, _ in DB_PAIRS]
    engine_names = [name for _, _, name in DB_PAIRS]

    fig, axes = plt.subplots(1, 3, figsize=(16, 5), sharey=False)

    cmaps = ["Blues", "Oranges", "Reds"]
    scale_titles = ["10% Dataset", "50% Dataset", "100% Dataset"]

    for ax_idx, (scale, cmap_name, title) in enumerate(zip(SCALES, cmaps, scale_titles)):
        ax = axes[ax_idx]

        # Build matrix: rows = engines (naive vs opt), cols = queries
        # Show naive and opt as alternating rows
        row_labels = []
        mat_rows   = []

        for eng_idx, (naive, opt, name) in enumerate(DB_PAIRS):
            for db, suffix in [(naive, "(N)"), (opt, "(O)")]:
                row = []
                for qid in QUERIES:
                    v = merged.get(db, {}).get(qid, {}).get(scale, {}).get("p50")
                    row.append(v if v is not None else np.nan)
                mat_rows.append(row)
                row_labels.append(f"{name} {suffix}")

        mat = np.array(mat_rows)
        log_mat = np.where(np.isnan(mat), np.nan,
                           np.log10(np.where(mat == 0, 1e-9, mat)))

        im = ax.imshow(log_mat, cmap=f"{cmap_name}", aspect="auto",
                       interpolation="nearest")

        for i in range(len(row_labels)):
            for j in range(len(QUERIES)):
                v = mat[i, j]
                if not np.isnan(v):
                    ax.add_patch(plt.Rectangle(
                        (j-0.5, i-0.5), 1, 1,
                        fill=False, edgecolor="white", lw=0.5))
                    txt = (f"{v/1000:.1f}s" if v >= 1000 else
                           f"{v:.0f}ms" if v >= 1 else f"{v:.2f}ms")
                    ax.text(j, i, txt, ha="center", va="center",
                            fontsize=7.5, fontweight="bold")

        ax.set_xticks(range(len(QUERIES)))
        ax.set_xticklabels(QUERIES, fontsize=9)
        ax.set_yticks(range(len(row_labels)))
        ax.set_yticklabels(row_labels, fontsize=8)
        ax.set_title(title, fontsize=11, pad=8)
        ax.grid(False)

        cbar = fig.colorbar(im, ax=ax, fraction=0.04, pad=0.02)
        cbar.set_label("log₁₀ p50 ms", fontsize=7.5)

    fig.suptitle("p50 Latency at Each Dataset Scale — Naïve vs. Optimised",
                 fontsize=13, fontweight="bold", y=1.01)
    fig.text(0.5, -0.01,
             "(N) = naïve schema, (O) = optimised schema. Darker = higher latency.",
             ha="center", fontsize=8.5, alpha=0.7)

    plt.tight_layout()
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close()
    print(f"Saved: {path}")


# ── MAIN ───────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Scalability Analysis")
    parser.add_argument("--scale-dir",    required=True,
                        help="Directory with 10%/50% scale JSONL files")
    parser.add_argument("--baseline-dir", required=True,
                        help="Directory with 100% baseline JSONL files")
    parser.add_argument("--out-dir",      default="outputs_scale")
    args = parser.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    scale_data    = load_scale_results(args.scale_dir)
    baseline_data = load_baseline_results(args.baseline_dir)
    merged        = merge(scale_data, baseline_data)

    save_csv(merged, out / "scale_stats.csv")
    fig_factor_heatmap(merged,          out / "scale_fig1_factor_heatmap.png")
    fig_growth_lines(merged,            out / "scale_fig2_growth_lines.png")
    fig_naive_opt_comparison(merged,    out / "scale_fig3_naive_opt_grid.png")

    print(f"\nDone. All outputs in: {out.resolve()}")


if __name__ == "__main__":
    main()