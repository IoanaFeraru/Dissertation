# Dissertation TODO — Performance Gain of Using a Specialised Database

---

## The Queries

| # | Database | Query | What it uniquely demonstrates |
|---|---|---|---|
| Q1 | PostgreSQL | Monthly revenue report by subscription tier incl. marketplace purchases, last 12 months — temporal JOIN on pricing history | Multi-table temporal JOIN — relational elegance |
| Q2 | MongoDB | Fetch a complete invoice with customer info, all line items and product details in a single read | Embedded document model — zero JOINs |
| Q3 | Redis | Retrieve a user's active session and full cart contents under 50 concurrent requests | Single-key lookup under concurrency |
| Q4 | Neo4j | Given a product, find the top 10 recommendations based on co-purchase traversal | Graph traversal — structurally impossible to replicate efficiently in SQL |
| Q5 | Elasticsearch | Full-text product search with relevance ranking across name, description and attributes | BM25 ranking + custom analysers — PostgreSQL tsvector is the baseline |
| Q6 | Cassandra | Retrieve all activity events for a specific user in a 30-day window, ordered by time | Wide-row partition scan at 5M+ rows |
| Q7 | TimescaleDB | 7-day rolling average of daily revenue per subscription tier over 6 months, with gap-filling for days with zero activity | `time_bucket_gapfill()` — structurally impossible in plain PostgreSQL |

### Q8 — High-Volume Write Benchmark (all 7 DBs)

**Dissertation angle:** Does specialisation also confer a write advantage? Cassandra (LSM-tree) and TimescaleDB (chunk-partitioned inserts) are architecturally optimised for high-throughput writes — PostgreSQL is not. This is a direct, measurable claim.

| Dimension | Detail |
|---|---|
| Scenario | Insert 1M clickstream events with realistic payload into each DB |
| Measure | Throughput (ops/sec), write latency p95/p99, CPU and memory via Docker stats API |
| Databases | All 7 — compare each specialised DB’s write path against PostgreSQL |
| Implementation | Python `docker` SDK for resource stats; DB-native bulk APIs (`COPY`, `bulk_write`, `execute_concurrent`, ES bulk, Redis pipeline) |

---
## Phase 2 — PostgreSQL Baseline Queries `Week 4`

### Benchmarking Harness
- [ ] Write `benchmarks/harness.py`:
  - [ ] Runs a query function N times (default 1000)
  - [ ] Records latency per run in milliseconds
  - [ ] Computes p50, p95, p99
  - [ ] Supports concurrent execution via `threading`
  - [ ] Saves results to JSON with metadata (db, query_id, timestamp, concurrency)

### PostgreSQL Benchmark Queries (Q1–Q7)
- [ ] **Q1** Monthly revenue by subscription tier with temporal JOIN on pricing history, last 12 months
- [ ] **Q2** Fetch complete invoice (customer + all line items + product details) via 4-table JOIN
- [ ] **Q3** Retrieve active session + cart under 50 concurrent threads
- [ ] **Q4** Co-purchase recommendations via recursive CTE or multi-hop JOIN
- [ ] **Q5** Full-text product search using `tsvector` + `tsquery` with `ts_rank` scoring
- [ ] **Q6** Retrieve all events for a user in a 30-day window using composite index
- [ ] **Q7** 7-day rolling average of daily revenue with gap-filling using `generate_series`
- [ ] Run all 7 read baselines, 1000 iterations each, save to `results/postgres_q{1-7}_baseline.json`
- [ ] Sanity check results — flag anything abnormal

### PostgreSQL Write Baseline (Q8)
- [ ] **Q8** ~~Bulk-insert~~ 1M events into PostgreSQL ~~using `COPY` (the fastest available write path)~~ (maybe row by row concurent insert!)
  - [ ] Batch size: 10K rows per batch
  - [ ] Record total time, throughput (rows/sec), p95/p99 insert latency per batch
  - [ ] Record CPU and memory usage via Docker stats API (`docker stats dissertation_postgres`)
  - [ ] This is the baseline all specialised DBs are compared against
- [ ] Save to `results/postgres_q8_write_baseline.json`

---

## Phase 3 — Naive Specialised Implementations `Weeks 5–7`

> Port the schema to each specialised DB with minimal changes. No optimisation yet — just get the query running.

### MongoDB — Naive (Q2)
- [ ] Write `loaders/mongodb_naive_loader.py`
  - [ ] Import invoices as flat documents (same structure as SQL rows — no embedding yet)
  - [ ] Import invoice_lines as separate documents referencing invoice by ID
- [ ] Write `benchmarks/mongodb/naive_query.py`
  - [ ] Fetch invoice + lines using two separate queries (mimics SQL JOIN approach)
- [ ] Run 1000 iterations with harness
- [ ] Save to `results/mongodb_naive.json`

### Redis — Naive (Q3)
- [ ] Write `loaders/redis_naive_loader.py`
  - [ ] Serialize each session + cart as a single JSON string at key `session:{id}`
- [ ] Write `benchmarks/redis/naive_query.py`
  - [ ] `GET session:{id}` + deserialise JSON under 50 concurrent threads
- [ ] Run 1000 iterations
- [ ] Save to `results/redis_naive.json`

### Neo4j — Naive (Q4)
- [ ] Write `loaders/neo4j_naive_loader.py`
  - [ ] Create `User`, `Product` nodes with flat properties
  - [ ] Create `PURCHASED` relationships from order_items data
- [ ] Write `benchmarks/neo4j/naive_query.py`
  - [ ] Traverse `PURCHASED` edges naively: User→Product→User→Product (2-hop)
- [ ] Run 1000 iterations
- [ ] Save to `results/neo4j_naive.json`

### Elasticsearch — Naive (Q5)
- [ ] Write `loaders/elasticsearch_naive_loader.py`
  - [ ] Index products with default mapping (no custom analysers, no field weighting)
  - [ ] Index all fields as plain `text` type
- [ ] Write `benchmarks/elasticsearch/naive_query.py`
  - [ ] `multi_match` query across name, description, product_type with default scoring
- [ ] Run 1000 iterations
- [ ] Save to `results/elasticsearch_naive.json`

### Cassandra — Naive (Q6)
- [ ] Write `loaders/cassandra_naive_loader.py`
  - [ ] Create table with `user_id` as sole partition key (naive — mirrors SQL thinking)
- [ ] Write `benchmarks/cassandra/naive_query.py`
  - [ ] Time-range scan for user events using only `user_id` partition
- [ ] Run 1000 iterations
- [ ] Save to `results/cassandra_naive.json`

### TimescaleDB — Naive (Q7)
- [ ] Write `loaders/timescaledb_naive_loader.py`
  - [ ] Create hypertable on orders/invoices (same schema, just hypertable enabled — no aggregates)
- [ ] Write `benchmarks/timescaledb/naive_query.py`
  - [ ] Rolling average using plain SQL window functions on raw data (no `time_bucket_gapfill`)
- [ ] Run 1000 iterations
- [ ] Save to `results/timescaledb_naive.json`

### Q8 — Write Throughput, Naive (all specialised DBs)
> Naive = insert 1M events using the simplest available write method for each DB, no tuning.

- [ ] **MongoDB naive** — `insert_many()` in batches of 10K, no write concern tuning
  - [ ] Save to `results/mongodb_q8_naive.json`
- [ ] **Redis naive** — `SET event:{id} {json}` one key per event, no pipelining
  - [ ] Save to `results/redis_q8_naive.json`
- [ ] **Neo4j naive** — `CREATE (e:Event {...})` one Cypher statement per event
  - [ ] Save to `results/neo4j_q8_naive.json`
- [ ] **Elasticsearch naive** — single-document index calls, no bulk API
  - [ ] Save to `results/elasticsearch_q8_naive.json`
- [ ] **Cassandra naive** — `session.execute()` one INSERT per event, no `execute_concurrent`
  - [ ] Save to `results/cassandra_q8_naive.json`
- [ ] **TimescaleDB naive** — `INSERT INTO events VALUES (...)` row by row via psycopg2
  - [ ] Save to `results/timescaledb_q8_naive.json`
- [ ] Record throughput, p95/p99 latency per batch, CPU + memory for each
- [ ] Compare all against PostgreSQL `COPY` baseline from Phase 2

---

## Phase 4 — Optimised Specialised Implementations `Weeks 8–10`

> Redesign the schema for each DB the way a practitioner would. Document every decision.

### MongoDB — Optimised (Q2)
- [ ] Redesign schema:
  - [ ] Embed `invoice_lines` array directly inside the invoice document
  - [ ] Embed denormalised customer snapshot (name, email) inside invoice document
  - [ ] Embed product name + type snapshot inside each line item
  - [ ] Add index on `invoice_id`
- [ ] Write `loaders/mongodb_optimised_loader.py`
- [ ] Write `benchmarks/mongodb/optimised_query.py`
  - [ ] Single `find_one` by invoice ID — no secondary queries needed
- [ ] Document changes in `benchmarks/mongodb/CHANGES.md`
- [ ] Run 1000 iterations
- [ ] Save to `results/mongodb_optimised.json`

### Redis — Optimised (Q3)
- [ ] Redesign schema:
  - [ ] Store session metadata as Redis Hash (`HSET`) — separate fields, no JSON deserialisation
  - [ ] Store cart items as a Redis List or Hash of serialised items
  - [ ] Pipeline GET commands to reduce round trips
- [ ] Write `loaders/redis_optimised_loader.py`
- [ ] Write `benchmarks/redis/optimised_query.py`
- [ ] Document changes in `benchmarks/redis/CHANGES.md`
- [ ] Run 1000 iterations under 50 concurrent threads
- [ ] Save to `results/redis_optimised.json`

### Neo4j — Optimised (Q4)
- [ ] Redesign schema:
  - [ ] Pre-compute `ALSO_BOUGHT` relationships between products (weighted by co-purchase count)
  - [ ] Store co-purchase count and confidence score as relationship properties
- [ ] Write `loaders/neo4j_optimised_loader.py`
  - [ ] Include step that computes and creates `ALSO_BOUGHT` edges after loading
- [ ] Write `benchmarks/neo4j/optimised_query.py`
  - [ ] Single-hop traversal on precomputed `ALSO_BOUGHT` edges — no user traversal needed
- [ ] Document changes in `benchmarks/neo4j/CHANGES.md`
- [ ] Run 1000 iterations
- [ ] Save to `results/neo4j_optimised.json`

### Elasticsearch — Optimised (Q5)
- [ ] Redesign index mapping:
  - [ ] Custom analyser: English stemming + stop words + synonym expansion
  - [ ] Field-level boosting: `name^3`, `description^1.5`, `product_type^1`
  - [ ] Keyword sub-fields on `product_type` and `price_usd` for faceted filtering
  - [ ] Enable `norms` on name, disable on low-signal fields to save memory
- [ ] Write `loaders/elasticsearch_optimised_loader.py`
- [ ] Write `benchmarks/elasticsearch/optimised_query.py`
  - [ ] `multi_match` with `best_fields` + boosts + product_type filter
- [ ] Document changes in `benchmarks/elasticsearch/CHANGES.md`
- [ ] Run 1000 iterations
- [ ] Save to `results/elasticsearch_optimised.json`

### Cassandra — Optimised (Q6)
- [ ] Redesign schema:
  - [ ] Composite partition key `(user_id, month)` — avoids hot partitions
  - [ ] `occurred_at` as clustering column — enables efficient range scans
  - [ ] Denormalise event metadata into the same row
- [ ] Write `loaders/cassandra_optimised_loader.py`
- [ ] Write `benchmarks/cassandra/optimised_query.py`
- [ ] Document changes in `benchmarks/cassandra/CHANGES.md`
- [ ] Run 1000 iterations
- [ ] Save to `results/cassandra_optimised.json`

### TimescaleDB — Optimised (Q7)
- [ ] Redesign schema:
  - [ ] Create continuous aggregate for daily revenue per tier
  - [ ] Rewrite query using `time_bucket_gapfill()` targeting the aggregate
  - [ ] Enable compression on chunks older than 7 days
  - [ ] Add retention policy (demonstrates time-series-native feature set)
- [ ] Write `loaders/timescaledb_optimised_loader.py`
- [ ] Write `benchmarks/timescaledb/optimised_query.py`
- [ ] Document changes in `benchmarks/timescaledb/CHANGES.md`
- [ ] Run 1000 iterations
- [ ] Save to `results/timescaledb_optimised.json`

### Q8 — Write Throughput, Optimised (all specialised DBs)
> Optimised = use each DB's best available bulk write mechanism with appropriate tuning.

- [ ] **MongoDB optimised** — `bulk_write()` with `ordered=False`, `w=1` write concern
  - [ ] Save to `results/mongodb_q8_optimised.json`
- [ ] **Redis optimised** — `pipeline()` batching 1000 commands per flush
  - [ ] Save to `results/redis_q8_optimised.json`
- [ ] **Neo4j optimised** — `UNWIND` batch Cypher: `UNWIND $rows AS row CREATE (e:Event {row})`
  - [ ] Save to `results/neo4j_q8_optimised.json`
- [ ] **Elasticsearch optimised** — bulk API with batches of 5K documents
  - [ ] Save to `results/elasticsearch_q8_optimised.json`
- [ ] **Cassandra optimised** — `execute_concurrent()` with `concurrency=50`, prepared statements
  - [ ] Save to `results/cassandra_q8_optimised.json`
- [ ] **TimescaleDB optimised** — `COPY` via psycopg2 with chunk-aware batch ordering
  - [ ] Save to `results/timescaledb_q8_optimised.json`
- [ ] Document write optimisation decisions in each DB's `CHANGES.md`
- [ ] Record throughput, p95/p99 latency per batch, CPU + memory for each

---

## Phase 5 — Analysis & Visualisation `Week 11`

### Result Aggregation
- [ ] Write `analysis/load_results.py`
  - [ ] Reads all JSON files from `results/`
  - [ ] Normalises into a single Pandas DataFrame
  - [ ] Exports to `results/all_results.csv`

### Charts
- [ ] **Chart 1 — Per-database 3-way comparison** (one per specialised DB)
  - [ ] Bar chart: PostgreSQL Baseline vs Naive vs Optimised
  - [ ] Show p50 and p95 side by side
  - [ ] Export as `analysis/charts/comparison_{dbname}.png`
- [ ] **Chart 2 — Cross-database read overview**
  - [ ] All optimised specialised DBs vs PostgreSQL baseline for Q1–Q7
  - [ ] One chart, all 6 specialised use cases
  - [ ] Export as `analysis/charts/cross_db_read_overview.png`
- [ ] **Chart 2b — Write throughput comparison (Q8)**
  - [ ] Bar chart: rows/sec for PostgreSQL COPY vs each specialised DB (naive and optimised)
  - [ ] Secondary axis: p99 write latency
  - [ ] Export as `analysis/charts/write_throughput_q8.png`
- [ ] **Chart 3 — Scalability curves**
  - [ ] Latency at 10K / 100K / 500K rows for each DB
  - [ ] Export as `analysis/charts/scalability_{dbname}.png`
- [ ] **Chart 4 — Throughput under concurrency**
  - [ ] Queries/sec at 1, 10, 50, 100 concurrent clients (Redis + Elasticsearch focus)
  - [ ] Export as `analysis/charts/throughput.png`
- [ ] **Chart 5 — Engine vs Schema gain breakdown**
  - [ ] Stacked bar: how much gain from engine alone (naive) vs schema optimisation (optimised)
  - [ ] Export as `analysis/charts/gain_breakdown.png`

### Summary Table
- [ ] Write `analysis/summary_table.py`
  - [ ] Read table (Q1–Q7): DB × (p50 baseline, p50 naive, p50 optimised, speedup naive, speedup optimised)
  - [ ] Write table (Q8): DB × (rows/sec naive, rows/sec optimised, p99 latency naive, p99 latency optimised, speedup vs PostgreSQL COPY)
  - [ ] Export as `results/summary_table_reads.csv`, `results/summary_table_writes.csv`, and combined `results/summary_table.md`
- [ ] Sanity-check every number — re-run any benchmark that looks suspicious

## Phase 6 — Writing `Weeks 12–14`

### Methodology and Tools (write first)
- [ ] Unified schema rationale and StreamCart domain justification
- [ ] Dataset generation logic and reproducibility (fixed seed)
- [ ] Benchmark harness design (p50/p95/p99, threading, warm-up)
- [ ] PostgreSQL baseline design and query implementations
- [ ] Naïve specialised schema per DB — design decisions
- [ ] Optimised specialised schema per DB — design decisions and justifications
- [ ] Experimental setup (hardware specs, Docker config, concurrency settings)

### Results and Discussion (write second)
- [ ] Benchmark results per DB with charts
- [ ] Analysis: what do the numbers mean, where does the gain come from
- [ ] Cross-DB comparison chart and interpretation
- [ ] Statistical tests on latency distributions (Mann-Whitney U or t-test)

### Literature Review
- [x] Why relational databases became the default
- [ ] Why specialised databases emerged
- [ ] How data modelling affects performance
- [ ] How workload alignment affects performance
- [ ] Why existing benchmarks don't isolate modelling vs engine effects
- [ ] The research gap — lack of controlled unified-schema comparisons
- [ ] Benchmarking methodology: YCSB, TPC-C, LinkBench — design and limitations
- [ ] Percentile metrics (p50, p95, p99), concurrency testing, synthetic datasets
- [ ] Minimum 25–35 academic and industry sources, APA citation style

### Introduction
- [ ] Background and practical relevance
- [ ] Problem statement — default reliance on PostgreSQL
- [ ] 3–4 clear and measurable research questions
- [ ] Scope and limitations (single-node Docker, synthetic data, 7 DB types)
- [ ] Dissertation structure overview

### Conclusions
- [ ] Summary of key findings per DB type
- [ ] Answer to each research question
- [ ] Limitations and threats to validity
- [ ] Future work suggestions

### Abstract
- [ ] Write last — one paragraph, max 300 words
- [ ] Cover: problem, method, key findings, conclusion

---

## Phase 7 — Review & Polish `Week 15`

### Dissertation Review
- [ ] Read the full dissertation once for flow and logical consistency
- [ ] Verify every chart is referenced and explained in the text
- [ ] Verify every claim is backed by a result or a citation
- [ ] Check chapter transitions
- [ ] Proofread for grammar and language

### Bibliography
- [ ] All sources cited in-text
- [ ] Bibliography formatted consistently (APA)
- [ ] Count sources — aim for 25–35 minimum

### Code & Reproducibility
- [ ] Clean up the Git repository — remove debug code and temporary files
- [ ] Verify `run_all.py` works from a clean clone
- [ ] Write `README.md` with setup and run instructions
- [ ] Document the fixed random seed for reproducibility

---

## Progress Tracker

| Phase | Status | Date Target | Completed  |
|---|---|-------------|------------|
| 0 — Environment Setup | ✅ Complete | -           | 2026-02-20 |
| 1 — Schema & Data Generation | ✅ Complete | -           | 2026-02-24 |
| 2 — PostgreSQL Baselines | ⬜ Not started | 2026-02-28  | -          |
| 3 — Naive Specialised | ⬜ Not started | 2026-03-06  | -          |
| 4 — Optimised Specialised | ⬜ Not started | 2026-03-18  | -          |
| 5 — Analysis & Visualisation | ⬜ Not started | 2026-04-01  | -          |
| 6 — Writing | ⬜ Not started | 2026-04-20  | -          |
| 7 — Review & Polish | ⬜ Not started | 2026-05-01  | -          |

---