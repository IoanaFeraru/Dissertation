"""
write_analysis.py — Q8 Write Throughput Analysis
=================================================
Produces:
  outputs/write_stats.csv             — throughput + latency per DB × thread count
  outputs/write_fig1_throughput.png   — throughput lines (events/s vs threads), all DBs
  outputs/write_fig2_latency.png      — p50 / p95 latency vs concurrency, all DBs
  outputs/write_fig3_heatmaps.png     — combined throughput + p99 heatmaps (compact)

Usage:
  python write_analysis.py --results-dir path/to/write_results --out-dir outputs
"""

import argparse
import csv
import json
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
THREAD_ORDER  = [10, 50, 100]
DB_ORDER      = ["postgres", "mongodb", "cassandra", "neo4j",
                 "elasticsearch", "timescaledb"]
DB_DISPLAY    = {
    "postgres":      "PostgreSQL",
    "mongodb":       "MongoDB",
    "cassandra":     "Cassandra",
    "neo4j":         "Neo4j",
    "elasticsearch": "Elasticsearch",
    "timescaledb":   "TimescaleDB",
}
COLOR_MAP = {
    "postgres":      "#4C72B0",
    "mongodb":       "#DD8452",
    "cassandra":     "#55A868",
    "neo4j":         "#8172B2",
    "elasticsearch": "#937860",
    "timescaledb":   "#DA8BC3",
}
MARKER = {
    "postgres":      "o",
    "mongodb":       "s",
    "cassandra":     "^",
    "neo4j":         "D",
    "elasticsearch": "P",
    "timescaledb":   "X",
}


# ── LOAD ───────────────────────────────────────────────────────────────────
def load_write_results(results_dir: str) -> dict:
    """
    Returns: {db: {n_threads: record}}
    """
    data = defaultdict(dict)
    for f in Path(results_dir).glob("*.jsonl"):
        for line in open(f, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if not isinstance(rec, dict):
                continue
            raw_db  = rec.get("db", "").strip()
            db = raw_db.split("_")[0]
            thr = rec.get("n_threads")
            if db and thr is not None:
                data[db][int(thr)] = rec
    print(f"Loaded write results for: {sorted(data.keys())}")
    return dict(data)


# ── CSV ────────────────────────────────────────────────────────────────────
def save_csv(data: dict, path: Path):
    rows = []
    for db in DB_ORDER:
        if db not in data:
            continue
        for thr in THREAD_ORDER:
            rec = data[db].get(thr)
            if not rec:
                continue
            lms = rec.get("latency_ms", {})
            rows.append({
                "db":             db,
                "db_display":     DB_DISPLAY.get(db, db),
                "n_threads":      thr,
                "total_events":   rec.get("total_events"),
                "wall_time_s":    round(rec.get("wall_time_s", 0), 3),
                "throughput_eps": round(rec.get("throughput_events_per_sec", 0), 2),
                "p50_ms":         lms.get("p50"),
                "p95_ms":         lms.get("p95"),
                "p99_ms":         lms.get("p99"),
                "mean_ms":        round(lms.get("mean", 0), 4),
                "std_dev_ms":     round(lms.get("std_dev", 0), 4),
                "min_ms":         lms.get("min"),
                "max_ms":         lms.get("max"),
            })
    if not rows:
        print("No write data found — CSV skipped.")
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    print(f"Saved: {path}")


# ── FIG 1 — THROUGHPUT LINE CHART ─────────────────────────────────────────
def fig_throughput(data: dict, path: Path):
    dbs_present = [d for d in DB_ORDER if d in data]
    if not dbs_present:
        print("No data for throughput figure — skipped.")
        return
    fig, ax = plt.subplots(figsize=(9, 5))

    for db in dbs_present:
        xs, ys = [], []
        for thr in THREAD_ORDER:
            rec = data[db].get(thr)
            if rec:
                xs.append(thr)
                ys.append(rec["throughput_events_per_sec"])
        if xs:
            ax.plot(xs, ys,
                    marker=MARKER[db],
                    color=COLOR_MAP[db],
                    linewidth=2,
                    markersize=8,
                    label=DB_DISPLAY[db])
            # Annotate last point
            ax.annotate(f"{ys[-1]:,.0f}",
                        xy=(xs[-1], ys[-1]),
                        xytext=(6, 0),
                        textcoords="offset points",
                        fontsize=8,
                        color=COLOR_MAP[db],
                        va="center")

    ax.set_xticks(THREAD_ORDER)
    ax.set_xticklabels([f"{t} threads" for t in THREAD_ORDER])
    ax.set_ylabel("Throughput (events / second)")
    ax.set_title("Q8 — Write Throughput vs. Concurrency Level", pad=10)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    ax.legend(loc="upper left", frameon=False)
    ax.set_xlim(5, 115)

    fig.text(0.5, -0.02,
             "Higher values indicate better throughput. 1,000,000 single-record INSERTs per run.",
             ha="center", fontsize=8.5, alpha=0.7)

    plt.tight_layout()
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close()
    print(f"Saved: {path}")


# ── FIG 2 — LATENCY LINES (p50 + p95 per DB) ─────────────────────────────
def fig_latency_lines(data: dict, path: Path):
    dbs_present = [d for d in DB_ORDER if d in data]
    if not dbs_present:
        print("No data for latency lines figure — skipped.")
        return
    n = len(dbs_present)
    cols = 3
    rows = int(np.ceil(n / cols))

    fig, axes = plt.subplots(rows, cols, figsize=(14, 4 * rows), sharey=False)
    axes = axes.flatten()

    for i, db in enumerate(dbs_present):
        ax = axes[i]
        xs, p50s, p95s, p99s = [], [], [], []

        for thr in THREAD_ORDER:
            rec = data[db].get(thr)
            if rec:
                lms = rec["latency_ms"]
                xs.append(thr)
                p50s.append(lms["p50"])
                p95s.append(lms["p95"])
                p99s.append(lms["p99"])

        c = COLOR_MAP[db]
        ax.plot(xs, p50s, "o-",  color=c,         linewidth=2, markersize=6, label="p50")
        ax.plot(xs, p95s, "s--", color=c, alpha=0.7, linewidth=1.5, markersize=5, label="p95")
        ax.plot(xs, p99s, "^:", color=c, alpha=0.45, linewidth=1.2, markersize=4, label="p99")

        ax.fill_between(xs, p50s, p99s, color=c, alpha=0.08)

        ax.set_title(DB_DISPLAY[db], color=c, fontweight="bold", fontsize=10)
        ax.set_xticks(THREAD_ORDER)
        ax.set_xticklabels([str(t) for t in THREAD_ORDER], fontsize=8)
        ax.set_ylabel("Latency (ms)", fontsize=8)
        ax.set_xlabel("Threads", fontsize=8)
        ax.tick_params(labelsize=8)
        ax.legend(fontsize=7.5, frameon=False, loc="upper left")
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(
            lambda x, _: f"{x:.0f}ms" if x < 1000 else f"{x/1000:.1f}s"))

    for j in range(i + 1, len(axes)):
        fig.delaxes(axes[j])

    fig.suptitle("Q8 — Insert Latency Distribution vs. Concurrency Level",
                 fontsize=13, fontweight="bold", y=1.01)

    fig.text(0.5, -0.01,
             "p50 = median, p95 = 95th percentile, p99 = 99th percentile. Shaded band = p50→p99 range.",
             ha="center", fontsize=8.5, alpha=0.7)

    plt.tight_layout()
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close()
    print(f"Saved: {path}")


# ── FIG 3 — COMBINED HEATMAPS ─────────────────────────────────────────────
def fig_heatmaps(data: dict, path: Path):
    dbs = [d for d in DB_ORDER if d in data]
    if not dbs:
        print("No data for heatmaps figure — skipped.")
        return
    thr_labels = [f"{t}T" for t in THREAD_ORDER]

    thr_mat  = np.full((len(dbs), len(THREAD_ORDER)), np.nan)
    p99_mat  = np.full((len(dbs), len(THREAD_ORDER)), np.nan)

    for i, db in enumerate(dbs):
        for j, thr in enumerate(THREAD_ORDER):
            rec = data[db].get(thr)
            if rec:
                thr_mat[i, j] = rec["throughput_events_per_sec"]
                p99_mat[i, j] = rec["latency_ms"]["p99"]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 4.5))

    def _draw(ax, mat, title, cmap, fmt_fn, cbar_label):
        log_mat = np.where(np.isnan(mat), np.nan, np.log10(np.where(mat == 0, 1e-9, mat)))
        im = ax.imshow(log_mat, cmap=cmap, aspect="auto", interpolation="nearest")

        for i in range(len(dbs)):
            for j in range(len(THREAD_ORDER)):
                v = mat[i, j]
                if not np.isnan(v):
                    ax.add_patch(plt.Rectangle((j-0.5, i-0.5), 1, 1,
                                               fill=False, edgecolor="white", lw=0.6))
                    ax.text(j, i, fmt_fn(v), ha="center", va="center",
                            fontsize=9, fontweight="bold", color="black")

        ax.set_xticks(range(len(THREAD_ORDER)))
        ax.set_xticklabels(thr_labels, fontsize=9)
        ax.set_yticks(range(len(dbs)))
        ax.set_yticklabels([DB_DISPLAY[d] for d in dbs], fontsize=9)
        ax.set_title(title, fontsize=11, pad=8)
        ax.grid(False)

        cbar = fig.colorbar(im, ax=ax, fraction=0.04, pad=0.02)
        cbar.set_label(cbar_label, fontsize=8)
        return im

    def _fmt_thr(v):
        return f"{v/1000:.1f}k" if v >= 1000 else f"{v:.0f}"

    def _fmt_lat(v):
        return f"{v:.0f}ms" if v < 1000 else f"{v/1000:.1f}s"

    _draw(ax1, thr_mat,
          "Throughput (events / second)",
          "YlGn",
          _fmt_thr,
          "log₁₀ events/s")

    _draw(ax2, p99_mat,
          "p99 Insert Latency (ms)",
          "YlOrRd",
          _fmt_lat,
          "log₁₀ latency ms")

    fig.suptitle("Q8 — Write Throughput & Tail Latency by Database and Concurrency",
                 fontsize=12, fontweight="bold", y=1.02)

    fig.text(0.5, -0.02,
             "T = threads. Green = higher throughput. Orange/red = higher latency.",
             ha="center", fontsize=8.5, alpha=0.7)

    plt.tight_layout()
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close()
    print(f"Saved: {path}")


# ── MAIN ───────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Q8 Write Throughput Analysis")
    parser.add_argument("--results-dir", required=True)
    parser.add_argument("--out-dir", default="outputs_write")
    args = parser.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    data = load_write_results(args.results_dir)

    save_csv(data, out / "write_stats.csv")
    fig_throughput(data, out / "write_fig1_throughput.png")
    fig_latency_lines(data, out / "write_fig2_latency.png")
    fig_heatmaps(data, out / "write_fig3_heatmaps.png")

    print(f"\nDone. All outputs in: {out.resolve()}")


if __name__ == "__main__":
    main()