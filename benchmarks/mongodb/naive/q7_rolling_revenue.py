"""
benchmarks/mongodb/naive/q7_rolling_revenue.py — MongoDB Naive: Q7
===================================================================
Q7: 7-day rolling average of daily revenue per subscription tier
    over a 6-month window, with gap-filling for days with zero activity.

Naive implementation notes:
    All collections are flat mirrors of the PostgreSQL schema — no
    pre-computed aggregates, no continuous aggregate views.

    The implementation requires:
      1. Fetch paid invoices in the 6-month window  [timed]
      2. Resolve tier_id per invoice (same logic as Q1)
      3. Aggregate revenue by (day, tier_id) in Python
      4. Build a complete date × tier grid (gap-filling in Python)
      5. Compute 7-day rolling average in Python using a sliding window

    Steps 2–5 are equivalent to PostgreSQL's four CTEs (date_spine,
    tier_days, daily_revenue, filled) plus the window function —
    all executed at query time in Python rather than inside the engine.

    Subscriptions, tiers, and pricing are pre-loaded once before the
    benchmark loop (same pattern as Q1) — only the invoice fetch and
    aggregation logic are timed per iteration.

    The same random window logic as the PostgreSQL baseline is used:
      - Dataset fixed to 2025
      - Window start drawn randomly from 2025-01-01 to 2025-06-30
      - Window is always WINDOW_DAYS (183) long

Academic context:
    Engine effect = naive MongoDB result minus PostgreSQL baseline.
    Schema effect = optimised MongoDB result minus naive result.
    This file measures the naive (engine-only) side.

Usage:
    cd benchmarks/mongodb/naive
    python q7_rolling_revenue.py                   # 1000 iterations
    python q7_rolling_revenue.py --iterations 100  # quick smoke test
    python q7_rolling_revenue.py --dry-run         # run once, print sample
"""

import argparse
import os
import random
import sys
from collections import defaultdict
from datetime import date, timedelta, datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
from benchmarks.harness import run_benchmark
from benchmarks.mongodb.mongo_conn import get_db

# ── dataset date range (mirrors PostgreSQL baseline exactly) ──────────────────

WINDOW_DAYS   = 183
DATASET_START = date(2024, 1, 1)
DATASET_END   = date(2025, 12, 31) - timedelta(days=WINDOW_DAYS)

# ── date helpers ──────────────────────────────────────────────────────────────

def random_window() -> tuple[str, str, date, date]:
    """
    Return (iso_start, iso_end, date_start, date_end) for a random window.
    iso strings match the format stored in the naive collection.
    date objects are used for gap-filling grid construction.
    """
    delta = (DATASET_END - DATASET_START).days
    start = DATASET_START + timedelta(days=random.randint(0, delta))
    end   = start + timedelta(days=WINDOW_DAYS - 1)
    iso_start = datetime(start.year, start.month, start.day,
                         tzinfo=timezone.utc).isoformat()
    iso_end   = datetime(end.year, end.month, end.day, 23, 59, 59,
                         tzinfo=timezone.utc).isoformat()
    return iso_start, iso_end, start, end


def parse_dt(s: str) -> datetime:
    if not s:
        return datetime.min.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(s.strip().replace("Z", "+00:00"))


def date_of(s: str) -> date:
    return parse_dt(s).date()

# ── one-time reference data loaders ──────────────────────────────────────────

def load_subs_by_id(db) -> dict:
    docs = db["subscriptions"].find(
        {}, {"_id": 1, "tier_id": 1, "user_id": 1, "started_at": 1}
    )
    return {d["_id"]: d for d in docs}


def load_subs_by_user(db) -> dict:
    docs = db["subscriptions"].find(
        {}, {"_id": 1, "tier_id": 1, "user_id": 1, "started_at": 1}
    )
    by_user = defaultdict(list)
    for d in docs:
        by_user[d["user_id"]].append(d)
    for uid in by_user:
        by_user[uid].sort(key=lambda s: s["started_at"], reverse=True)
    return dict(by_user)


def load_tiers(db) -> dict:
    return {d["_id"]: d["name"]
            for d in db["subscription_tiers"].find({}, {"_id": 1, "name": 1})}

# ── core Q7 logic (timed portion) ─────────────────────────────────────────────

def run_q7(db, subs_by_id: dict, subs_by_user: dict,
           tiers: dict) -> list[dict]:
    """
    Fetch invoices in a random 6-month window and compute a 7-day rolling
    revenue average per subscription tier with Python-side gap-filling.

    Returns rows matching the PostgreSQL Q7 output format:
        [{day, tier_name, daily_revenue_usd, rolling_7day_avg_usd}]
    """
    iso_start, iso_end, date_start, date_end = random_window()

    # ── timed step 1: fetch paid invoices in window ───────────────────────
    invoices = list(db["invoices"].find(
        {
            "status":     "paid",
            "created_at": {"$gte": iso_start, "$lte": iso_end},
        },
        {
            "_id": 1, "user_id": 1, "invoice_type": 1,
            "total_usd": 1, "created_at": 1, "subscription_id": 1,
        }
    ))

    # ── timed step 2: resolve tier and aggregate by (day, tier) ──────────
    daily: dict[tuple, float] = defaultdict(float)

    for inv in invoices:
        inv_dt   = parse_dt(inv["created_at"])
        inv_type = inv.get("invoice_type", "")
        tier_id  = None

        if inv_type == "subscription":
            sub = subs_by_id.get(inv.get("subscription_id", ""))
            if sub:
                tier_id = sub["tier_id"]
        elif inv_type == "marketplace":
            for sub in subs_by_user.get(inv.get("user_id", ""), []):
                if parse_dt(sub["started_at"]) <= inv_dt:
                    tier_id = sub["tier_id"]
                    break

        if tier_id is None:
            continue

        day_key = inv_dt.date()
        daily[(day_key, tier_id)] += float(inv.get("total_usd", 0))

    # ── timed step 3: build complete (day × tier) grid with gap-filling ───
    all_days   = [date_start + timedelta(days=i)
                  for i in range((date_end - date_start).days + 1)]
    tier_ids   = list(tiers.keys())

    grid: dict[tuple, float] = {}
    for d in all_days:
        for tid in tier_ids:
            grid[(d, tid)] = daily.get((d, tid), 0.0)

    # ── timed step 4: compute 7-day rolling average per tier ──────────────
    rows = []
    for tid in tier_ids:
        tier_series = [(d, grid[(d, tid)]) for d in all_days]
        for i, (d, rev) in enumerate(tier_series):
            window = [tier_series[j][1]
                      for j in range(max(0, i - 6), i + 1)]
            rolling_avg = sum(window) / len(window)
            rows.append({
                "day":                  d.isoformat(),
                "tier_name":            tiers[tid],
                "daily_revenue_usd":    round(rev, 2),
                "rolling_7day_avg_usd": round(rolling_avg, 2),
            })

    rows.sort(key=lambda r: (r["day"], r["tier_name"]))
    return rows

# ── benchmark factory ─────────────────────────────────────────────────────────

def make_query_fn(db, subs_by_id, subs_by_user, tiers):
    def _run():
        run_q7(db, subs_by_id, subs_by_user, tiers)
    return _run

# ── dry run ───────────────────────────────────────────────────────────────────

def dry_run(db, subs_by_id, subs_by_user, tiers):
    print("\n  DRY RUN — MongoDB Naive Q7 rolling revenue sample:\n")
    rows = run_q7(db, subs_by_id, subs_by_user, tiers)
    if not rows:
        print("  ⚠  No rows returned — is the database populated?")
        return
    total = len(rows)
    print(f"  {total} rows returned ({total // 3} days × 3 tiers)\n")
    headers = ["day", "tier_name", "daily_revenue_usd", "rolling_7day_avg_usd"]
    col_w   = [12, 12, 20, 22]
    print("  " + "  ".join(h.ljust(w) for h, w in zip(headers, col_w)))
    print("  " + "  ".join("─" * w for w in col_w))
    sample = rows[:9]
    if total > 18:
        sample += [None]
        sample += rows[-9:]
    for row in sample:
        if row is None:
            print("  ...")
            continue
        print("  " + "  ".join(
            str(row[h]).ljust(w) for h, w in zip(headers, col_w)
        ))

# ── entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="MongoDB Naive Q7 — rolling revenue benchmark"
    )
    parser.add_argument(
        "--iterations", type=int, default=1000,
        help="Number of measured iterations (default: 1000)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", dest="dry_run",
        help="Execute once and print result sample then exit",
    )
    parser.add_argument(
        "--output", type=str,
        default=os.path.join("results", "mongodb_naive_Q7.json"),
        help="Path to save JSON results (default: results/mongodb_naive_Q7.json)",
    )
    args = parser.parse_args()

    print("\n" + "=" * 55)
    print("  MongoDB Naive — Q7 Rolling Revenue Benchmark")
    print("=" * 55)
    print(f"  Window size  : {WINDOW_DAYS} days (~6 months)")
    print(f"  Dataset range: {DATASET_START} to "
          f"{DATASET_END + timedelta(days=WINDOW_DAYS)}")

    db = get_db()

    print("  Pre-loading reference data (subscriptions, tiers)...")
    subs_by_id   = load_subs_by_id(db)
    subs_by_user = load_subs_by_user(db)
    tiers        = load_tiers(db)
    print(f"  Loaded {len(subs_by_id):,} subscriptions, {len(tiers)} tiers.\n")

    if args.dry_run:
        dry_run(db, subs_by_id, subs_by_user, tiers)
        return

    run_benchmark(
        query_fn=make_query_fn(db, subs_by_id, subs_by_user, tiers),
        db="mongodb_naive",
        query_id="Q7",
        label=(
            f"7-day rolling average of daily revenue per subscription tier "
            f"over a {WINDOW_DAYS}-day (~6-month) window. Naive: invoice fetch "
            "from MongoDB + Python-side tier attribution, gap-filling, and "
            "rolling window computation. No pre-computed aggregates. "
            "Pre-loaded subscriptions and tiers; random window per iteration."
        ),
        iterations=args.iterations,
        concurrency=1,
        output_path=args.output,
    )


if __name__ == "__main__":
    main()