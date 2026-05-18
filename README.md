# Database Benchmark Suite

**Performance Gain of Using a Specialised Database:** Master's dissertation benchmarking framework comparing PostgreSQL against five specialised databases across a synthetic e-commerce scenario of ~9.8 million records.

---

## Overview

This repository contains the complete benchmarking infrastructure built for my master's dissertation.

The original contribution is the **two-factor decomposition of database performance** into:

- **Engine effect** — the raw performance difference between a specialised database and PostgreSQL when both use a naïve, flat schema that mirrors the relational baseline.
- **Schema effect** — the additional gain unlocked by redesigning the schema idiomatically for each engine (embedded documents, wide-row partitions, precomputed graph edges, continuous aggregates, etc.).

---

## Databases Compared

| Database | Specialisation |
|---|---|
| **PostgreSQL** | Relational baseline |
| **MongoDB** | Document store |
| **Apache Cassandra** | Wide-column store |
| **Neo4j** | Graph database |
| **Elasticsearch** | Search engine |
| **TimescaleDB** | Time-series (PostgreSQL ext.) |

---

## Benchmark Queries

Seven read queries and one concurrent write benchmark are run at three implementation levels per database: **Relational Baseline**, **Naïve Specialised**, and **Optimised Specialised**.

| Query | Description | Concurrency |
|---|---|---|
| Q1 | Monthly revenue by subscription tier — temporal JOIN on pricing history | 1 |
| Q2 | Full invoice fetch: header + customer snapshot + all line items + products | 1 |
| Q3 | Active session + cart retrieval | 50 threads |
| Q4 | Top-10 co-purchase recommendations | 1 |
| Q5 | Full-text product search with relevance ranking | 1 |
| Q6 | All user events in a 30-day window, ordered by time | 1 |
| Q7 | 7-day rolling revenue average per tier with gap-filling (6-month window) | 1 |
| Q8 | 1 million concurrent single-event inserts | 100 threads |

Q8 runs at a single level per database — micro-batching is an application-level decision, not a schema effect, so it is deliberately excluded from the naive/optimised split.

A **scalability experiment** re-runs Q1–Q7 at 10% and 50% data scale (date-range cutoff) to characterise how each engine's advantage changes with data volume.

---

## Dataset

The synthetic e-commerce platform was generated at approximately **9.8 million records** across 14 tables/collections/node types:

- Users, subscriptions, subscription tiers, subscription tier pricing
- Products, orders, order items
- Invoices, invoice lines
- Sessions (with cart contents)
- Events (user activity)

The dataset spans two years of synthetic transactional and behavioural data, seeded deterministically for reproducibility.

---

## Technical Stack

**Infrastructure**
- Docker Compose — one container per database, isolated environments
- Python 3.11

**Drivers**
- `psycopg2` — PostgreSQL & TimescaleDB
- `pymongo` — MongoDB
- `cassandra-driver` — Apache Cassandra
- `neo4j` Python driver — Neo4j
- `elasticsearch-py` (`>=8,<9`) — Elasticsearch

**Benchmarking**
- Custom `harness.py` — configurable iteration count, warmup runs, concurrency via `threading.Barrier`, JSON output with full raw timing distributions
- Statistical analysis: Welch's t-test (α = 0.05) + Cliff's delta effect size
- Per-query result files (`db_schema_Qn.json`) storing p50/p95/p99, mean ± std dev, min/max, and the complete raw timing array

---

## Repository Structure

```
benchmarks/
├── harness.py                 
├── postgres/ 
├── mongodb/
│   ├── naive/                  # Flat collections mirroring PG schema
│   └── optimised/              # Embedded documents, multikey indexes
├── cassandra/
│   ├── naive/                  # id-only partition keys, ALLOW FILTERING
│   └── optimised/              # Idiomatic wide-row partition design
├── neo4j/
│   ├── naive/                  # Node/relationship mirror of PG schema
│   └── optimised/              # Precomputed ALSO_BOUGHT edges, full-text index
├── elasticsearch/
│   ├── naive/                  # Flat indices, default BM25
│   └── optimised/              # Field boosts, custom English analyser, extended_bounds
└── timescaleDB/
    ├── naive/                  # Hypertable with 7-day chunks
    └── optimised/              # 1-month chunks, compression, continuous aggregate
```

---

## Key Design Decisions

**Anchor-based query pools** — Q6 samples `(user_id, occurred_at)` pairs directly from the events table and centres each 30-day window on the anchor event, guaranteeing every iteration returns real results rather than empty scans from sparse user histories.

**Cassandra Q6** — ALLOW FILTERING with a WHERE predicate causes a server-side ReadTimeout at ~1 million rows regardless of timeout configuration. The naive implementation uses a paginated full-table scan instead, chunked into 10,000-row pages to avoid coordinator blocking. Documented as a finding rather than silently worked around.

**Q7 consistency** — Neo4j lacks `generate_series` and window functions. Its Q7 measures the closest honest equivalent (daily aggregation only) and the structural limitation is documented in results.

**Q8 single level** — the concurrent write benchmark is not split into naive/optimised because micro-batching is an application-level pattern change that would muddy the engine-vs-schema decomposition.

---

## Running the Benchmarks

```bash
# Start all database containers
docker-compose up -d

# Verify connectivity
python setup.py --wait

# Run PostgreSQL baseline (example)
cd benchmarks/postgres
python q1_revenue.py --iterations 1000

# Run a dry-run to validate output before a full benchmark
python q6_events.py --dry-run

# Run scalability baselines
python run_scalability.py --scale 10 --iterations 1000
```

Each benchmark script accepts `--iterations`, `--dry-run`, and `--output` flags. Results are saved as JSON to `benchmarks/<db>/<schema>/results/`.
