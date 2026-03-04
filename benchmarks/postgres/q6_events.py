"""
benchmarks/postgres/q6_events.py — PostgreSQL Baseline: Q6
===========================================================
Q6: Retrieve all activity events for a specific user in a
    30-day window, ordered by time.

    This is the PostgreSQL baseline for the Cassandra comparison (Q6).
    Cassandra will serve the same result via a single wide-row partition
    scan with (user_id, month) as the composite partition key and
    occurred_at as the clustering column.

Killer feature demonstrated (Cassandra side):
    Wide-row partition scan at 5M+ rows — Cassandra stores all events
    for a (user_id, month) partition physically contiguous on disk.
    A time-range scan within a partition is a sequential read with no
    index traversal. PostgreSQL must use a B-tree index scan across a
    heap table, which involves random I/O for large result sets and
    lock overhead on the shared buffer pool.

PostgreSQL baseline design notes
──────────────────────────────────
The composite index idx_events_user_time on (user_id, occurred_at DESC)
covers both the WHERE and ORDER BY clauses, giving PostgreSQL an
index-only scan path in most cases.

With 6.3M events across 100K users, the average user has ~63 events.
A 30-day window will typically return 5-15 rows per user — a realistic
hot path that reflects genuine per-user activity queries.

Since the dataset is fixed to 2025, window start dates are drawn
randomly from 2025-01-01 to 2025-11-30 (leaving 30 days of headroom
so the window always falls within the dataset). Using NOW() - 30 days
would return zero rows for every iteration.

A (user_id, window_start) pair is sampled randomly each iteration —
same user with different windows measures true range-scan variance,
while different users avoids buffer cache bias on frequently-queried
user partitions.

Usage:
    python q6_events.py                   # 1000 iterations
    python q6_events.py --iterations 100  # quick smoke test
    python q6_events.py --explain         # EXPLAIN ANALYZE
    python q6_events.py --dry-run         # run once, print result sample
    python q6_events.py --pool-size 500   # pre-fetch 500 user IDs
"""

import argparse
import os
import random
import sys
from datetime import date, timedelta

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from benchmarks.harness import run_benchmark

load_dotenv()

# -- dataset date range --------------------------------------------------------

WINDOW_DAYS   = 30
DATASET_START = date(2025, 1, 1)
# Leave WINDOW_DAYS of headroom so the window always falls within the data
DATASET_END   = date(2025, 12, 31) - timedelta(days=WINDOW_DAYS)

# -- connection ----------------------------------------------------------------

from pg_conn import get_connection

# -- query --------------------------------------------------------------------
#
# Design notes
# ------------
# The WHERE clause uses:
#   user_id = %s                         -- equality on first index column
#   occurred_at BETWEEN %s AND %s        -- range on second index column
#
# This is the optimal pattern for the composite index (user_id, occurred_at DESC).
# PostgreSQL can seek directly to the user's section of the index and scan
# the date range without touching any other users' rows.
#
# Cassandra's table will use exactly the same access pattern:
#   PARTITION KEY = (user_id, month)
#   CLUSTERING KEY = occurred_at
# but physically stores the rows contiguous on disk per partition,
# eliminating the B-tree traversal and random heap I/O.

Q6_SQL = """
SELECT
    e.id            AS event_id,
    e.event_type,
    e.occurred_at,
    e.product_id,
    e.session_id,
    e.metadata
FROM events e
WHERE e.user_id     = %s
  AND e.occurred_at >= %s
  AND e.occurred_at <  %s
ORDER BY e.occurred_at DESC;
"""

Q6_EXPLAIN_SQL = "EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)\n" + Q6_SQL

# -- helpers ------------------------------------------------------------------

def random_window():
    """
    Return a (window_start, window_end) pair drawn from a random date
    within the 2025 dataset range.
    """
    delta = (DATASET_END - DATASET_START).days
    start = DATASET_START + timedelta(days=random.randint(0, delta))
    end   = start + timedelta(days=WINDOW_DAYS)
    return start, end

# -- ID pool ------------------------------------------------------------------

def fetch_user_id_pool(conn, pool_size: int) -> list[str]:
    """
    Pre-fetch user IDs that have at least one event in the dataset.
    Sampling only active users ensures iterations return at least
    some rows — timing empty scans would not represent the hot path.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT user_id FROM (
                SELECT DISTINCT user_id FROM events
            ) AS active_users
            ORDER BY RANDOM()
            LIMIT %s;
            """,
            (pool_size,),
        )
        rows = cur.fetchall()

    if not rows:
        raise RuntimeError(
            "No events found in the database. "
            "Run the data loader before benchmarking."
        )

    ids = [str(row[0]) for row in rows]
    print(f"  Loaded pool of {len(ids)} user IDs with event history.")
    return ids

# -- benchmark factory --------------------------------------------------------

def make_query_fn(conn, user_ids: list[str]):
    """
    Return a zero-argument callable that fetches events for a randomly
    selected (user_id, 30-day window) pair on every call.
    Randomising both the user and the window avoids buffer cache bias
    from repeatedly scanning the same partition.
    """
    def _run():
        user_id = random.choice(user_ids)
        start, end = random_window()
        with conn.cursor() as cur:
            cur.execute(Q6_SQL, (user_id, start, end))
            cur.fetchall()
    return _run

# -- helper modes -------------------------------------------------------------

def dry_run(conn, user_ids: list[str]):
    """Fetch events for one user in one 30-day window and print the result."""
    user_id = user_ids[0]
    start, end = random_window()

    print(f"\n  DRY RUN -- Q6 events for user {user_id}")
    print(f"  Window: {start} to {end}\n")

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(Q6_SQL, (user_id, start, end))
        rows = cur.fetchall()

    if not rows:
        print("  No events found in this window for this user.")
        print("  Try --dry-run again -- a different random window may have results.")
        return

    print(f"  {len(rows)} event(s) returned:\n")
    print(
        f"  {'#':<4} {'Event type':<25} {'Occurred at':<28} "
        f"{'Product ID':<38} {'Session ID'}"
    )
    print(f"  {'─'*4} {'─'*25} {'─'*28} {'─'*38} {'─'*20}")
    for i, row in enumerate(rows[:20], 1):
        print(
            f"  {i:<4} {str(row['event_type']):<25} "
            f"{str(row['occurred_at']):<28} "
            f"{str(row['product_id'] or 'N/A'):<38} "
            f"{str(row['session_id'] or 'N/A')}"
        )
    if len(rows) > 20:
        print(f"  ... and {len(rows) - 20} more rows")


def explain(conn, user_ids: list[str]):
    """Print EXPLAIN ANALYZE for one event window scan."""
    user_id = user_ids[0]
    start, end = random_window()
    print(f"\n  EXPLAIN ANALYZE -- Q6 (user {user_id}, {start} to {end}):\n")
    with conn.cursor() as cur:
        cur.execute(Q6_EXPLAIN_SQL, (user_id, start, end))
        rows = cur.fetchall()
    for row in rows:
        print(" ", row[0])

# -- entry point --------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="PostgreSQL Q6 user events benchmark"
    )
    parser.add_argument(
        "--iterations", type=int, default=1000,
        help="Number of measured iterations (default: 1000)",
    )
    parser.add_argument(
        "--pool-size", type=int, default=1000, dest="pool_size",
        help="Number of user IDs to pre-fetch (default: 1000)",
    )
    parser.add_argument(
        "--explain", action="store_true",
        help="Print EXPLAIN ANALYZE output then exit (no benchmark run)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", dest="dry_run",
        help="Fetch events for one user in one window then exit",
    )
    parser.add_argument(
        "--output", type=str,
        default=os.path.join("results", "postgres_q6_baseline.json"),
        help="Path to save JSON results (default: results/postgres_q6_baseline.json)",
    )
    args = parser.parse_args()

    print("\n" + "=" * 50)
    print("  PostgreSQL -- Q6 User Events Benchmark")
    print("=" * 50)
    print(f"  Window size  : {WINDOW_DAYS} days")
    print(f"  Dataset range: {DATASET_START} to {DATASET_END + timedelta(days=WINDOW_DAYS)}")

    conn = get_connection()

    try:
        user_ids = fetch_user_id_pool(conn, args.pool_size)

        if args.explain:
            explain(conn, user_ids)
            return

        if args.dry_run:
            dry_run(conn, user_ids)
            return

        run_benchmark(
            query_fn=make_query_fn(conn, user_ids),
            db="postgres",
            query_id="Q6",
            label=(
                f"All events for a user in a {WINDOW_DAYS}-day window, ordered "
                "by occurred_at DESC. Composite index on (user_id, occurred_at). "
                "Random (user_id, window_start) pair per iteration to avoid "
                f"buffer cache bias. Pool of {args.pool_size} user IDs. "
                "Dataset fixed to 2025."
            ),
            iterations=args.iterations,
            concurrency=1,
            output_path=args.output,
        )

    finally:
        conn.close()


if __name__ == "__main__":
    main()