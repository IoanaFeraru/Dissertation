"""
benchmarks/postgres/q7_rolling_revenue.py — PostgreSQL Baseline: Q7
====================================================================
Q7: 7-day rolling average of daily revenue per subscription tier
    over a 6-month window, with gap-filling for days with zero activity.

    This is the PostgreSQL baseline for the TimescaleDB comparison (Q7).
    TimescaleDB will serve the same result using time_bucket_gapfill()
    targeting a pre-computed continuous aggregate.

Killer feature demonstrated (TimescaleDB side):
    time_bucket_gapfill() + continuous aggregates — TimescaleDB stores
    pre-aggregated daily revenue buckets as a materialised view that is
    incrementally refreshed. Gap-filling is a native operation. The
    rolling average reads from the aggregate, not the raw invoices table.
    PostgreSQL must scan raw invoices, aggregate by day, fill gaps with
    generate_series, then compute the rolling window — all at query time
    on every execution.

PostgreSQL baseline design notes
──────────────────────────────────
The query is built in four CTEs:

  1. date_spine
     Generates every calendar day in the 6-month window using
     generate_series. This is the gap-filling mechanism — days with
     no revenue will still appear in the output with 0.00 revenue,
     matching what time_bucket_gapfill() produces natively.

  2. tier_days
     Cross-joins date_spine with subscription_tiers so every
     (day, tier) combination exists, guaranteeing a complete grid
     before joining revenue data. Without this, tiers with zero
     revenue on a given day would be absent from the rolling average.

  3. daily_revenue
     Aggregates paid invoice totals by (day, tier) from raw invoices.
     Subscription invoices are attributed by their linked subscription
     tier. Marketplace invoices are attributed via LATERAL subquery
     to the user's most recent subscription at invoice time —
     consistent with the Q1 attribution logic.

  4. filled
     LEFT JOINs tier_days onto daily_revenue so every (day, tier)
     pair has a row, with 0.00 revenue for missing days.

The final SELECT computes the 7-day rolling average using a window
function: AVG(daily_total) OVER (PARTITION BY tier, 7 PRECEDING rows).

Since the dataset is fixed to 2025, the 6-month window is anchored
to a random start date within 2025 rather than NOW() - 6 months.
A random window is chosen per iteration to prevent plan cache bias.

Usage:
    python q7_rolling_revenue.py                   # 1000 iterations
    python q7_rolling_revenue.py --iterations 100  # quick smoke test
    python q7_rolling_revenue.py --explain         # EXPLAIN ANALYZE
    python q7_rolling_revenue.py --dry-run         # run once, print sample
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

# -- dataset date range -------------------------------------------------------

WINDOW_MONTHS = 6
WINDOW_DAYS   = 183          # ~6 months in days
DATASET_START = date(2025, 1, 1)
# Leave WINDOW_DAYS of headroom so window always falls within the data
DATASET_END   = date(2025, 12, 31) - timedelta(days=WINDOW_DAYS)

# -- connection ---------------------------------------------------------------

def get_connection():
    return psycopg2.connect(
        host="localhost",
        port=5432,
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
        dbname=os.getenv("POSTGRES_DB"),
    )

# -- query --------------------------------------------------------------------
#
# CTE breakdown
# -------------
#
#   1. date_spine
#      generate_series produces one row per calendar day in the window.
#      This is the PostgreSQL equivalent of TimescaleDB's time_bucket_gapfill()
#      gap-filling — every day exists regardless of whether revenue occurred.
#
#   2. tier_days
#      CROSS JOIN with subscription_tiers (3 rows) expands the spine to
#      one row per (day, tier) — 3 * WINDOW_DAYS rows total (~549 rows).
#      This ensures tiers with zero activity on a given day still appear
#      in the final output with 0.00, matching time_bucket_gapfill() output.
#
#   3. daily_revenue
#      Aggregates actual invoice totals per (day, tier).
#      Attribution logic mirrors Q1:
#        - subscription invoices: tier from subscription record
#        - marketplace invoices:  tier from LATERAL most-recent-subscription
#
#   4. filled
#      LEFT JOIN tier_days -> daily_revenue so every (day, tier) pair
#      has a row. COALESCE converts NULL revenue (missing days) to 0.00.
#
#   Final SELECT:
#      AVG() OVER with ROWS BETWEEN 6 PRECEDING AND CURRENT ROW computes
#      the 7-day rolling average within each tier partition, ordered by day.
#      TimescaleDB's equivalent is a window function over the continuous
#      aggregate — structurally identical but reading pre-computed buckets.

Q7_SQL = """
WITH date_spine AS (

    SELECT generate_series(
        %s::date,
        %s::date,
        '1 day'::interval
    )::date AS day

),

tier_days AS (

    -- Every (day, tier) combination — guarantees complete grid for gap-fill
    SELECT
        ds.day,
        st.id   AS tier_id,
        st.name AS tier_name
    FROM date_spine ds
    CROSS JOIN subscription_tiers st

),

daily_revenue AS (

    -- Subscription invoice revenue per day and tier
    SELECT
        DATE_TRUNC('day', i.created_at)::date AS day,
        sub.tier_id,
        SUM(i.total_usd)                       AS revenue
    FROM invoices i
    JOIN subscriptions sub ON sub.id = i.subscription_id
    WHERE i.invoice_type = 'subscription'
      AND i.status       = 'paid'
      AND i.created_at  >= %s::date
      AND i.created_at  <  (%s::date + INTERVAL '1 day')
    GROUP BY 1, 2

    UNION ALL

    -- Marketplace invoice revenue attributed to user's active tier at purchase
    SELECT
        DATE_TRUNC('day', i.created_at)::date AS day,
        active_sub.tier_id,
        SUM(i.total_usd)                       AS revenue
    FROM invoices i
    JOIN LATERAL (
        SELECT s.tier_id
        FROM   subscriptions s
        WHERE  s.user_id    = i.user_id
          AND  s.started_at <= i.created_at
        ORDER BY s.started_at DESC
        LIMIT 1
    ) active_sub ON TRUE
    WHERE i.invoice_type = 'marketplace'
      AND i.status       = 'paid'
      AND i.created_at  >= %s::date
      AND i.created_at  <  (%s::date + INTERVAL '1 day')
    GROUP BY 1, 2

),

filled AS (

    -- Gap-fill: LEFT JOIN ensures every (day, tier) row exists
    SELECT
        td.day,
        td.tier_id,
        td.tier_name,
        COALESCE(SUM(dr.revenue), 0.00) AS daily_total
    FROM tier_days td
    LEFT JOIN daily_revenue dr
        ON  dr.day     = td.day
        AND dr.tier_id = td.tier_id
    GROUP BY td.day, td.tier_id, td.tier_name

)

SELECT
    day,
    tier_name,
    ROUND(daily_total, 2)                        AS daily_revenue_usd,
    ROUND(
        AVG(daily_total) OVER (
            PARTITION BY tier_id
            ORDER BY day
            ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
        ),
        2
    )                                            AS rolling_7day_avg_usd
FROM filled
ORDER BY day, tier_name;
"""

Q7_EXPLAIN_SQL = "EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)\n" + Q7_SQL

# -- helpers ------------------------------------------------------------------

def random_window():
    """
    Return a (window_start, window_end) pair anchored to a random date
    within the 2025 dataset. The window is always WINDOW_DAYS long and
    always falls within the dataset boundaries.
    """
    delta = (DATASET_END - DATASET_START).days
    start = DATASET_START + timedelta(days=random.randint(0, delta))
    end   = start + timedelta(days=WINDOW_DAYS - 1)
    return start, end

def query_params(start: date, end: date) -> tuple:
    """
    Q7 references the window boundaries 3 times each in the SQL
    (date_spine + two UNION ALL branches). Returns the full params tuple.
    """
    return (start, end, start, end, start, end)

# -- benchmark factory --------------------------------------------------------

def make_query_fn(conn):
    """
    Return a zero-argument callable that executes Q7 over a randomly
    chosen 6-month window on every call. Randomising the window prevents
    the PostgreSQL plan cache from reusing identical parameter plans and
    prevents the OS page cache from serving the same invoice pages repeatedly.
    """
    def _run():
        start, end = random_window()
        with conn.cursor() as cur:
            cur.execute(Q7_SQL, query_params(start, end))
            cur.fetchall()
    return _run

# -- helper modes -------------------------------------------------------------

def dry_run(conn):
    """Execute Q7 for one window and print the first and last rows."""
    start, end = random_window()
    print(f"\n  DRY RUN -- Q7 rolling revenue")
    print(f"  Window: {start} to {end} ({WINDOW_DAYS} days)\n")

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(Q7_SQL, query_params(start, end))
        rows = cur.fetchall()

    if not rows:
        print("  No revenue data found in this window.")
        return

    total_rows = len(rows)
    print(f"  {total_rows} rows returned ({total_rows // 3} days x 3 tiers)\n")

    headers = ["day", "tier_name", "daily_revenue_usd", "rolling_7day_avg_usd"]
    col_w   = [12, 12, 20, 22]

    header_line = "  " + "  ".join(h.ljust(w) for h, w in zip(headers, col_w))
    sep_line    = "  " + "  ".join("─" * w for w in col_w)
    print(header_line)
    print(sep_line)

    # Print first 9 rows (3 days x 3 tiers) and last 9 rows
    sample = rows[:9]
    if total_rows > 18:
        sample += [None]   # sentinel for ellipsis
        sample += rows[-9:]

    for row in sample:
        if row is None:
            print(f"  {'...'}")
            continue
        print("  " + "  ".join(
            str(row[h]).ljust(w) for h, w in zip(headers, col_w)
        ))


def explain(conn):
    """Print EXPLAIN ANALYZE for one Q7 execution."""
    start, end = random_window()
    print(f"\n  EXPLAIN ANALYZE -- Q7 ({start} to {end}):\n")
    with conn.cursor() as cur:
        cur.execute(Q7_EXPLAIN_SQL, query_params(start, end))
        rows = cur.fetchall()
    for row in rows:
        print(" ", row[0])

# -- entry point --------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="PostgreSQL Q7 rolling revenue benchmark"
    )
    parser.add_argument(
        "--iterations", type=int, default=1000,
        help="Number of measured iterations (default: 1000)",
    )
    parser.add_argument(
        "--explain", action="store_true",
        help="Print EXPLAIN ANALYZE output then exit (no benchmark run)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", dest="dry_run",
        help="Execute once and print result sample then exit",
    )
    parser.add_argument(
        "--output", type=str,
        default=os.path.join("results", "postgres_q7_baseline.json"),
        help="Path to save JSON results (default: results/postgres_q7_baseline.json)",
    )
    args = parser.parse_args()

    print("\n" + "=" * 50)
    print("  PostgreSQL -- Q7 Rolling Revenue Benchmark")
    print("=" * 50)
    print(f"  Window size  : {WINDOW_DAYS} days (~{WINDOW_MONTHS} months)")
    print(f"  Dataset range: {DATASET_START} to {DATASET_END + timedelta(days=WINDOW_DAYS)}")

    conn = get_connection()

    try:
        if args.explain:
            explain(conn)
            return

        if args.dry_run:
            dry_run(conn)
            return

        run_benchmark(
            query_fn=make_query_fn(conn),
            db="postgres",
            query_id="Q7",
            label=(
                f"7-day rolling average of daily revenue per subscription tier "
                f"over a {WINDOW_DAYS}-day (~{WINDOW_MONTHS}-month) window with "
                "generate_series gap-filling. Subscription + marketplace revenue "
                "both included with temporal tier attribution (mirrors Q1 logic). "
                "Random window start per iteration to avoid plan/page cache bias. "
                "TimescaleDB baseline uses time_bucket_gapfill() on continuous aggregate."
            ),
            iterations=args.iterations,
            concurrency=1,
            output_path=args.output,
        )

    finally:
        conn.close()


if __name__ == "__main__":
    main()