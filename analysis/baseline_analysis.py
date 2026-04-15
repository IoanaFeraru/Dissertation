"""
analysis.py  —  Dissertation benchmark analysis
================================================
Produces:
  outputs/stats_summary.csv         — engine-effect & schema-effect Welch t + Cliff delta
  outputs/fig_master_p50.png        — p50 heatmap (all DBs × queries)
  outputs/fig_engine_Q*.png         — per-query engine-effect bar charts (7 files)
  outputs/fig_schema_Q*.png         — per-query schema-effect bar charts (7 files)
  outputs/fig_schema_per_db.png     — schema effect: naive vs opt per database (grid)
  outputs/fig_engine_per_db.png     — engine effect: PG vs naive per database (grid)
  outputs/fig_boxplot_Q*.png        — box plots from raw timings (7 files)

Usage
-----
  python analysis.py --results-dir path/to/jsonl/files

Each JSONL file must have one JSON object per line.
raw_timings_ms is required for statistical tests and box plots.
"""

import argparse
import json
import math
import os
import sys
import warnings
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from scipy import stats

# ──────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────
QUERIES = [f"Q{i}" for i in range(1, 8)]

# Canonical display names
DB_DISPLAY = {
    "postgres":              "PostgreSQL",
    "mongodb_naive":         "MongoDB (naive)",
    "mongodb_optimised":     "MongoDB (opt.)",
    "cassandra_naive":       "Cassandra (naive)",
    "cassandra_optimised":   "Cassandra (opt.)",
    "neo4j_naive":           "Neo4j (naive)",
    "neo4j_optimised":       "Neo4j (opt.)",
    "elasticsearch_naive":   "ES (naive)",
    "elasticsearch_optimised":"ES (opt.)",
    "timescaledb_naive":     "TimescaleDB (naive)",
    "timescaledb_optimised": "TimescaleDB (opt.)",
}

# Order for master table rows
ROW_ORDER = [
    "postgres",
    "mongodb_naive",   "mongodb_optimised",
    "cassandra_naive", "cassandra_optimised",
    "neo4j_naive",     "neo4j_optimised",
    "elasticsearch_naive", "elasticsearch_optimised",
    "timescaledb_naive",   "timescaledb_optimised",
]

# Engine-effect pairs: (naive_db, baseline_db)
ENGINE_PAIRS = [
    ("mongodb_naive",       "postgres"),
    ("cassandra_naive",     "postgres"),
    ("neo4j_naive",         "postgres"),
    ("elasticsearch_naive", "postgres"),
    ("timescaledb_naive",   "postgres"),
]

# Schema-effect pairs: (naive_db, optimised_db)
SCHEMA_PAIRS = [
    ("mongodb_naive",       "mongodb_optimised"),
    ("cassandra_naive",     "cassandra_optimised"),
    ("neo4j_naive",         "neo4j_optimised"),
    ("elasticsearch_naive", "elasticsearch_optimised"),
    ("timescaledb_naive",   "timescaledb_optimised"),
]

ENGINE_DB_NAMES = ["MongoDB", "Cassandra", "Neo4j", "Elasticsearch", "TimescaleDB"]

# Colour palette
PALETTE = {
    "postgres":              "#4C72B0",
    "mongodb_naive":         "#DD8452",
    "mongodb_optimised":     "#c0500a",
    "cassandra_naive":       "#55A868",
    "cassandra_optimised":   "#1f6e38",
    "neo4j_naive":           "#C44E52",
    "neo4j_optimised":       "#8a0f13",
    "elasticsearch_naive":   "#8172B2",
    "elasticsearch_optimised":"#4b3a8c",
    "timescaledb_naive":     "#937860",
    "timescaledb_optimised": "#5c4433",
}

OUT_DIR = Path("outputs")


# ──────────────────────────────────────────────
# LOAD DATA
# ──────────────────────────────────────────────
def load_results(results_dir: str) -> dict:
    """
    Returns: {db_key: {query_id: record_dict}}
    """
    data = defaultdict(dict)
    p = Path(results_dir)
    jsonl_files = list(p.glob("**/*.jsonl")) + list(p.glob("**/*.json"))
    if not jsonl_files:
        sys.exit(f"No .jsonl/.json files found in {results_dir}")

    for fpath in jsonl_files:
        with open(fpath, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(rec, dict):
                    continue
                db  = rec.get("db", "").strip()
                qid = rec.get("query_id", "").strip()
                if db and qid:
                    data[db][qid] = rec

    if not data:
        sys.exit("No valid records loaded.")
    print(f"Loaded {sum(len(v) for v in data.values())} records "
          f"from {len(data)} database keys.")
    return dict(data)


# ──────────────────────────────────────────────
# STATISTICS
# ──────────────────────────────────────────────
def cliff_delta(a: list[float], b: list[float]) -> float:
    """Non-parametric effect size. Positive => a tends to be larger than b."""
    a, b = np.asarray(a), np.asarray(b)
    m, n = len(a), len(b)
    # Vectorised dominance count
    dominance = np.sum(np.sign(a[:, None] - b[None, :]))
    return float(dominance) / (m * n)


def cliff_label(d: float) -> str:
    ad = abs(d)
    if ad < 0.147:
        return "negligible"
    if ad < 0.33:
        return "small"
    if ad < 0.474:
        return "medium"
    return "large"


def run_stat_tests(data: dict) -> list[dict]:
    """
    Run Welch t-test + Cliff delta for all engine-effect and schema-effect pairs.
    Returns list of result dicts.
    """
    rows = []

    def _test(kind, qid, db_a, db_b, label_a, label_b):
        rec_a = data.get(db_a, {}).get(qid)
        rec_b = data.get(db_b, {}).get(qid)
        if rec_a is None or rec_b is None:
            return
        ra = rec_a.get("raw_timings_ms", [])
        rb = rec_b.get("raw_timings_ms", [])
        if len(ra) < 2 or len(rb) < 2:
            warnings.warn(f"Insufficient raw timings for {db_a} vs {db_b} {qid} — skipping.")
            return

        t_stat, p_val = stats.ttest_ind(ra, rb, equal_var=False)
        d = cliff_delta(ra, rb)  # positive => a > b (a is slower if positive)
        p50_a = rec_a["latency_ms"]["p50"]
        p50_b = rec_b["latency_ms"]["p50"]
        speedup = p50_a / p50_b if p50_b > 0 else float("inf")

        rows.append({
            "effect_type": kind,
            "query":        qid,
            "db_a":         db_a,
            "db_b":         db_b,
            "label_a":      label_a,
            "label_b":      label_b,
            "p50_a_ms":     round(p50_a, 4),
            "p50_b_ms":     round(p50_b, 4),
            "speedup_b_over_a": round(speedup, 2),   # >1 means b is faster
            "t_stat":       round(t_stat, 4),
            "p_value":      round(p_val, 6),
            "significant":  p_val < 0.05,
            "cliff_delta":  round(d, 4),
            "cliff_label":  cliff_label(d),
        })

    # Engine effect: naive vs PostgreSQL baseline
    for (naive_db, base_db), name in zip(ENGINE_PAIRS, ENGINE_DB_NAMES):
        for qid in QUERIES:
            _test("engine", qid, naive_db, base_db,
                  f"{name} (naive)", "PostgreSQL")

    # Schema effect: optimised vs naive
    for (naive_db, opt_db), name in zip(SCHEMA_PAIRS, ENGINE_DB_NAMES):
        for qid in QUERIES:
            _test("schema", qid, naive_db, opt_db,
                  f"{name} (naive)", f"{name} (opt.)")

    return rows


def save_stats_csv(rows: list[dict], path: Path):
    import csv
    if not rows:
        print("No stat rows to save.")
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    print(f"Saved: {path}")

def print_master_table(data: dict):
    """Print ASCII master table to stdout."""
    col_w = 18
    header = f"{'Database':<28}" + "".join(f"{q:>{col_w}}" for q in QUERIES)
    print("\n" + "=" * len(header))
    print("MASTER p50 LATENCY TABLE")
    print("=" * len(header))
    print(header)
    print("-" * len(header))
    for db in ROW_ORDER:
        if db not in data:
            continue
        row = f"{DB_DISPLAY.get(db, db):<28}"
        for qid in QUERIES:
            rec = data.get(db, {}).get(qid)
            v = rec["latency_ms"]["p50"] if rec else None
            row += f"{(_fmt(v) if v is not None else '—'):>{col_w}}"
        print(row)
    print("=" * len(header))


# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Dissertation benchmark analysis")
    parser.add_argument("--results-dir", default=".",
                        help="Directory containing JSONL result files")
    parser.add_argument("--out-dir", default="outputs",
                        help="Output directory for figures and CSV")
    args = parser.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    data = load_results(args.results_dir)

    # Print summary table to terminal
    print_master_table(data)

    # Statistical tests → CSV
    stat_rows = run_stat_tests(data)
    if stat_rows:
        save_stats_csv(stat_rows, out / "stats_summary.csv")
        # Print quick summary
        print("\nSTATISTICAL SUMMARY (significant engine-effect pairs):")
        print(f"{'Query':<6} {'DB':<22} {'p50 naive':>12} {'p50 PG':>10} "
              f"{'speedup':>9} {'p-value':>10} {'Cliff δ':>9} {'label':<12}")
        print("-" * 95)
        for r in stat_rows:
            if r["effect_type"] == "engine" and r["significant"]:
                print(f"{r['query']:<6} {r['label_a']:<22} "
                      f"{_fmt(r['p50_a_ms']):>12} {_fmt(r['p50_b_ms']):>10} "
                      f"{r['speedup_b_over_a']:>9.2f}× "
                      f"{r['p_value']:>10.4f} "
                      f"{r['cliff_delta']:>9.4f} "
                      f"{r['cliff_label']:<12}")
        print("\nSCHEMA EFFECT (significant improvements):")
        print(f"{'Query':<6} {'DB':<22} {'p50 naive':>12} {'p50 opt':>10} "
              f"{'speedup':>9} {'p-value':>10} {'Cliff δ':>9} {'label':<12}")
        print("-" * 95)
        for r in stat_rows:
            if r["effect_type"] == "schema" and r["significant"] and r["speedup_b_over_a"] > 1:
                print(f"{r['query']:<6} {r['label_a']:<22} "
                      f"{_fmt(r['p50_a_ms']):>12} {_fmt(r['p50_b_ms']):>10} "
                      f"{r['speedup_b_over_a']:>9.2f}× "
                      f"{r['p_value']:>10.4f} "
                      f"{r['cliff_delta']:>9.4f} "
                      f"{r['cliff_label']:<12}")
    else:
        print("No stat rows computed (raw_timings_ms missing from files?).")
        print("Add raw_timings_ms to your JSONL files and re-run.")

    print(f"\nDone. All outputs in: {out.resolve()}")


if __name__ == "__main__":
    main()