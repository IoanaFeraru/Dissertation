"""
benchmarks/harness.py — Universal Benchmarking Harness
=======================================================
Runs any query function N times, records per-run latency in milliseconds,
computes p50/p95/p99, supports concurrent execution via threading, and
saves results to JSON with full metadata.

Usage (from any benchmark module):
    from benchmarks.harness import run_benchmark

    def my_query(conn):
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchall()

    run_benchmark(
        query_fn=my_query,
        get_conn_fn=get_pg_conn,
        db="postgresql",
        query_id="Q1",
        n_iterations=1000,
        concurrency=1,
        output_path="results/postgres_q1_baseline.json",
    )
"""

import json
import os
import time
import threading
import statistics
from datetime import datetime, timezone
from typing import Callable


# ── Percentile helper ─────────────────────────────────────────────────────────

def percentile(data: list[float], p: float) -> float:
    """Return the p-th percentile of a list (interpolated)."""
    if not data:
        raise ValueError("Empty data list")
    s = sorted(data)
    k = (len(s) - 1) * (p / 100)
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (k - lo) * (s[hi] - s[lo])


# ── Thread worker ─────────────────────────────────────────────────────────────

def _worker(
    query_fn: Callable,
    get_conn_fn: Callable,
    iterations: int,
    latencies: list[float],
    errors: list[str],
    lock: threading.Lock,
    warm_up: bool = False,
):
    """
    Opens its own connection, runs query_fn `iterations` times,
    appends each elapsed ms to the shared latencies list under a lock.
    Connections are closed after the worker finishes.
    """
    try:
        conn = get_conn_fn()
    except Exception as e:
        with lock:
            errors.append(f"Connection failed: {e}")
        return

    try:
        for i in range(iterations):
            t0 = time.perf_counter()
            try:
                query_fn(conn)
            except Exception as e:
                with lock:
                    errors.append(f"Iteration {i}: {e}")
                continue
            elapsed_ms = (time.perf_counter() - t0) * 1000
            if not warm_up:
                with lock:
                    latencies.append(elapsed_ms)
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ── Public API ────────────────────────────────────────────────────────────────

def run_benchmark(
    query_fn: Callable,
    get_conn_fn: Callable,
    db: str,
    query_id: str,
    n_iterations: int = 1000,
    concurrency: int = 1,
    output_path: str | None = None,
    warm_up_iterations: int = 10,
    extra_metadata: dict | None = None,
) -> dict:
    """
    Benchmark `query_fn` across `concurrency` threads for `n_iterations` total.

    Parameters
    ----------
    query_fn           : callable(conn) — executes the query. Must be thread-safe
                         (each thread has its own connection).
    get_conn_fn        : callable() → connection — called once per thread.
    db                 : database label for the result (e.g. "postgresql").
    query_id           : query label (e.g. "Q1").
    n_iterations       : total measured iterations split across all threads.
    concurrency        : number of concurrent threads.
    output_path        : if given, result dict is saved here as JSON.
    warm_up_iterations : discarded iterations before measurement begins.
    extra_metadata     : any extra fields to embed in the output JSON.

    Returns
    -------
    dict with stats, config, errors, and a downsampled latency sample.
    """
    G = "\033[92m"; Y = "\033[93m"; R = "\033[91m"; B = "\033[94m"; E = "\033[0m"
    print(f"\n{'─' * 56}")
    print(f"  {B}Benchmark:{E} {db.upper()} / {query_id}")
    print(f"  Iterations: {n_iterations}  |  Concurrency: {concurrency}")
    print(f"{'─' * 56}")

    # ── Warm-up (single thread, results discarded) ──
    if warm_up_iterations > 0:
        print(f"  Warming up ({warm_up_iterations} iterations)…")
        _wl: list[float] = []; _we: list[str] = []; _wlk = threading.Lock()
        _worker(query_fn, get_conn_fn, warm_up_iterations, _wl, _we, _wlk, warm_up=True)
        if _we:
            print(f"  {Y}⚠ Warm-up errors: {_we[:2]}{E}")

    # ── Distribute iterations across threads ──
    base, rem = divmod(n_iterations, concurrency)
    iters_per_thread = [base + (1 if i < rem else 0) for i in range(concurrency)]

    latencies: list[float] = []
    errors:    list[str]   = []
    lock = threading.Lock()

    t_start = time.perf_counter()
    threads = [
        threading.Thread(
            target=_worker,
            args=(query_fn, get_conn_fn, iters_per_thread[i], latencies, errors, lock),
            daemon=True,
        )
        for i in range(concurrency)
    ]
    for t in threads: t.start()
    for t in threads: t.join()
    wall_ms = (time.perf_counter() - t_start) * 1000

    if not latencies:
        raise RuntimeError(f"No measurements collected. Errors: {errors[:5]}")

    n   = len(latencies)
    p50 = percentile(latencies, 50)
    p95 = percentile(latencies, 95)
    p99 = percentile(latencies, 99)
    avg = statistics.mean(latencies)
    sd  = statistics.stdev(latencies) if n > 1 else 0.0
    mn  = min(latencies)
    mx  = max(latencies)
    qps = n / (wall_ms / 1000)

    print(f"  Collected  : {n}")
    print(f"  p50 / p95 / p99 : {p50:.2f} / {p95:.2f} / {p99:.2f} ms")
    print(f"  mean ± stdev    : {avg:.2f} ± {sd:.2f} ms")
    print(f"  min / max       : {mn:.2f} / {mx:.2f} ms")
    print(f"  throughput      : {qps:.1f} qps")
    if errors:
        print(f"  {Y}⚠ Errors  : {len(errors)} (first: {errors[0][:120]}){E}")

    result = {
        "db": db,
        "query_id": query_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "config": {
            "n_iterations": n_iterations,
            "concurrency": concurrency,
            "warm_up_iterations": warm_up_iterations,
        },
        "stats": {
            "n_collected": n,
            "p50_ms":  round(p50, 4),
            "p95_ms":  round(p95, 4),
            "p99_ms":  round(p99, 4),
            "mean_ms": round(avg, 4),
            "stdev_ms": round(sd, 4),
            "min_ms":  round(mn, 4),
            "max_ms":  round(mx, 4),
            "total_wall_ms": round(wall_ms, 2),
            "throughput_qps": round(qps, 2),
        },
        "errors": errors[:20],
        # Downsample to ≤500 points to keep the JSON file small
        "latency_sample_ms": [round(v, 4) for v in latencies[::max(1, n // 500)]],
        **(extra_metadata or {}),
    }

    if output_path:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        print(f"  {G}✔ Saved → {output_path}{E}")

    return result


def sanity_check(result: dict, warn_ms: float = 500.0, fail_ms: float = 5000.0) -> bool:
    """Print a one-line sanity summary. Returns False if p99 exceeds fail_ms."""
    G = "\033[92m"; Y = "\033[93m"; R = "\033[91m"; E = "\033[0m"
    s   = result["stats"]
    tag = f"{result['db']}/{result['query_id']}"
    p99, p50 = s["p99_ms"], s["p50_ms"]
    if p99 > fail_ms:
        print(f"  {R}✘ FAIL  {tag}: p99={p99:.0f}ms > {fail_ms:.0f}ms{E}"); return False
    elif p99 > warn_ms:
        print(f"  {Y}⚠ WARN  {tag}: p99={p99:.0f}ms > {warn_ms:.0f}ms{E}"); return True
    else:
        print(f"  {G}✔ OK    {tag}: p50={p50:.1f}ms  p99={p99:.1f}ms{E}"); return True