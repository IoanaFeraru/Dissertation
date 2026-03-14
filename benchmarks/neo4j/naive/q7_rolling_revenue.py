"""
benchmarks/neo4j/naive/q7_rolling_revenue.py — Neo4j Naive: Q7
===============================================================
Q7: Daily revenue per subscription tier over a 6-month window.

Neo4j cannot natively replicate the full PostgreSQL Q7 query.
The missing capabilities are:

  - No generate_series / gap-filling primitive: PostgreSQL fills
    missing days with zero revenue via generate_series + LEFT JOIN.
    Neo4j has no equivalent — days with no invoices simply do not
    appear in the result.

  - No window functions: PostgreSQL computes the 7-day rolling
    average server-side via AVG() OVER (ROWS BETWEEN 6 PRECEDING
    AND CURRENT ROW). Neo4j has no OVER / window function support.

Implementing these in Python would benchmark Python+Neo4j, not
Neo4j. That would invalidate the comparison against PostgreSQL,
which does both operations server-side. Q7 is therefore benchmarked
as the closest honest equivalent Neo4j can execute natively:

    Aggregate daily invoice revenue by tier within the window.

This is what Neo4j measures. The gap-filling and rolling average
are acknowledged as structural limitations and documented in the
methodology chapter. The result set is smaller than PostgreSQL's
(no zero-revenue days, no rolling column) — latency differences
partly reflect this reduced output, which is itself a consequence
of Neo4j's missing primitives.

No schema effect vs optimised — both schemas have the same invoice
traversal. Engine effect only.

Usage:
    python q7_rolling_revenue.py
    python q7_rolling_revenue.py --iterations 100
    python q7_rolling_revenue.py --dry-run
"""

import argparse
import os
import random
import sys
from datetime import date, timedelta

from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
from benchmarks.harness import run_benchmark
from benchmarks.neo4j.neo4j_conn import get_driver

load_dotenv()

WINDOW_DAYS = 183   # ~6 months

# ── Cypher ────────────────────────────────────────────────────────────────────
# Aggregates daily revenue by (day, tier) within the window.
# No gap-filling, no rolling average — not available in Neo4j.

Q7_SUBSCRIPTION_CYPHER = """
MATCH (i:Invoice)-[:FOR_SUBSCRIPTION]->(s:Subscription)-[:ON_TIER]->(t:SubscriptionTier)
WHERE i.status       = 'paid'
  AND i.invoice_type = 'subscription'
  AND i.created_at  >= $start
  AND i.created_at  <  $end
RETURN
    substring(i.created_at, 0, 10) AS day,
    t.name                          AS tier_name,
    sum(toFloat(i.total_usd))       AS daily_revenue_usd
ORDER BY day, tier_name
"""

Q7_MARKETPLACE_CYPHER = """
MATCH (u:User)-[:HAS_INVOICE]->(i:Invoice)
WHERE i.status       = 'paid'
  AND i.invoice_type = 'marketplace'
  AND i.created_at  >= $start
  AND i.created_at  <  $end
MATCH (u)-[:HAS_SUBSCRIPTION]->(s:Subscription)
WHERE s.started_at <= i.created_at
WITH i, s
ORDER BY s.started_at DESC
WITH i, head(collect(s)) AS active_sub
WHERE active_sub IS NOT NULL
MATCH (t:SubscriptionTier {id: active_sub.tier_id})
RETURN
    substring(i.created_at, 0, 10) AS day,
    t.name                          AS tier_name,
    sum(toFloat(i.total_usd))       AS daily_revenue_usd
ORDER BY day, tier_name
"""

# ── date range loader ─────────────────────────────────────────────────────────

def load_data_date_range(driver) -> tuple[date, date]:
    cypher = """
    MATCH (i:Invoice)
    WHERE i.status = 'paid'
    RETURN min(i.created_at) AS min_dt, max(i.created_at) AS max_dt
    """
    with driver.session() as session:
        row = session.run(cypher).single()
    if not row or not row["min_dt"]:
        raise RuntimeError("No paid invoices found — run the loader first.")
    return date.fromisoformat(row["min_dt"][:10]), date.fromisoformat(row["max_dt"][:10])


def random_window(data_min: date, data_max: date) -> tuple[str, str]:
    max_start = max(0, (data_max - data_min).days - WINDOW_DAYS)
    start     = data_min + timedelta(days=random.randint(0, max_start))
    end       = start + timedelta(days=WINDOW_DAYS - 1)
    return start.isoformat(), (end + timedelta(days=1)).isoformat()


# ── query function ────────────────────────────────────────────────────────────

def make_query_fn(driver, data_min: date, data_max: date):
    def _run():
        start, end = random_window(data_min, data_max)
        with driver.session() as session:
            session.run(Q7_SUBSCRIPTION_CYPHER, start=start, end=end).data()
            session.run(Q7_MARKETPLACE_CYPHER,  start=start, end=end).data()
    return _run


# ── dry run ───────────────────────────────────────────────────────────────────

def dry_run(driver, data_min: date, data_max: date):
    start, end = random_window(data_min, data_max)
    print(f"\n  DRY RUN — Neo4j Naive Q7")
    print(f"  Window: {start} to {end} ({WINDOW_DAYS} days)")
    print(f"  Note: no gap-filling or rolling average — Neo4j limitation\n")

    with driver.session() as session:
        sub_rows = session.run(Q7_SUBSCRIPTION_CYPHER, start=start, end=end).data()
        mkt_rows = session.run(Q7_MARKETPLACE_CYPHER,  start=start, end=end).data()

    print(f"  Subscription rows: {len(sub_rows)}  |  Marketplace rows: {len(mkt_rows)}\n")
    rows = sub_rows[:10]
    if not rows:
        print("  ⚠  No rows returned.")
        return

    print(f"  {'Day':<12} {'Tier':<12} {'Daily revenue':>15}")
    print(f"  {'─'*12} {'─'*12} {'─'*15}")
    for row in rows:
        print(
            f"  {str(row['day']):<12} "
            f"{str(row['tier_name']):<12} "
            f"{str(round(row['daily_revenue_usd'], 2)):>15}"
        )


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Neo4j Naive Q7 benchmark")
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--dry-run", action="store_true", dest="dry_run")
    parser.add_argument(
        "--output", type=str,
        default=os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "results",
            "neo4j_naive_Q7.json",
        ),
    )
    args = parser.parse_args()

    print("\n" + "=" * 55)
    print("  Neo4j Naive — Q7 Daily Revenue Benchmark")
    print("=" * 55)
    print(f"  Window size : {WINDOW_DAYS} days (~6 months)")
    print(f"  Limitation  : no gap-filling or rolling average (Neo4j)")

    driver = get_driver(port=int(os.getenv("NEO4J_NAIVE_PORT", 7687)))

    try:
        data_min, data_max = load_data_date_range(driver)
        print(f"  Invoice range: {data_min} → {data_max}")

        if args.dry_run:
            dry_run(driver, data_min, data_max)
            return

        run_benchmark(
            query_fn=make_query_fn(driver, data_min, data_max),
            db="neo4j_naive",
            query_id="Q7",
            label=(
                f"Daily revenue aggregated by tier over {WINDOW_DAYS} days. "
                "Partial Q7 equivalent — Neo4j does not support generate_series "
                "(gap-filling) or window functions (rolling average). "
                "Benchmarks the Cypher aggregation only. "
                "No schema effect vs optimised — engine effect only."
            ),
            iterations=args.iterations,
            concurrency=1,
            output_path=args.output,
        )
    finally:
        driver.close()


if __name__ == "__main__":
    main()