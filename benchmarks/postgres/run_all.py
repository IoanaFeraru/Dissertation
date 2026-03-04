"""
benchmarks/postgres/run_all.py — Phase 2 Full Benchmark Runner
===============================================================
Runs all 8 PostgreSQL benchmarks in sequence and produces a
summary table at the end.

    Q1  Monthly revenue by subscription tier (temporal JOIN)
    Q2  Complete invoice fetch (4-table JOIN)
    Q3  Active session + cart under 50 concurrent threads
    Q4  Co-purchase recommendations (2-hop JOIN)
    Q5  Full-text product search (tsvector + ts_rank_cd)
    Q6  User events in a 30-day window
    Q7  7-day rolling revenue average (generate_series gap-fill)
    Q8  Concurrent event ingestion (1M single INSERTs, 100 threads)

Results are saved individually per query AND as a combined summary.

Usage:
    python run_all.py                        # full run, all 8 benchmarks
    python run_all.py --skip-q8              # skip write benchmark (reads only)
    python run_all.py --iterations 100       # reduced iterations (smoke test)
    python run_all.py --dry-run              # 100 iterations + Q8 dry-run
    python run_all.py --no-resource-stats    # skip Docker stats for Q8
    python run_all.py --only Q1 Q3 Q7       # run specific queries only
"""

import argparse
import importlib.util
import json
import os
import sys
import time
from datetime import datetime, timezone

# ── path setup ────────────────────────────────────────────────────────────────
# Allow imports from the project root (for benchmarks.harness)
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

POSTGRES_DIR = os.path.dirname(__file__)
RESULTS_DIR  = os.path.join(PROJECT_ROOT, "results")

# ── colour helpers ────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
BLUE   = "\033[94m"
RESET  = "\033[0m"

def ok(msg):   print(f"  {GREEN}✔ {msg}{RESET}")
def fail(msg): print(f"  {RED}✘ {msg}{RESET}")
def info(msg): print(f"  {BLUE}> {msg}{RESET}")
def warn(msg): print(f"  {YELLOW}! {msg}{RESET}")

# ── benchmark registry ────────────────────────────────────────────────────────
#
# Each entry defines how to run one benchmark.
# Q1-Q7 are run via the harness (returns a result dict).
# Q8 is run via its own run_q8() function (different interface).

def load_module(filename):
    """Dynamically load a benchmark module by filename."""
    path = os.path.join(POSTGRES_DIR, filename)
    spec = importlib.util.spec_from_file_location(filename[:-3], path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_read_benchmark(module, query_id, label, iterations, concurrency, output_path):
    """Run a Q1-Q7 style benchmark via its make_query_fn + run_benchmark."""
    from benchmarks.harness import run_benchmark

    conn = module.get_connection()
    try:
        # Build the query function — different modules need different args
        if query_id == "Q1":
            query_fn = module.make_query_fn(conn)
        elif query_id in ("Q2", "Q4"):
            pool = module.fetch_product_id_pool(conn, 1000) if query_id == "Q4" \
                   else module.fetch_invoice_id_pool(conn, 1000)
            query_fn = module.make_query_fn(conn, pool)
        elif query_id == "Q3":
            pool = module.fetch_user_id_pool(conn, 1000)
            # Q3 uses per-thread connections internally
            query_fn = module.make_query_fn(pool)
        elif query_id == "Q5":
            query_fn = module.make_query_fn(conn, module.SEARCH_TERMS)
        elif query_id == "Q6":
            pool = module.fetch_user_id_pool(conn, 1000)
            query_fn = module.make_query_fn(conn, pool)
        elif query_id == "Q7":
            query_fn = module.make_query_fn(conn)
        else:
            raise ValueError(f"Unknown query_id: {query_id}")

        return run_benchmark(
            query_fn=query_fn,
            db="postgres",
            query_id=query_id,
            label=label,
            iterations=iterations,
            concurrency=concurrency,
            output_path=output_path,
        )
    finally:
        conn.close()

# ── summary helpers ───────────────────────────────────────────────────────────

def format_ms(val):
    if val is None:
        return "N/A"
    return f"{float(val):.2f} ms"

def format_tps(val):
    if val is None:
        return "N/A"
    return f"{float(val):,.0f} ev/s"

def print_summary(results: list[dict]):
    """Print a formatted summary table of all benchmark results."""
    print("\n" + "═" * 72)
    print("  PHASE 2 SUMMARY — PostgreSQL Baselines")
    print("═" * 72)
    print(f"  {'Query':<6} {'Label':<34} {'p50':>9} {'p95':>9} {'p99':>9} {'Throughput':>12}")
    print(f"  {'─'*6} {'─'*34} {'─'*9} {'─'*9} {'─'*9} {'─'*12}")

    for r in results:
        qid    = r.get("query_id", "?")
        label  = r.get("label", "")[:34]
        lms    = r.get("latency_ms", {})
        p50    = format_ms(lms.get("p50"))
        p95    = format_ms(lms.get("p95"))
        p99    = format_ms(lms.get("p99"))

        # Q8 has throughput instead of per-query latency as primary metric
        if qid == "Q8":
            tps = format_tps(r.get("throughput_events_per_sec"))
        else:
            tps = "—"

        print(f"  {qid:<6} {label:<34} {p50:>9} {p95:>9} {p99:>9} {tps:>12}")

    print("═" * 72)

def save_summary(results: list[dict], output_path: str):
    """Save all results as a combined JSON file."""
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "db": "postgres",
        "phase": 2,
        "benchmarks": results,
    }
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    info(f"Combined summary saved → {output_path}")

# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Run all Phase 2 PostgreSQL benchmarks"
    )
    parser.add_argument(
        "--iterations", type=int, default=1000,
        help="Iterations for Q1-Q7 (default: 1000)",
    )
    parser.add_argument(
        "--skip-q8", action="store_true", dest="skip_q8",
        help="Skip the Q8 write benchmark",
    )
    parser.add_argument(
        "--dry-run", action="store_true", dest="dry_run",
        help="Quick smoke test: 100 iterations for Q1-Q7, 100 rows for Q8",
    )
    parser.add_argument(
        "--no-resource-stats", action="store_true", dest="no_resource_stats",
        help="Disable Docker resource monitoring for Q8",
    )
    parser.add_argument(
        "--only", nargs="+", metavar="Q",
        help="Run only specific queries e.g. --only Q1 Q3 Q8",
    )
    parser.add_argument(
        "--results-dir", type=str, default=RESULTS_DIR,
        dest="results_dir",
        help=f"Directory to save results (default: {RESULTS_DIR})",
    )
    args = parser.parse_args()

    iterations = 100 if args.dry_run else args.iterations
    only       = [q.upper() for q in args.only] if args.only else None

    print("\n" + "═" * 60)
    print("  Phase 2 — PostgreSQL Baseline Benchmarks")
    print("═" * 60)
    print(f"  Iterations  : {iterations} {'(dry-run mode)' if args.dry_run else ''}")
    print(f"  Results dir : {args.results_dir}")
    if only:
        print(f"  Running only: {', '.join(only)}")
    print()

    os.makedirs(args.results_dir, exist_ok=True)

    all_results  = []
    failed       = []
    total_start  = time.perf_counter()

    # ── Q1 ────────────────────────────────────────────────────────────────────
    if not only or "Q1" in only:
        print(f"\n{'─'*60}")
        print("  Q1 — Monthly Revenue (temporal JOIN)")
        print(f"{'─'*60}")
        try:
            mod = load_module("q1_revenue.py")
            result = run_read_benchmark(
                mod, "Q1",
                label="Monthly revenue by subscription tier, last 12 months",
                iterations=iterations,
                concurrency=1,
                output_path=os.path.join(args.results_dir, "postgres_q1_baseline.json"),
            )
            all_results.append(result)
            ok("Q1 complete")
        except Exception as e:
            fail(f"Q1 failed: {e}")
            failed.append("Q1")

    # ── Q2 ────────────────────────────────────────────────────────────────────
    if not only or "Q2" in only:
        print(f"\n{'─'*60}")
        print("  Q2 — Invoice Fetch (4-table JOIN)")
        print(f"{'─'*60}")
        try:
            mod = load_module("q2_invoice.py")
            result = run_read_benchmark(
                mod, "Q2",
                label="Complete invoice fetch via 4-table JOIN",
                iterations=iterations,
                concurrency=1,
                output_path=os.path.join(args.results_dir, "postgres_q2_baseline.json"),
            )
            all_results.append(result)
            ok("Q2 complete")
        except Exception as e:
            fail(f"Q2 failed: {e}")
            failed.append("Q2")

    # ── Q3 ────────────────────────────────────────────────────────────────────
    if not only or "Q3" in only:
        print(f"\n{'─'*60}")
        print("  Q3 — Session + Cart (50 concurrent threads)")
        print(f"{'─'*60}")
        try:
            mod = load_module("q3_session.py")
            result = run_read_benchmark(
                mod, "Q3",
                label="Active session + cart under 50 concurrent threads",
                iterations=iterations,
                concurrency=50,
                output_path=os.path.join(args.results_dir, "postgres_q3_baseline.json"),
            )
            all_results.append(result)
            ok("Q3 complete")
        except Exception as e:
            fail(f"Q3 failed: {e}")
            failed.append("Q3")

    # ── Q4 ────────────────────────────────────────────────────────────────────
    if not only or "Q4" in only:
        print(f"\n{'─'*60}")
        print("  Q4 — Co-Purchase Recommendations (2-hop JOIN)")
        print(f"{'─'*60}")
        try:
            mod = load_module("q4_recommendations.py")
            result = run_read_benchmark(
                mod, "Q4",
                label="Top 10 recommendations via co-purchase 2-hop JOIN",
                iterations=iterations,
                concurrency=1,
                output_path=os.path.join(args.results_dir, "postgres_q4_baseline.json"),
            )
            all_results.append(result)
            ok("Q4 complete")
        except Exception as e:
            fail(f"Q4 failed: {e}")
            failed.append("Q4")

    # ── Q5 ────────────────────────────────────────────────────────────────────
    if not only or "Q5" in only:
        print(f"\n{'─'*60}")
        print("  Q5 — Full-Text Search (tsvector + ts_rank_cd)")
        print(f"{'─'*60}")
        try:
            mod = load_module("q5_search.py")
            result = run_read_benchmark(
                mod, "Q5",
                label="Full-text search via tsvector + GIN index",
                iterations=iterations,
                concurrency=1,
                output_path=os.path.join(args.results_dir, "postgres_q5_baseline.json"),
            )
            all_results.append(result)
            ok("Q5 complete")
        except Exception as e:
            fail(f"Q5 failed: {e}")
            failed.append("Q5")

    # ── Q6 ────────────────────────────────────────────────────────────────────
    if not only or "Q6" in only:
        print(f"\n{'─'*60}")
        print("  Q6 — User Events in 30-day Window")
        print(f"{'─'*60}")
        try:
            mod = load_module("q6_events.py")
            result = run_read_benchmark(
                mod, "Q6",
                label="All user events in 30-day window, composite index",
                iterations=iterations,
                concurrency=1,
                output_path=os.path.join(args.results_dir, "postgres_q6_baseline.json"),
            )
            all_results.append(result)
            ok("Q6 complete")
        except Exception as e:
            fail(f"Q6 failed: {e}")
            failed.append("Q6")

    # ── Q7 ────────────────────────────────────────────────────────────────────
    if not only or "Q7" in only:
        print(f"\n{'─'*60}")
        print("  Q7 — Rolling Revenue Average (generate_series gap-fill)")
        print(f"{'─'*60}")
        try:
            mod = load_module("q7_rolling_revenue.py")
            result = run_read_benchmark(
                mod, "Q7",
                label="7-day rolling avg revenue with generate_series gap-fill",
                iterations=iterations,
                concurrency=1,
                output_path=os.path.join(args.results_dir, "postgres_q7_baseline.json"),
            )
            all_results.append(result)
            ok("Q7 complete")
        except Exception as e:
            fail(f"Q7 failed: {e}")
            failed.append("Q7")

    # ── Q8 ────────────────────────────────────────────────────────────────────
    if not args.skip_q8 and (not only or "Q8" in only):
        print(f"\n{'─'*60}")
        print("  Q8 — Concurrent Event Ingestion (1M events, 100 threads)")
        print(f"{'─'*60}")
        try:
            mod = load_module("q8_write.py")
            csv_path = os.path.join(PROJECT_ROOT, "data", "events_q8.csv")
            output_path = os.path.join(args.results_dir, "postgres_q8_write_baseline.json")
            mod.run_q8(
                csv_path=csv_path,
                n_threads=100,
                max_rows=100 if args.dry_run else None,
                output_path=output_path,
                resource_stats=not args.no_resource_stats,
            )
            # Load the saved result to include in summary
            with open(output_path) as f:
                q8_result = json.load(f)
            all_results.append(q8_result)
            ok("Q8 complete")
        except Exception as e:
            fail(f"Q8 failed: {e}")
            failed.append("Q8")

    # ── final summary ─────────────────────────────────────────────────────────
    total_elapsed = time.perf_counter() - total_start

    if all_results:
        print_summary(all_results)
        save_summary(
            all_results,
            os.path.join(args.results_dir, "postgres_phase2_summary.json"),
        )

    print(f"\n  Total wall time : {total_elapsed:.1f}s ({total_elapsed/60:.1f} min)")
    print(f"  Completed       : {len(all_results)}/{ len(all_results) + len(failed) }")

    if failed:
        warn(f"Failed benchmarks: {', '.join(failed)}")
        print(f"\n  Re-run failed benchmarks with:")
        print(f"    python run_all.py --only {' '.join(failed)}\n")
        sys.exit(1)
    else:
        print(f"\n  {GREEN}All benchmarks complete. Results in: {args.results_dir}{RESET}\n")
        sys.exit(0)


if __name__ == "__main__":
    main()