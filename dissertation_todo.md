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

### Q8 — Concurrent Event Ingestion Benchmark (all 7 DBs)

**Dissertation angle:** Does specialisation confer a write advantage under realistic production conditions? In production, events are written the moment they occur — one user action, one insert — across many concurrent users. Nobody accumulates 1M events and bulk-loads them. This benchmark simulates that real workload.

| Dimension | Detail |
|---|---|
| Scenario | 100 concurrent threads each inserting individual events as fast as possible, sustained until 1M total events are written |
| Measure | Throughput (events/sec), write latency p95/p99 per insert, CPU and memory via Docker stats API |
| Databases | All 7 — PostgreSQL is the baseline, all specialised DBs compared against it |
| Implementation | Python `threading.Thread` pool (100 workers); each thread loops inserting single events; latency recorded per insert; `docker` SDK for resource stats |

**Three-level comparison:**

| Level | Pattern | Rationale |
|---|---|---|
| PostgreSQL baseline | 100 threads, single `INSERT` per event | Realistic production pattern — this is what applications actually do |
| Specialised DB naive | 100 threads, single insert call per event, no tuning | Same pattern, different engine — isolates engine difference |
| Specialised DB optimised | 100 threads, micro-batch of 50 events per flush | Realistic session-end buffer flush — a common production optimisation |

> **Why not `COPY`?** `COPY` is a bulk data loading tool, not an application write pattern. No production system accumulates millions of events then batch-loads them via `COPY`. Benchmarking it would measure a data migration tool, not a database engine's write path. The concurrent single-insert pattern is what an event-driven application actually produces.

---

## Phase 2 — PostgreSQL Baseline Queries `Week 4`

### PostgreSQL Benchmark Queries (Q1–Q7)
- [ ] Run all 7 read baselines, 1000 iterations each, save to `results/postgres_q{1-7}_baseline.json`

### PostgreSQL Write Baseline (Q8)
- [ ] Save to `results/postgres_q8_write_baseline.json`

### PostgreSQL Scalability Baseline (for Chart 3)
- [ ] Re-run Q1–Q7 at two reduced data scales to establish the PostgreSQL scalability curve:
  - [ ] Save to `results/postgres_q{1-7}_scale10.json` and `results/postgres_q{1-7}_scale50.json`

**✅ Phase 2 Deliverable:** All 7 read queries + Q8 write baseline + scalability baselines benchmarked on PostgreSQL, results saved to `results/`.
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

### Q8 — Concurrent Ingestion, Naive (all specialised DBs)
> Naive = 100 concurrent threads, one insert call per event, no batching, no tuning.
> Same pattern as the PostgreSQL baseline — isolates the engine difference cleanly.

- [ ] **MongoDB naive** — 100 threads, one `insert_one()` per event, default write concern
  - [ ] Save to `results/mongodb_q8_naive.json`
- [ ] **Redis naive** — 100 threads, one `SET event:{id} {json}` per event, no pipelining
  - [ ] Save to `results/redis_q8_naive.json`
- [ ] **Neo4j naive** — 100 threads, one `CREATE (e:Event {...})` Cypher call per event
  - [ ] Save to `results/neo4j_q8_naive.json`
- [ ] **Elasticsearch naive** — 100 threads, one `index()` call per event, no bulk API
  - [ ] Save to `results/elasticsearch_q8_naive.json`
- [ ] **Cassandra naive** — 100 threads, one `session.execute()` per event, no `execute_concurrent`
  - [ ] Save to `results/cassandra_q8_naive.json`
- [ ] **TimescaleDB naive** — 100 threads, one `INSERT` per event via psycopg2
  - [ ] Save to `results/timescaledb_q8_naive.json`
- [ ] Record total throughput (events/sec), p50/p95/p99 insert latency, CPU + memory for each
- [ ] Compare all against PostgreSQL baseline from Phase 2

### Scalability at Naive Level (for Chart 3)
- [ ] For each specialised DB, re-run its naive killer query at 10% and 50% data scale
  - [ ] Use the same date-range subsets as the PostgreSQL scalability baseline
  - [ ] Save to `results/{db}_naive_scale10.json` and `results/{db}_naive_scale50.json`

**✅ Phase 3 Deliverable:** 6 naive read benchmarks + 6 naive Q8 write benchmarks + naive scalability data at 3 scales, all saved.

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

### Q8 — Concurrent Ingestion, Optimised (all specialised DBs)
> Optimised = 100 concurrent threads, each accumulating a micro-batch of 50 events then flushing.
> This mirrors a realistic session-end buffer flush — a common and defensible production pattern.
> The batch size of 50 is intentionally small: it represents a single user session, not a bulk ETL job.

- [ ] **MongoDB optimised** — 100 threads, flush 50 events per `insert_many()`, `ordered=False`, `w=1`
  - [ ] Save to `results/mongodb_q8_optimised.json`
- [ ] **Redis optimised** — 100 threads, flush 50 commands per `pipeline()` call
  - [ ] Save to `results/redis_q8_optimised.json`
- [ ] **Neo4j optimised** — 100 threads, flush 50 events per `UNWIND $rows AS row CREATE (e:Event {row})`
  - [ ] Save to `results/neo4j_q8_optimised.json`
- [ ] **Elasticsearch optimised** — 100 threads, flush 50 events per bulk API call
  - [ ] Save to `results/elasticsearch_q8_optimised.json`
- [ ] **Cassandra optimised** — 100 threads, `execute_concurrent()` with 50-statement batches, prepared statements
  - [ ] Save to `results/cassandra_q8_optimised.json`
- [ ] **TimescaleDB optimised** — 100 threads, flush 50 events per `executemany()` call
  - [ ] Save to `results/timescaledb_q8_optimised.json`
- [ ] Document the micro-batch flush decision in each DB's `CHANGES.md`
- [ ] Record total throughput (events/sec), p50/p95/p99 insert latency, CPU + memory for each

### Scalability at Optimised Level (for Chart 3)
- [ ] For each specialised DB, re-run its optimised killer query at 10% and 50% data scale
  - [ ] Save to `results/{db}_optimised_scale10.json` and `results/{db}_optimised_scale50.json`
  - [ ] This answers: does the optimisation gap widen at scale, or is it constant?

**✅ Phase 4 Deliverable:** 6 optimised read benchmarks + 6 optimised Q8 write benchmarks + optimised scalability data at 3 scales completed, all schema and write optimisation notes written.

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
  - [ ] Line chart: p50 latency at 10% / 50% / 100% data scale for PostgreSQL vs each specialised DB (optimised)
  - [ ] Data source: scale results collected in Phases 2, 3, 4
  - [ ] Export as `analysis/charts/scalability_{dbname}.png`
- [ ] **Chart 4 — Throughput under concurrency**
  - [ ] Re-run Q3 (Redis) and Q5 (Elasticsearch) at 1, 10, and 50 concurrent clients
  - [ ] Plot queries/sec vs concurrency level for each
  - [ ] Export as `analysis/charts/throughput_concurrency.png`
- [ ] **Chart 5 — Engine vs Schema gain breakdown**
  - [ ] Stacked bar: how much gain from engine alone (naive) vs schema optimisation (optimised)
  - [ ] Export as `analysis/charts/gain_breakdown.png`

### Summary Table
- [ ] Write `analysis/summary_table.py`
  - [ ] Read table (Q1–Q7): DB × (p50 baseline, p50 naive, p50 optimised, speedup naive, speedup optimised)
  - [ ] Write table (Q8): DB × (events/sec baseline, events/sec naive, events/sec optimised, p99 latency naive, p99 latency optimised, speedup vs PostgreSQL baseline)
  - [ ] Export as `results/summary_table_reads.csv`, `results/summary_table_writes.csv`, and combined `results/summary_table.md`
- [ ] Sanity-check every number — re-run any benchmark that looks suspicious

**✅ Phase 5 Deliverable:** All charts exported as PNG, summary tables as CSV and Markdown.

---

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

**✅ Phase 6 Deliverable:** Full draft completed.

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

**✅ Phase 7 Deliverable:** Final version ready to submit.

---

## Progress Tracker

| Phase | Status        | Date Target | Completed |
|---|---------------|---|---|
| 0 — Environment Setup | ✅ Complete    | — | 2026-02-20 |
| 1 — Schema & Data Generation | ✅ Complete    | — | 2026-02-24 |
| 2 — PostgreSQL Baselines | ⬜ 2026-03-04  | 2026-03-01 | — |
| 3 — Naive Specialised | ⬜ Not started | 2026-03-08 | — |
| 4 — Optimised Specialised | ⬜ Not started | 2026-03-18 | — |
| 5 — Analysis & Visualisation | ⬜ Not started | 2026-04-01 | — |
| 6 — Writing | ⬜ Not started | 2026-04-20 | — |
| 7 — Review & Polish | ⬜ Not started | 2026-05-15 | — |

---