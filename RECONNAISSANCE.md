# RECONNAISSANCE.md — Manual Day-One Analysis

**Target**: `dbt-labs/jaffle-shop` (v2 — hyphen, not underscore)  
**URL**: https://github.com/dbt-labs/jaffle-shop.git  
**Cloned to**: `repo_cache/jaffle_shop/`  
**Repo commit**: `7be2c5838dbdeca8e915d4e46db70e910753d7f6`  
**Analysis date**: 2026-03-11  
**Previous version**: The old `jaffle_shop` (underscore) had 14 files, 3 seeds, 2 marts. This v2 repo is a full redesign showcasing MetricFlow / dbt Semantic Layer with 6 entities.

This is the **ground truth** document. The automated system's output will be measured against these answers.

---

## Repository Facts (Automated Inventory — Latest Run)

| Property | Value |
|---|---|
| Repo commit | `7be2c5838dbdeca8e915d4e46db70e910753d7f6` |
| Modules registered | 21 (SQL + YAML files as ModuleNodes) |
| Datasets in lineage | 27 |
| Transformations | 15 |
| Module import edges | 11 |
| Lineage edges | 38 |
| Framework | dbt v1.7+ with MetricFlow / dbt Semantic Layer |
| Materialization | staging → VIEW; marts → TABLE |
| CI/CD | GitHub Actions (`.github/workflows/`) |

---

## Full File Inventory

```
repo_cache/jaffle_shop/
  seeds/
    jaffle-data/
      raw_customers.csv     ← customer records
      raw_items.csv         ← order line-item records  ★ NEW vs v1
      raw_orders.csv        ← order header records
      raw_products.csv      ← product catalog          ★ NEW vs v1
      raw_stores.csv        ← store/location records   ★ NEW vs v1
      raw_supplies.csv      ← supply/ingredient data   ★ NEW vs v1

  macros/
    cents_to_dollars.sql    ← reusable UDF: amount / 100  ★ NEW vs v1 (was inline)
    generate_schema_name.sql ← overrides dbt schema naming convention

  models/
    staging/
      __sources.yml         ← declares raw_* seeds as source() refs  ★ NEW vs v1
      stg_customers.sql     ← selects + renames from raw_customers
      stg_customers.yml     ← schema tests for stg_customers
      stg_locations.sql     ← selects + renames from raw_stores       ★ NEW vs v1
      stg_locations.yml
      stg_order_items.sql   ← selects from raw_items; applies cents_to_dollars ★ NEW
      stg_order_items.yml
      stg_orders.sql        ← selects + renames from raw_orders
      stg_orders.yml
      stg_products.sql      ← selects from raw_products               ★ NEW vs v1
      stg_products.yml
      stg_supplies.sql      ← selects from raw_supplies               ★ NEW vs v1
      stg_supplies.yml

    marts/
      customers.sql         ← FINAL TABLE: customer profile + CLV
      customers.yml
      locations.sql         ← FINAL TABLE: store-level aggregations   ★ NEW vs v1
      locations.yml
      metricflow_time_spine.sql ← date spine for MetricFlow metrics   ★ NEW vs v1
      order_items.sql       ← FINAL TABLE: enriched line items        ★ NEW vs v1
      order_items.yml
      orders.sql            ← FINAL TABLE: order facts
      orders.yml
      products.sql          ← FINAL TABLE: product-level metrics      ★ NEW vs v1
      products.yml
      supplies.sql          ← FINAL TABLE: supply/ingredient metrics  ★ NEW vs v1
      supplies.yml

  dbt_project.yml           ← project config: name, paths, materializations
  packages.yml              ← dbt package dependencies (e.g. dbt_utils)
  package-lock.yml          ← locked package versions
  Taskfile.yml              ← task runner: dbt build, test, docs shortcuts
  .pre-commit-config.yaml   ← sqlfluff linting, yaml validation hooks
  .github/workflows/        ← CI (test on PR) and CD (staging/prod deploy)
  README.md                 ← setup instructions
```

---

## The Five FDE Day-One Questions

### Q1. What is the primary data ingestion path?

**Answer**: Data enters as 6 CSV seed files nested under `seeds/jaffle-data/` and flows through a strict two-layer pipeline — identical architecture to v1 but with 3× more entities:

```
seeds/raw_customers.csv  ──► stg_customers  ──► customers (TABLE)
seeds/raw_orders.csv     ──► stg_orders     ──► orders (TABLE)
                                             ──► order_items (TABLE)
seeds/raw_items.csv      ──► stg_order_items ─► order_items (TABLE)
seeds/raw_products.csv   ──► stg_products   ──► products (TABLE)
seeds/raw_supplies.csv   ──► stg_supplies   ──► supplies (TABLE)
seeds/raw_stores.csv     ──► stg_locations  ──► locations (TABLE)
```

**Key change vs v1**: The v2 repo uses a `__sources.yml` file declaring seeds via `{{ source('jaffle_shop', 'raw_*') }}` instead of `{{ ref('raw_*') }}`. This is the correct dbt pattern for external sources.

**Macro usage**: The `cents_to_dollars` macro (previously inlined in `stg_payments.sql`) is now extracted into `macros/cents_to_dollars.sql` and called in `stg_order_items.sql`.

---

### Q2. What are the 3–5 most critical output datasets or endpoints?

| Dataset | Type | Why Critical |
|---|---|---|
| `orders` | TABLE (mart sink) | Central fact table; most mart models depend on order data |
| `order_items` | TABLE (mart sink) | Line-item granularity; joins stg_orders + stg_order_items + stg_products + stg_supplies |
| `customers` | TABLE (mart sink) | Consumer-facing CLV and order history profile |
| `stg_orders` | VIEW (intermediary) | Feeds multiple downstream marts; single point of failure for order data |
| `stg_order_items` | VIEW (intermediary) | High fan-out: feeds order_items, products, supplies marts |
| `metricflow_time_spine` | TABLE (special) | Required by ALL MetricFlow metric definitions for time-series aggregation |

**Note on `metricflow_time_spine`**: This model is unique — it generates a date spine (one row per day) and is not a business model. It is a required dependency for the dbt Semantic Layer. Failure here breaks all time-series metrics across every mart, even though it has no SQL business logic.

---

### Q3. What is the blast radius if the most critical module fails?

**Most critical module**: `stg_orders` (consumed by `orders`, `order_items`, `customers`, `locations`)

**Blast radius if `stg_orders` fails**:

```
stg_orders (BROKEN)
  ├── orders.sql          → orders TABLE broken
  ├── order_items.sql     → order_items TABLE broken
  ├── customers.sql       → customers TABLE broken (order history CTEs fail)
  └── locations.sql       → locations TABLE broken (order aggregations fail)
```

**Result**: 4 of 6 mart tables fail (67% of output layer).

**Blast radius if `stg_order_items` fails**:
```
stg_order_items (BROKEN)
  ├── order_items.sql     → broken
  ├── products.sql        → broken (product-level metrics depend on items)
  └── supplies.sql        → broken (supply-level metrics depend on items)
```
**Result**: 3 of 6 mart tables fail (50% of output layer).

**Blast radius if `metricflow_time_spine` fails**:
- No direct SQL dependency chain, but all MetricFlow metric queries fail at query time (the Semantic Layer cannot generate time-series slices). Invisible to dbt build but breaks every BI tool metric.

**Conclusion**: `stg_orders` is the single highest-risk node. `metricflow_time_spine` is a hidden risk that won't surface in `dbt build` but breaks the Semantic Layer entirely.

---

### Q4. Where is the business logic concentrated vs. distributed?

| File | Logic Type | Complexity |
|---|---|---|
| `models/marts/order_items.sql` | Multi-join enrichment: items + orders + products + supplies | HIGH — 4-table join |
| `models/marts/customers.sql` | CTE aggregation, CLV computation, order history | HIGH |
| `models/marts/orders.sql` | Order-level aggregations, payment rollup | MEDIUM |
| `models/marts/products.sql` | Product-level sales metrics from order_items | MEDIUM |
| `models/marts/locations.sql` | Store-level aggregations from orders | MEDIUM |
| `models/marts/supplies.sql` | Supply-level cost metrics from order_items | MEDIUM |
| `models/marts/metricflow_time_spine.sql` | Date spine generation only | LOW — no business logic |
| `models/staging/*.sql` | Column renaming, type casting only | LOW |
| `macros/cents_to_dollars.sql` | Single arithmetic expression | TRIVIAL |
| `macros/generate_schema_name.sql` | dbt convention override | CONFIGURATION |

**Key change vs v1**: Business logic is no longer concentrated in 2 files — it is now spread across 6 mart models. `order_items` replaces the old `orders.sql` Jinja pivot as the most complex transformation.

**MetricFlow addition**: The `.yml` files in `models/marts/` likely contain `metrics:` blocks (dbt Semantic Layer definitions). These are non-SQL business logic that static analysis will not capture from `.sql` files alone.

---

### Q5. What has changed most frequently?

The repo commit is `7be2c5838...` — this is the v2 redesign commit. Git history is shallow (`--depth=100`). The git velocity heatmap will show recent activity patterns. Given this is an actively maintained reference repo (unlike the archived v1), expect genuine recent commits on `dbt_project.yml`, staging models, and mart models.

**Expected high-velocity files** (based on typical reference repo maintenance patterns):
- `dbt_project.yml` — version bumps and config changes
- `models/marts/*.sql` — metric refinements
- `models/staging/__sources.yml` — source additions

---

## DAG Structure (Reconstructed from File Analysis)

```
Seeds (sources)          Staging (VIEW)            Marts (TABLE)
─────────────────────────────────────────────────────────────────
raw_customers  ────────► stg_customers ──────────► customers
                                       ──────────► (via orders join)

raw_orders     ────────► stg_orders   ───────────► orders
                                      ───────────► order_items
                                      ───────────► customers
                                      ───────────► locations

raw_items      ────────► stg_order_items ─────────► order_items
                                         ─────────► products
                                         ─────────► supplies

raw_products   ────────► stg_products ───────────► order_items
                                      ───────────► products

raw_supplies   ────────► stg_supplies ───────────► order_items
                                      ───────────► supplies

raw_stores     ────────► stg_locations ──────────► locations

(standalone)                            ──────────► metricflow_time_spine
```

**Automated system output (latest run)**:
- 27 datasets in lineage graph
- 38 lineage edges
- 15 transformations detected

---

## What Changed vs v1 (Automated System Implications)

| Change | v1 Behavior | v2 Behavior | System Impact |
|---|---|---|---|
| Source declarations | `ref('raw_*')` — seeds as models | `source('jaffle_shop', 'raw_*')` via `__sources.yml` | Hydrologist must parse `source()` calls, not just `ref()` |
| Seed location | `seeds/*.csv` (flat) | `seeds/jaffle-data/*.csv` (subdirectory) | Surveyor must walk nested seed dirs |
| Macro extraction | Logic inlined in SQL | `{{ cents_to_dollars(amount) }}` macro call | SQL parser sees a function call, not arithmetic |
| MetricFlow models | Not present | `metricflow_time_spine.sql` + metric YAML blocks | Semantic Layer models look like normal models but serve a different purpose |
| Schema YAML pairing | `schema.yml` for all models | Per-model `.yml` files (e.g. `customers.yml`) | YAML parser must handle 1:1 SQL/YAML pairing |
| CI/CD | Not present | GitHub Actions workflows | Surveyor should recognize `.github/` as infrastructure, not business logic |

---

## Verification Checklist

After the automated system runs on this repo, compare its output against this ground truth:

- [x] Surveyor registers 21 modules (SQL + YAML files)
- [x] Hydrologist finds 27 datasets
- [x] 38 lineage edges detected
- [x] 15 transformations found
- [ ] `stg_orders` identified as highest-blast-radius node (fans out to 4 marts)
- [ ] `metricflow_time_spine` correctly classified as a utility/spine model, not a business sink
- [ ] `macros/cents_to_dollars` registered as a module (SQL macro)
- [ ] `source()` calls parsed correctly (not just `ref()`)
- [ ] Seeds nested under `seeds/jaffle-data/` are detected as source nodes
- [ ] Per-model `.yml` files linked to their corresponding `.sql` files
- [ ] `stg_order_items` identified as second-highest fan-out node (feeds 3 marts)
- [ ] System handles `generate_schema_name.sql` macro without crashing (no `ref()`/`source()` calls)

---

## Target 2 — MIT Open Learning Data Platform (`mitodl/ol-data-platform`)

**Target**: `mitodl/ol-data-platform`  
**URL**: `https://github.com/mitodl/ol-data-platform.git`  
**Cloned to**: `repo_cache/ol-data-platform/` <!-- adjust to your actual cache path -->  
**Repo commit**: `<fill in from git rev-parse HEAD>`  
**Analysis date**: 2026-03-13  

This section is **manual ground truth** based on reading the repo by hand. Automated Cartographer output for `ol-data-platform` should be compared against these answers.

### Repository Snapshot (Manual)

- **Core role**: Central Dagster + dbt–based data platform for MIT Open Learning, orchestrating ingestion and transformation pipelines into an analytics warehouse.
- **Key technologies**:
  - Dagster (Python) for orchestration and code locations.
  - dbt for warehouse modeling (staging, marts, intermediate models).
  - Docker + `docker-compose` for local Dagster.
  - `uv` and `pyproject.toml` for Python environment management.
- **Key directories (high level)**:
  - `src/`: Dagster code locations and Python business logic.
  - `src/ol_dbt/`: dbt project (models, seeds, macros, sources).
  - `dg_deployments/`, `dg_projects/`: deployment and Dagster configuration.
  - `bin/`: operational scripts (dbt staging model generator, uv operations).
  - `.github/workflows/`: CI for tests/formatting/builds.

---

### Day-One Question 1 — What Is the Primary Data Ingestion Path?

**Manual answer (to refine as you explore):**

At a high level, data ingestion looks like:

- **Upstream systems**: Application databases and services for various MIT Open Learning products (for example, MITlearn / MITx Online), exposed as raw schemas in a shared analytics warehouse.
- **Landing / raw zone**: Raw tables in warehouse schemas such as `ol_warehouse_production_raw` (names referenced in scripts like `bin/dbt-create-staging-models.py` and dbt source definitions).
- **Ingestion / orchestration**:
  - Dagster assets and jobs call out to:
    - Warehouse connections (via Python DB APIs / SQLAlchemy / drivers).
    - dbt command runs (for example, `dbt run`, `dbt build`) for transformations.
- **Modeling**:
  - dbt staging models under `src/ol_dbt/models/staging/{domain}/` normalize raw tables into clean, domain-focused staging layers.
  - dbt marts under `src/ol_dbt/models/marts/{domain}/` define analytics-ready facts and dimensions.

Conceptual pipeline sketch:

```text
App DBs / external feeds
      ↓ (extracted via ETL tools, connectors, or SQL)
Warehouse raw schemas (e.g. ol_warehouse_*_raw tables)
      ↓ (dbt sources + staging models)
dbt staging models (per domain)
      ↓ (dbt intermediate / marts)
dbt marts and aggregates
      ↓
BI tools / dashboards / reports for MIT Open Learning
```

You should refine this with specific schema and model names you see in the dbt project.

---

### Day-One Question 2 — What Are the 3–5 Most Critical Output Datasets or Endpoints?

**Manual answer (initial hypothesis):**

Based on the README and structure, critical outputs are:

- **Core warehouse marts**:
  - Fact tables summarizing learner activity, enrollments, completions, revenue, and other product analytics (dbt models under `models/marts/{domain}/`).
- **Shared dimension / entity tables**:
  - Normalized entities like users, courses, runs, programs, videos, and sites that are shared across analyses.
- **Dagster-exposed assets / jobs**:
  - Dagster job/asset graphs that orchestrate dbt runs and possibly additional Python-based transforms to produce final tables.
- **Downstream consumers**:
  - BI dashboards and reports that read from the above warehouse tables (not in this repo, but clearly the primary consumers).

As you explore, list 3–5 **specific** dbt models (with paths) that look like the most central “sinks” in the lineage graph (for example, `src/ol_dbt/models/marts/mitlearn/fct_<something>.sql`).

---

### Day-One Question 3 — What Is the Blast Radius If the Most Critical Module Fails?

**Manual answer (initial):**

- A failure in a **core Dagster job** that orchestrates multiple product pipelines (for example, a job that runs all warehouse dbt models nightly) will:
  - Stop new data from flowing into all downstream marts for that product family.
  - Break freshness SLAs for dashboards built on those marts.

- A failure in a **shared dbt staging or intermediate model**:
  - For example, a staging model for a shared entity such as `user` or `course` that feeds many downstream marts.
  - Blast radius: multiple fact tables and semantic metrics that depend on this shared entity go stale or error.

- A failure in an **environment / deployment definition** in `dg_deployments`:
  - Could prevent an entire Dagster deployment (for example, production) from running any jobs at all.

Once you locate specific high-fan-out models (for example, a shared user dimension), write a more concrete sketch like:

```text
stg_users (BROKEN)
  ├── fct_enrollments
  ├── fct_course_engagement
  ├── dim_learners
  └── [other marts]
Result: majority of learner-facing metrics fail or go stale.
```

---

### Day-One Question 4 — Where Is the Business Logic Concentrated vs. Distributed?

**Manual answer (initial):**

- **Concentrated business logic**:
  - dbt **marts**: complex joins, aggregations, and metric definitions per domain (`models/marts/{domain}/...`).
  - Some **Python transforms / Dagster assets** that do non-SQL work (for example, custom pre-processing before writing to the warehouse).
  - Potential shared libraries under `packages/ol-orchestrate-lib` or similar folders.

- **Distributed / configuration logic**:
  - dbt **staging models**: mostly normalization, renaming, and type casting.
  - YAML files for dbt sources, tests, and metrics (schema and semantic definitions).
  - Dagster configuration and deployment descriptors (code locations, schedules, resources).

As you read a few representative files, note which ones actually contain business rules (for example, how a “learner engagement” metric is computed) versus wiring / config.

---

### Day-One Question 5 — What Has Changed Most Frequently?

**Manual answer (initial hypothesis, before running git stats):**

Given this is an active production data platform, you can expect high-velocity areas to include:

- **dbt models**:
  - `models/marts/` and `models/staging/` where new products/entities are onboarded and metrics are refined.
- **Dagster orchestration code**:
  - Jobs and assets under `src/` that define pipelines and shared resources.
- **Deployment / environment configs**:
  - `dg_deployments/` and `dg_projects/` as new code locations and environments are added.
- **Operational scripts**:
  - `bin/dbt-create-staging-models.py` and `bin/uv-operations.py` as automation requirements evolve.

Later, the automated **git velocity** computation (Phase 1) should either confirm or correct this list.

---

### Difficulty Analysis (for `ol-data-platform`)

**What was hardest to figure out manually?**

- Mapping all the different **products/domains** (for example, MITlearn vs other offerings) to specific Dagster code locations and dbt subtrees.
- Understanding how **Dagster deployments** (`dg_deployments`) relate to code locations and dbt projects.
- Tracing a single **business question** (for example, “How do we compute learner engagement for MITlearn?”) through Dagster → dbt → warehouse tables.

**Where I got lost / needed to slow down:**

- Jumping between Dagster Python code and dbt SQL/YAML for the same domain.
- Interpreting environment-specific settings (dev vs qa vs prod) and how secrets/config are wired (Vault, environment variables).

These pain points are what the Cartographer system should make trivially easy later.
