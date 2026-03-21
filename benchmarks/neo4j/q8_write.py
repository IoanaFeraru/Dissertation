"""
benchmarks/neo4j/q8_write.py — Neo4j: Q8
=========================================
Q8: Concurrent event ingestion benchmark.

    100 threads each insert individual Event nodes from the pre-generated
    CSV as fast as possible until all rows are exhausted.
    Each thread executes one CREATE per event — the same single-insert
    production pattern used in the PostgreSQL baseline.

Design decisions
────────────────
  - Same events_q8.csv as PostgreSQL — identical data, identical row count.
    The only variable is the database engine.
  - Same 100-thread, single-insert-per-event pattern as PostgreSQL Q8.
    No batching, no pipelining — this isolates engine write throughput.
  - Neo4j driver session pool: driver.session() draws from the internal
    pool rather than opening a raw socket per thread. This is the idiomatic
    Neo4j equivalent of a per-thread psycopg2 connection.
  - Docker stats sampled from dissertation_neo4j_naive container.
  - Output saved to results/neo4j_q8.json.

Q8 has one level only (no naive/optimised split). This is consistent
across all databases — see methodology chapter for rationale.

Usage:
    python q8_write.py                        # full benchmark
    python q8_write.py --rows 10000           # smoke test
    python q8_write.py --threads 10           # reduce concurrency
    python q8_write.py --no-resource-stats    # skip Docker stats
    python q8_write.py --dry-run              # 100 rows, no output file
"""

import argparse
import csv
import json
import math
import os
import sys
import threading
import time
from datetime import datetime, timezone

from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from benchmarks.neo4j.neo4j_conn import get_driver

load_dotenv()

# ── constants ─────────────────────────────────────────────────────────────────

DEFAULT_THREADS   = 100
DEFAULT_CSV_PATH  = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "events_q8.csv"
)
DOCKER_CONTAINER  = "dissertation_neo4j_naive"
RESOURCE_SAMPLE_S = 1.0

# ── Cypher ────────────────────────────────────────────────────────────────────
#
# Creates an Event node with all fields as properties.
# ON CREATE SET avoids duplicate errors on re-runs (same as ON CONFLICT DO NOTHING).
# No FK constraints — matches the PostgreSQL staging table design.

CREATE_CYPHER = """
MERGE (e:EventQ8_1 {id: $id})
ON CREATE SET
    e.user_id     = $user_id,
    e.event_type  = $event_type,
    e.product_id  = $product_id,
    e.session_id  = $session_id,
    e.metadata    = $metadata,
    e.occurred_at = $occurred_at
"""

# ── CSV loading ───────────────────────────────────────────────────────────────

def load_csv(csv_path: str, max_rows: int | None = None) -> list[dict]:
    print(f"  Loading CSV: {csv_path}")
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if max_rows and i >= max_rows:
                break
            rows.append({
                "id":          row["id"]          or None,
                "user_id":     row["user_id"]     or None,
                "event_type":  row["event_type"]  or None,
                "product_id":  row["product_id"]  or None,
                "session_id":  row["session_id"]  or None,
                "metadata":    row["metadata"]    or "{}",
                "occurred_at": row["occurred_at"] or None,
            })
    print(f"  Loaded {len(rows):,} rows from CSV.")
    return rows


def slice_rows(rows: list[dict], n_threads: int) -> list[list[dict]]:
    size   = len(rows) // n_threads
    slices = []
    start  = 0
    for i in range(n_threads):
        end = start + size + (1 if i < len(rows) % n_threads else 0)
        slices.append(rows[start:end])
        start = end
    return slices

# ── Docker resource stats ─────────────────────────────────────────────────────

def start_resource_monitor(container: str, stop_event: threading.Event) -> list[dict]:
    samples = []

    def _sample():
        try:
            import docker
            client = docker.from_env()
            c = client.containers.get(container)
            while not stop_event.is_set():
                stats        = c.stats(stream=False)
                cpu_delta    = (stats["cpu_stats"]["cpu_usage"]["total_usage"]
                                - stats["precpu_stats"]["cpu_usage"]["total_usage"])
                system_delta = (stats["cpu_stats"]["system_cpu_usage"]
                                - stats["precpu_stats"]["system_cpu_usage"])
                n_cpus       = stats["cpu_stats"].get("online_cpus", 1)
                cpu_pct      = (cpu_delta / system_delta) * n_cpus * 100.0 if system_delta > 0 else 0.0
                mem_mb       = stats["memory_stats"].get("usage", 0) / (1024 * 1024)
                samples.append({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "cpu_pct":   round(cpu_pct, 2),
                    "memory_mb": round(mem_mb, 2),
                })
                time.sleep(RESOURCE_SAMPLE_S)
        except Exception as e:
            samples.append({"error": str(e)})

    threading.Thread(target=_sample, daemon=True).start()
    return samples

# ── stats ─────────────────────────────────────────────────────────────────────

def compute_stats(timings: list[float]) -> dict:
    if not timings:
        return {}
    s = sorted(timings)
    n = len(s)
    mean = sum(s) / n
    variance = sum((x - mean) ** 2 for x in s) / n

    def pct(p):
        k = max(0, min(math.ceil((p / 100) * n) - 1, n - 1))
        return round(s[k], 4)

    return {
        "p50":     pct(50),
        "p95":     pct(95),
        "p99":     pct(99),
        "mean":    round(mean, 4),
        "std_dev": round(math.sqrt(variance), 4),
        "min":     round(s[0], 4),
        "max":     round(s[-1], 4),
    }

# ── progress printer ──────────────────────────────────────────────────────────

def progress_printer(total: int, counter: list[int], stop: threading.Event):
    start = time.perf_counter()
    while not stop.is_set():
        time.sleep(5)
        done    = counter[0]
        elapsed = time.perf_counter() - start
        pct     = done / total * 100 if total else 0
        rate    = done / elapsed if elapsed > 0 else 0
        print(f"  [{pct:5.1f}%] {done:>9,}/{total:,}  {rate:,.0f} events/sec", flush=True)

# ── worker ────────────────────────────────────────────────────────────────────

def worker(
    thread_id: int,
    driver,
    slice_: list[dict],
    all_timings: list[float],
    timings_lock: threading.Lock,
    progress_counter: list[int],
    progress_lock: threading.Lock,
    barrier: threading.Barrier,
    errors: list[str],
):
    """
    One session per thread, reused across all rows in the slice.
    This mirrors PostgreSQL's one-connection-per-thread model exactly:
    - PostgreSQL: one psycopg2 connection, autocommit=True, loop inserts
    - Neo4j:      one driver session, loop session.run() calls

    Opening a new session per insert exhausts the connection pool under
    100 threads — the majority time out waiting for a pool slot. Holding
    one session open per thread eliminates pool contention entirely.
    """
    local_timings = []
    barrier.wait()   # all threads start simultaneously

    try:
        with driver.session() as session:
            for row in slice_:
                t0 = time.perf_counter()
                session.run(CREATE_CYPHER, **row)
                elapsed_ms = (time.perf_counter() - t0) * 1_000
                local_timings.append(elapsed_ms)

                with progress_lock:
                    progress_counter[0] += 1
    except Exception as e:
        errors.append(f"Thread {thread_id}: {e}")

    with timings_lock:
        all_timings.extend(local_timings)

# ── main benchmark ────────────────────────────────────────────────────────────

def run_q8(
    csv_path: str,
    n_threads: int,
    max_rows: int | None,
    output_path: str,
    resource_stats: bool,
):
    rows      = load_csv(csv_path, max_rows)
    total     = len(rows)
    n_threads = min(n_threads, total)
    slices    = slice_rows(rows, n_threads)
    del rows

    print(f"\n  Threads    : {n_threads}")
    print(f"  Total rows : {total:,}")
    print(f"  Rows/thread: {len(slices[0]):,} (±1 for remainder)")

    port   = int(os.getenv("NEO4J_NAIVE_PORT", 7687))
    # max_connection_pool_size must be >= n_threads.
    # Default Neo4j pool size is 100 — with 100 threads each holding a
    # session open for the full slice duration, the pool must be at least
    # as large as the thread count. Set to n_threads + 10 for headroom.
    driver = get_driver(port=port, max_connection_pool_size=n_threads + 10)

    # Verify connectivity before launching threads
    try:
        driver.verify_connectivity()
        print(f"  Connected to Neo4j (port {port})")
    except Exception as e:
        print(f"  ✗ Could not connect to Neo4j: {e}")
        return

    all_timings      = []
    timings_lock     = threading.Lock()
    errors           = []
    progress_counter = [0]
    progress_lock    = threading.Lock()
    barrier          = threading.Barrier(n_threads)
    stop_progress    = threading.Event()
    stop_resources   = threading.Event()

    resource_samples = []
    if resource_stats:
        resource_samples = start_resource_monitor(DOCKER_CONTAINER, stop_resources)
        print(f"  Resource monitor started (container: {DOCKER_CONTAINER})")
    else:
        print("  Resource monitoring disabled.")

    progress_thread = threading.Thread(
        target=progress_printer,
        args=(total, progress_counter, stop_progress),
        daemon=True,
    )
    progress_thread.start()

    print(f"\n  Starting benchmark at {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}...")
    wall_start = time.perf_counter()

    threads = []
    for i, slice_ in enumerate(slices):
        t = threading.Thread(
            target=worker,
            args=(
                i, driver, slice_, all_timings, timings_lock,
                progress_counter, progress_lock, barrier, errors,
            ),
            daemon=True,
        )
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    wall_elapsed = time.perf_counter() - wall_start
    stop_progress.set()
    stop_resources.set()
    driver.close()

    actual_events = len(all_timings)
    throughput    = actual_events / wall_elapsed if wall_elapsed > 0 else 0
    stats         = compute_stats(all_timings)

    print(f"\n  {'═' * 46}")
    print(f"  Benchmark complete")
    print(f"  {'─' * 46}")
    print(f"  {'Events inserted':<28} {actual_events:>12,}")
    print(f"  {'Wall time':<28} {wall_elapsed:>11.2f}s")
    print(f"  {'Throughput':<28} {throughput:>10,.0f} events/sec")
    print(f"  {'p50 latency':<28} {stats.get('p50', 0):>11.2f} ms")
    print(f"  {'p95 latency':<28} {stats.get('p95', 0):>11.2f} ms")
    print(f"  {'p99 latency':<28} {stats.get('p99', 0):>11.2f} ms")
    print(f"  {'mean ± std':<28} "
          f"{stats.get('mean', 0):.2f} ± {stats.get('std_dev', 0):.2f} ms")
    print(f"  {'─' * 46}")

    if errors:
        print(f"\n  Errors ({len(errors)}):")
        for e in errors[:10]:
            print(f"    {e}")

    result = {
        "db":                       "neo4j",
        "query_id":                 "Q8",
        "label": (
            "Concurrent event ingestion — single CREATE per event across "
            f"{n_threads} threads. Neo4j driver session pool (idiomatic "
            "equivalent of per-thread psycopg2 connection). MERGE on id "
            "prevents duplicate errors on re-runs. "
            "EventQ8 label used to isolate Q8 data from benchmark events."
        ),
        "timestamp":                datetime.now(timezone.utc).isoformat(),
        "n_threads":                n_threads,
        "total_events":             actual_events,
        "wall_time_s":              round(wall_elapsed, 3),
        "throughput_events_per_sec": round(throughput, 2),
        "errors":                   errors,
        "latency_ms":               stats,
        "resource_stats":           resource_samples,
        "raw_timings_ms":           [round(t, 4) for t in all_timings],
    }

    if output_path and output_path != os.devnull:
        os.makedirs(
            os.path.dirname(output_path) if os.path.dirname(output_path) else ".",
            exist_ok=True,
        )
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        print(f"\n  Saved → {output_path}")

# ── entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Neo4j Q8 concurrent write benchmark")
    parser.add_argument("--threads", type=int, default=DEFAULT_THREADS)
    parser.add_argument("--rows",    type=int, default=None,
                        help="Limit total rows (default: all). Use 10000 for smoke test.")
    parser.add_argument("--csv",     type=str, default=DEFAULT_CSV_PATH)
    parser.add_argument("--no-resource-stats", action="store_true", dest="no_resource_stats")
    parser.add_argument("--dry-run", action="store_true", dest="dry_run")
    parser.add_argument(
        "--output", type=str,
        default=os.path.join(
            os.path.dirname(__file__), "..", "..", "results", "neo4j_q8.json"
        ),
    )
    args = parser.parse_args()

    print("\n" + "=" * 55)
    print("  Neo4j — Q8 Concurrent Write Benchmark")
    print("=" * 55)

    max_rows = 100 if args.dry_run else args.rows

    run_q8(
        csv_path=args.csv,
        n_threads=args.threads,
        max_rows=max_rows,
        output_path=args.output if not args.dry_run else os.devnull,
        resource_stats=not args.no_resource_stats,
    )


if __name__ == "__main__":
    main()