# Dissertation TODO — Performance Gain of Using a Specialised Database

---

## Key Design Decisions

> Read this section before writing any loader or benchmark code.

### All queries run on all databases

Every query (Q1–Q8) is run on **every database** — not just each database's "killer" query.
This is what makes the comparison academically rigorous. Rather than only showing where each
specialised DB excels, the full matrix reveals:

- Where it beats PostgreSQL (its home turf)
- Where it roughly matches PostgreSQL (engine difference only)
- Where it struggles (queries it was never designed for)

Some queries will produce ugly, convoluted implementations in certain databases (e.g. Q1's
temporal JOIN in Redis, or Q4's graph traversal in Cassandra). **This is intentional and
academically valuable** — the awkward implementations demonstrate exactly why you would
choose a specialised database. A slow, convoluted Q4 in Cassandra makes the Neo4j result
more meaningful. Never declare a query "not applicable" — implement it as best you can and
document the limitations.

### Naive vs Optimised — what they mean

**Naive schema** — port the PostgreSQL schema as literally as possible to each specialised DB.
Every table becomes a flat collection/keyspace/index. Foreign keys stay as plain ID reference
fields. No embedding, no denormalisation, no use of DB-native data structures. This answers:
*does the engine alone give any benefit, before thinking about data modelling?*

**Optimised schema** — redesign the schema the way a practitioner of that database would.
For MongoDB: embed related documents, denormalise snapshots. For Redis: use Hashes, Sets,
Sorted Sets instead of JSON strings. For Cassandra: design partition keys around query
patterns. For Neo4j: pre-compute relationship weights. This answers: *how much additional
gain comes from using the database the way it was designed to be used?*

Note on query changes in the optimised phase: the query logic follows the schema — we do
not apply query tricks independent of schema design. However, when the schema changes, the
query naturally changes too. For example, MongoDB Q2 optimised becomes a single `find_one`
because lines are now embedded in the invoice document. Neo4j Q4 optimised becomes a
single-hop traversal because `ALSO_BOUGHT` edges are precomputed at load time. The query
simplification is a consequence of the schema improvement, not a separate optimisation.

### The three-way comparison isolates two distinct effects

For every query on every specialised DB, you get three numbers:

| Level | What it measures |
|---|---|
| PostgreSQL baseline | The relational reference point |
| Naive specialised | Engine effect — DB swap with no modelling change |
| Optimised specialised | Engine + schema effect — full idiomatic implementation |

- **Engine effect** = naive minus baseline (is the DB itself faster, holding schema constant?)
- **Schema effect** = optimised minus naive (how much does idiomatic design add on top?)

This decomposition is the core academic contribution — most benchmarks only show the end
result, not what fraction came from the engine vs the data model.

### Loader scope

Every specialised DB needs ALL tables loaded — users, seller_profiles, subscription_tiers,
subscription_tier_pricing, subscriptions, products, invoices, invoice_lines, orders,
order_items, sessions, events. The loader for each DB is responsible for all 12 tables,
not just the data needed for its killer query.

### Q8 — why there is no optimised write benchmark

Q8 uses a single consistent write pattern across all databases (100 threads, one insert per
event) because this isolates the engine's write performance under realistic production load.
The "optimised" write variant would be micro-batching — but micro-batching is an
application-level pattern change, not a schema-level change. It would not be comparable to
the schema effect measured in Q1–Q7, and would muddy the methodology. Q8 therefore has one
level per DB: the naive single-insert pattern. This decision must be defended explicitly in
the methodology chapter.

---

## The Queries

> Q1–Q7 are each one database's "killer" query — the workload it was specifically designed for.
> ALL queries are run on ALL databases — see Key Design Decisions above.

| # | Killer DB     | Query | What it uniquely demonstrates |
|---|---------------|---|---|
| Q1 | PostgreSQL    | Monthly revenue report by subscription tier incl. marketplace purchases, last 12 months — temporal JOIN on pricing history | Multi-table temporal JOIN — relational elegance |
| Q2 | MongoDB       | Fetch a complete invoice with customer info, all line items and product details in a single read | Embedded document model — zero JOINs |
| Q3 |               | Retrieve a user's active session and full cart contents under 50 concurrent requests | Single-key lookup under concurrency |
| Q4 | Neo4j         | Given a product, find the top 10 recommendations based on co-purchase traversal | Graph traversal — structurally impossible to replicate efficiently in SQL |
| Q5 | Elasticsearch | Full-text product search with relevance ranking across name, description and attributes | BM25 ranking + custom analysers — PostgreSQL tsvector is the baseline |
| Q6 | Cassandra     | Retrieve all activity events for a specific user in a 30-day window, ordered by time | Wide-row partition scan at 5M+ rows |
| Q7 | TimescaleDB   | 7-day rolling average of daily revenue per subscription tier over 6 months, with gap-filling for days with zero activity | `time_bucket_gapfill()` — structurally impossible in plain PostgreSQL |

### Q8 — Concurrent Event Ingestion Benchmark (all 7 DBs)

**Dissertation angle:** Does specialisation confer a write advantage under realistic
production conditions? In production, events are written the moment they occur — one user
action, one insert — across many concurrent users. This benchmark simulates that workload.

| Dimension | Detail |
|---|---|
| Scenario | 100 concurrent threads each inserting individual events as fast as possible |
| Measure | Throughput (events/sec), write latency p50/p95/p99 per insert, CPU and memory via Docker stats API |
| Databases | All 7 — PostgreSQL is the baseline, all specialised DBs compared against it |
| Implementation | Python `threading.Thread` pool (100 workers); each thread loops inserting single events; latency recorded per insert |

| Level | Pattern | Rationale |
|---|---|---|
| PostgreSQL baseline | 100 threads, single `INSERT` per event | Realistic production pattern |
| Specialised DB | 100 threads, single insert call per event, no tuning | Same pattern, different engine — isolates engine difference cleanly |

> **Why not `COPY`?** `COPY` is a bulk data loading tool, not an application write pattern.
> No production system accumulates millions of events then batch-loads them via `COPY`.
> Benchmarking it would measure a data migration tool, not a database engine's write path.

---

## Phase 3 — Specialised Implementations

> Work through each database in full before moving to the next.
> Complete the naive cycle, then the optimised cycle, then scalability — all within the same DB.
> This keeps all related context together and produces usable results after each database.

---

### Cassandra
#### Naive — Benchmark
**Benchmarks** (`benchmarks/cassandra/naive_query.py`):
- Cassandra q4

---

### Elasticsearch

#### Naive — Load

**Loader** (`loaders/elasticsearch_naive_loader.py`):
- [ ] Create all 12 indices with default mapping (no custom analysers, no field boosting)
  - [ ] `users` index
  - [ ] `seller_profiles` index
  - [ ] `subscription_tiers` index
  - [ ] `subscription_tier_pricing` index
  - [ ] `subscriptions` index
  - [ ] `products` index — name, description, attributes as plain `text` (no boosting)
  - [ ] `invoices` index
  - [ ] `invoice_lines` index — `invoice_id` as plain keyword field (not nested)
  - [ ] `orders` index
  - [ ] `order_items` index
  - [ ] `sessions` index — cart stored as JSON string
  - [ ] `events` index

#### Naive — Benchmark

**Benchmarks** (`benchmarks/elasticsearch/naive_query.py`):
- [ ] Q1 — Monthly revenue: `date_histogram` aggregation on invoices + Python join to subscription/tier data
- [ ] Q2 — Invoice fetch: `get` by invoice ID + `search` for lines by `invoice_id` term query
- [ ] Q3 — Session + cart: `get` session document by ID, deserialise cart JSON string
- [ ] Q4 — Recommendations: multi-step Python orchestration — search buyers of product X, aggregate their other purchases
- [ ] Q5 — Product search: `multi_match` across name, description, product_type — default scoring, no boosting
- [ ] Q6 — User events: `range` query on `occurred_at` filtered by `user_id` term
- [ ] Q7 — Rolling revenue: `date_histogram` + `sum` aggregation, no gap-filling
- [ ] Q8 — Concurrent ingestion: 100 threads, one `index()` call per event, no bulk API
- [ ] Run 1000 iterations per query (50 warm-up) with harness
- [ ] Save to `results/elasticsearch_naive_Q{n}.json` for Q1–Q7, `results/elasticsearch_q8.json` for Q8

#### Optimised — Load

**Schema redesign:**
- [ ] Custom analyser on products index: English stemming + stop words + synonym expansion
- [ ] Field-level boosting: `name^3`, `description^1.5`, `product_type^1`
- [ ] Keyword sub-fields on `product_type` and `price_usd` for faceted filtering
- [ ] Enable `norms` on name, disable on low-signal fields
- [ ] Embed invoice_lines as nested objects inside invoice documents (for Q2)
- [ ] Embed event metadata as native object, not string (for Q6)
- [ ] `date`-optimised mappings on all timestamp fields

**Loader** (`loaders/elasticsearch_optimised_loader.py`):
- [ ] Load all 12 tables with the redesigned mappings above

#### Optimised — Benchmark

**Benchmarks** (`benchmarks/elasticsearch/optimised_query.py`):
- [ ] Q1 — Monthly revenue: `date_histogram` + `terms` aggregation with sub-aggregations
- [ ] Q2 — Invoice fetch: single `get` by invoice ID (lines embedded as nested objects)
- [ ] Q3 — Session + cart: single `get` by session ID (cart as native array)
- [ ] Q4 — Recommendations: `terms` aggregation on co-buyers (still Python-orchestrated — no graph)
- [ ] Q5 — Product search: `multi_match` with `best_fields` + boosts + product_type filter
- [ ] Q6 — User events: `range` query with composite (user_id + occurred_at) optimised mapping
- [ ] Q7 — Rolling revenue: `date_histogram` with `extended_bounds` for gap-filling
- [ ] Document changes in `benchmarks/elasticsearch/CHANGES.md`
- [ ] Run 1000 iterations per query (50 warm-up) with harness
- [ ] Save to `results/elasticsearch_optimised_Q{n}.json` for Q1–Q7

#### Scalability
- [ ] Re-run naive at 10% and 50% data scale → `results/elasticsearch_naive_scale10.json` / `scale50.json`
- [ ] Re-run optimised at 10% and 50% data scale → `results/elasticsearch_optimised_scale10.json` / `scale50.json`

---

### TimescaleDB

#### Naive — Load

**Loader** (`loaders/timescaledb_naive_loader.py`):
- [ ] Create all 12 tables identical to PostgreSQL schema
- [ ] Enable hypertable on `events` and `invoices` (time partitioning only — no aggregates yet)
- [ ] Load all data from PostgreSQL master via psycopg2

#### Naive — Benchmark

**Benchmarks** (`benchmarks/timescaledb/naive_query.py`):
- [ ] Q1 — Monthly revenue: same SQL as PostgreSQL baseline (no TimescaleDB-specific features)
- [ ] Q2 — Invoice fetch: same SQL JOIN as PostgreSQL baseline
- [ ] Q3 — Session + cart: same SQL as PostgreSQL baseline
- [ ] Q4 — Recommendations: same SQL co-purchase aggregation as PostgreSQL baseline
- [ ] Q5 — Product search: same tsvector search as PostgreSQL baseline
- [ ] Q6 — User events: same SQL range query as PostgreSQL baseline
- [ ] Q7 — Rolling revenue: plain SQL window functions on raw data (no `time_bucket_gapfill`)
- [ ] Q8 — Concurrent ingestion: 100 threads, one `INSERT` per event via psycopg2
- [ ] Run 1000 iterations per query (50 warm-up) with harness
- [ ] Save to `results/timescaledb_naive_Q{n}.json` for Q1–Q7, `results/timescaledb_q8.json` for Q8

#### Optimised — Load

**Schema redesign:**
- [ ] Hypertable on `events` chunked by week, `invoices` chunked by month
- [ ] Continuous aggregate for daily revenue per subscription tier (powers Q1 and Q7)
- [ ] Enable compression on chunks older than 7 days
- [ ] Add retention policy (demonstrates time-series-native feature set)

**Loader** (`loaders/timescaledb_optimised_loader.py`):
- [ ] Load all 12 tables with redesigned schema above
- [ ] Create continuous aggregate after data load

#### Optimised — Benchmark

**Benchmarks** (`benchmarks/timescaledb/optimised_query.py`):
- [ ] Q1 — Monthly revenue: query continuous aggregate view with `time_bucket`
- [ ] Q2 — Invoice fetch: same SQL JOIN as naive (TimescaleDB adds nothing for document-style fetch)
- [ ] Q3 — Session + cart: same SQL as naive
- [ ] Q4 — Recommendations: same co-purchase SQL as naive (no graph advantage)
- [ ] Q5 — Product search: same tsvector as naive (no text search advantage)
- [ ] Q6 — User events: hypertable chunk-pruned range scan on events
- [ ] Q7 — Rolling revenue: `time_bucket_gapfill()` on continuous aggregate — gap-filling included
- [ ] Document changes in `benchmarks/timescaledb/CHANGES.md`
- [ ] Run 1000 iterations per query (50 warm-up) with harness
- [ ] Save to `results/timescaledb_optimised_Q{n}.json` for Q1–Q7

#### Scalability
- [ ] Re-run naive at 10% and 50% data scale → `results/timescaledb_naive_scale10.json` / `scale50.json`
- [ ] Re-run optimised at 10% and 50% data scale → `results/timescaledb_optimised_scale10.json` / `scale50.json`

---

**✅ Phase 3 Deliverable:** All 6 specialised DBs fully implemented (naive + optimised). Q1–Q8
benchmarked on every DB. Scalability data at 3 scales per killer query. All results saved.

---

## Phase 4 — Analysis & Visualisation

### Result Aggregation
- [ ] Write `analysis/load_results.py`
  - [ ] Reads all JSON files from `results/`
  - [ ] Normalises into a single Pandas DataFrame (DB × Query × Level)
  - [ ] Exports to `results/all_results.csv`

### Charts
- [ ] **Chart 1 — Per-database 3-way comparison** (one chart per specialised DB, all 8 queries)
  - [ ] Grouped bar chart: PostgreSQL Baseline vs Naive vs Optimised, one group per query
  - [ ] Show p50 and p95 side by side
  - [ ] Export as `analysis/charts/comparison_{dbname}.png`
- [ ] **Chart 2 — Cross-database read overview**
  - [ ] All optimised specialised DBs vs PostgreSQL baseline for Q1–Q7
  - [ ] One chart showing each DB's performance relative to PostgreSQL across all queries
  - [ ] Export as `analysis/charts/cross_db_read_overview.png`
- [ ] **Chart 2b — Write throughput comparison (Q8)**
  - [ ] Bar chart: events/sec for PostgreSQL baseline vs each specialised DB
  - [ ] Secondary axis: p99 write latency
  - [ ] Export as `analysis/charts/write_throughput_q8.png`
- [ ] **Chart 3 — Scalability curves**
  - [ ] Line chart: p50 latency at 10% / 50% / 100% data scale for PostgreSQL vs each specialised DB (optimised)
  - [ ] Export as `analysis/charts/scalability_{dbname}.png`
- [ ] **Chart 4 — Throughput under concurrency**
  - [ ] Re-run Q3 (Redis) and Q5 (Elasticsearch) at 1, 10, and 50 concurrent clients
  - [ ] Plot queries/sec vs concurrency level for each
  - [ ] Export as `analysis/charts/throughput_concurrency.png`
- [ ] **Chart 5 — Engine vs Schema gain breakdown**
  - [ ] Stacked bar: how much gain from engine alone (naive) vs schema optimisation (optimised − naive)
  - [ ] Export as `analysis/charts/gain_breakdown.png`

### Summary Table
- [ ] Write `analysis/summary_table.py`
  - [ ] Read table (Q1–Q7): DB × Query × (p50 baseline, p50 naive, p50 optimised, speedup naive, speedup optimised)
  - [ ] Write table (Q8): DB × (events/sec baseline, events/sec specialised, p99 latency, speedup)
  - [ ] Export as `results/summary_table_reads.csv`, `results/summary_table_writes.csv`, `results/summary_table.md`
- [ ] Sanity-check every number — re-run any benchmark that looks suspicious

**✅ Phase 4 Deliverable:** All charts exported as PNG, summary tables as CSV and Markdown.

---

## Phase 5 — Writing

### Methodology and Tools (write first — can be done during benchmark run time)
- [ ] Benchmark harness design (p50/p95/p99, threading, warm-up)
- [ ] Full-scope benchmark rationale — why all queries run on all DBs (engine effect vs schema effect)
- [ ] PostgreSQL baseline design and query implementations
- [ ] Naive specialised schema per DB — design decisions
- [ ] Optimised specialised schema per DB — design decisions and justifications
- [ ] Defence of single Q8 level — why micro-batching was excluded as an application-level rather than schema-level optimisation

### Results and Discussion (write second)
- [ ] Benchmark results per DB with charts — full Q1–Q8 matrix per DB
- [ ] Analysis: engine effect vs schema effect per DB
- [ ] Cross-DB comparison: where each DB wins, matches, and struggles vs PostgreSQL
- [ ] Discussion of deliberately awkward implementations (e.g. Q4 in Cassandra, Q1 in Redis)
  - [ ] Explain why these are valuable data points, not failures of methodology
- [ ] Cross-DB comparison chart and interpretation
- [ ] Statistical tests on latency distributions (Mann-Whitney U or t-test)

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

**✅ Phase 5 Deliverable:** Full draft completed.

---

## Phase 6 — Review & Polish

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
- [ ] Write `README.md` with setup and run instructions
- [ ] Document the fixed random seed for reproducibility

**✅ Phase 6 Deliverable:** Final version ready to submit.

---

## Progress Tracker

| Phase | Status        | Date Target | Completed |
|---|---------------|---|---|
| 0 — Environment Setup | ✅ Complete    | — | 2026-02-20 |
| 1 — Schema & Data Generation | ✅ Complete    | — | 2026-02-24 |
| 2 — PostgreSQL Baselines | ✅ Complete    | — | 2026-03-04 |
| 3 — Specialised Implementations | ⬜ Started     | 2026-03-20 | — |
| 4 — Analysis & Visualisation | ⬜ Not started | 2026-04-01 | — |
| 5 — Writing | ⬜ Not started | 2026-04-20 | — |
| 6 — Review & Polish | ⬜ Not started | 2026-05-15 | — |

---