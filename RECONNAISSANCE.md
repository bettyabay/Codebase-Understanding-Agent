# RECONNAISSANCE.md — Manual Day-One Analysis

**Target**: `dbt-labs/jaffle_shop`  
**URL**: https://github.com/dbt-labs/jaffle_shop  
**Cloned to**: `repo_cache/jaffle_shop/`  
**Analysis date**: 2026-03-10  
**Time spent**: ~30 minutes manual exploration  

This is the **ground truth** document. The automated system's output will be measured against these answers.

---

## Repository Facts (Manual Inventory)

| Property | Value |
|---|---|
| Total files | 14 (excluding `.git/`) |
| Languages present | SQL (6 files), YAML (3 files), CSV (3 files), Markdown (2 files) |
| Framework | dbt v1.x |
| Materialization strategy | staging models → VIEW; final models → TABLE |
| Seed data | 3 CSV files in `seeds/` (raw_customers, raw_orders, raw_payments) |

### Full File Inventory

```
repo_cache/jaffle_shop/
  seeds/
    raw_customers.csv       ← source data: 100 customer records
    raw_orders.csv          ← source data: ~99 order records
    raw_payments.csv        ← source data: ~113 payment records

  models/
    staging/
      stg_customers.sql     ← renames id → customer_id; selects from raw_customers seed
      stg_orders.sql        ← renames id → order_id, user_id → customer_id; selects from raw_orders seed
      stg_payments.sql      ← renames id → payment_id; converts amount cents → dollars; selects from raw_payments seed
      schema.yml            ← column-level tests for stg_customers, stg_orders, stg_payments
    customers.sql           ← FINAL TABLE: joins stg_customers + stg_orders + stg_payments; computes CLV, order counts, dates
    orders.sql              ← FINAL TABLE: joins stg_orders + stg_payments; pivots payment methods via Jinja loop
    schema.yml              ← column-level descriptions and tests for customers and orders
    overview.md             ← project overview doc block
    docs.md                 ← doc block for orders.status field

  dbt_project.yml           ← project config: name, profile, paths, materialization strategy
  etc/
    dbdiagram_definition.txt ← raw DB schema definition (3 source tables)
  README.md                 ← project description + dbt-learn link
```

---

## The Five FDE Day-One Questions

### Q1. What is the primary data ingestion path?

**Answer**: Data enters the system as static CSV seed files and flows through a strict two-layer pipeline:

```
seeds/raw_customers.csv  ──┐
seeds/raw_orders.csv     ──┼──► staging (VIEW) ──► final models (TABLE)
seeds/raw_payments.csv   ──┘
```

**Detailed path**:
1. `dbt seed` loads the three CSV files into the database as tables: `raw_customers`, `raw_orders`, `raw_payments`
2. Each staging model selects from its corresponding raw table via `{{ ref('raw_*') }}` and does only structural renaming (no filtering, no joins):
   - `stg_customers.sql` → renames `id` to `customer_id` (`seeds/raw_customers.csv`, line 1 header)
   - `stg_orders.sql` → renames `id` → `order_id`, `user_id` → `customer_id` (`seeds/raw_orders.csv`, line 1 header)
   - `stg_payments.sql` → renames `id` → `payment_id`, converts `amount / 100` for cents-to-dollars (`models/staging/stg_payments.sql`, line 20)
3. Final models consume only from staging via `{{ ref('stg_*') }}` — never from raw seeds directly

**Key observation**: There are no external API sources, no Airflow DAGs, no streaming ingestion. This is a batch, file-based ingestion pattern. The `{{ ref() }}` macro is the mechanism that defines all DAG edges — understanding this is critical for lineage extraction.

---

### Q2. What are the 3–5 most critical output datasets or endpoints?

**Answer**: Two final output tables (the sinks of the DAG) and three staging views (critical intermediaries):

| Dataset | Type | File | Why Critical |
|---|---|---|---|
| `customers` | TABLE (final sink) | `models/customers.sql` | Consumer-facing: customer profile + lifetime value + order history. Most complex business logic. |
| `orders` | TABLE (final sink) | `models/orders.sql` | Consumer-facing: enriched order facts with per-payment-method breakdowns. Uses Jinja pivot. |
| `stg_payments` | VIEW (intermediary) | `models/staging/stg_payments.sql` | Consumed by BOTH `customers.sql` AND `orders.sql` — highest fan-out |
| `stg_orders` | VIEW (intermediary) | `models/staging/stg_orders.sql` | Consumed by BOTH `customers.sql` AND `orders.sql` |
| `stg_customers` | VIEW (intermediary) | `models/staging/stg_customers.sql` | Consumed only by `customers.sql` |

**Evidence from `models/customers.sql`**:
- Line 3: `select * from {{ ref('stg_customers') }}`
- Line 8: `select * from {{ ref('stg_orders') }}`
- Line 13: `select * from {{ ref('stg_payments') }}`

**Evidence from `models/orders.sql`**:
- Line 4: `select * from {{ ref('stg_orders') }}`
- Line 9: `select * from {{ ref('stg_payments') }}`

---

### Q3. What is the blast radius if the most critical module fails?

**Most critical module**: `stg_payments` (consumed by both final output tables)

**Blast radius if `stg_payments` fails**:

```
stg_payments (BROKEN)
  ├── orders.sql         → orders TABLE broken     (models/orders.sql, line 9)
  └── customers.sql      → customers TABLE broken   (models/customers.sql, line 13)
       └── [all downstream consumers of customers TABLE broken]
```

**Result**: 100% of final output tables fail. The entire pipeline is down.

**Blast radius if `raw_payments` seed is corrupt/missing**:
- Same as above but one level up — `stg_payments` breaks, which cascades to both final tables.

**Blast radius if `stg_orders` fails**:
- `orders.sql` (direct dep, line 4) → broken
- `customers.sql` (direct dep, line 8) → broken  
- Again: 100% of final outputs broken

**Blast radius if `stg_customers` fails**:
- `customers.sql` only (line 3) → broken
- `orders.sql` is NOT affected (it does not reference `stg_customers`)
- Partial blast: only the `customers` table is lost

**Conclusion**: `stg_orders` and `stg_payments` are the two highest-risk nodes. Failure of either takes down 100% of the output layer. `stg_customers` failure affects only 50% of outputs.

---

### Q4. Where is the business logic concentrated vs. distributed?

**Answer**: Business logic is concentrated almost entirely in two files: `models/customers.sql` and `models/orders.sql`. The staging layer is deliberately logic-free.

**Logic concentration map**:

| File | Logic Type | Complexity |
|---|---|---|
| `models/customers.sql` | Multi-CTE aggregation, LEFT JOINs, computed CLV | HIGH — 4 CTEs, 2 joins |
| `models/orders.sql` | Jinja pivot loop over payment methods, LEFT JOIN | HIGH — Jinja templating + runtime SQL generation |
| `models/staging/stg_payments.sql` | Unit conversion (`amount / 100`) | LOW — 1 arithmetic operation |
| `models/staging/stg_orders.sql` | Column renaming only | NONE |
| `models/staging/stg_customers.sql` | Column renaming only | NONE |
| `dbt_project.yml` | Materialization config (view vs table) | CONFIGURATION |

**Specific evidence**:

- `customers.sql`: The `customer_lifetime_value` metric (`total_amount`) is computed by joining `payments → orders → customers` (lines 33–44), then joined back in the `final` CTE (lines 48–66). This is the most complex transformation in the repo.
- `orders.sql`: Uses a Jinja for-loop (`{% for payment_method in payment_methods %}`) to dynamically generate one column per payment method (lines 20–28). This is a dbt-specific pattern — the actual SQL is not visible in source; it's generated at runtime.
- `dbt_project.yml` (lines 23–26) is the single place that controls materialization: staging = view, final = table. Changing a single line here changes all model types.

**Key finding for the automated system**: The Jinja templating in `orders.sql` means static SQL parsing will fail to see the full column list. The automated system must pre-process `{{ }}` blocks before passing to sqlglot.

---

### Q5. What has changed most frequently in the last 90 days?

**Answer**: **Nothing has changed in the last 90 days.** The last commit was on 2024-04-18, over 22 months before the analysis date of 2026-03-10. The repo is marked as "no longer maintained" in the README.

**All-time change velocity** (full commit history):

| File | Commit Count | Notes |
|---|---|---|
| `models/customers.sql` | 12 | Most-changed file. Early iterations building out the model. |
| `models/orders.sql` | 8 | Second-most changed. Payment pivot logic evolved over time. |
| `dbt_project.yml` | 5 | Config updates: path renames, dbt version pinning |
| `README.md` | 4 | Docs updates, deprecated notice |
| `models/staging/stg_payments.sql` | 2 | Minor changes |
| `models/schema.yml` | 2 | Schema docs added |
| `models/staging/stg_customers.sql` | 2 | Minor changes |

**Implication for automated system**: The git velocity metric will return zeros for the 30-day and 90-day windows. The system should degrade gracefully (e.g., "no recent changes" rather than an error) and fall back to all-time velocity when recent windows are empty.

---

## DAG Structure (Manual Reconstruction)

This is the dbt lineage DAG as understood from manual reading. The automated system must reproduce this exactly.

```
raw_customers (seed) ──► stg_customers ──────────────────────────────► customers (TABLE)
                                                                              ▲
raw_orders (seed)    ──► stg_orders    ──────────────────────────────►───────┤
                                           └──────────────────────────► orders (TABLE)
                                                                              ▲
raw_payments (seed)  ──► stg_payments  ──────────────────────────────►───────┘
                                           └──────────────────────────► customers (TABLE) [via payments CTE]
```

**Cleaner representation**:

```
Nodes (8 total):
  Sources:       raw_customers, raw_orders, raw_payments
  Staging:       stg_customers, stg_orders, stg_payments
  Final:         customers, orders

Edges (7 total):
  raw_customers  → stg_customers
  raw_orders     → stg_orders
  raw_payments   → stg_payments
  stg_customers  → customers
  stg_orders     → customers
  stg_orders     → orders
  stg_payments   → customers
  stg_payments   → orders
```

**Verification target**: The automated system's `lineage_graph.json` must contain exactly these 8 nodes and 8 edges. dbt's own `dbt ls --select` and the lineage visualization at https://www.getdbt.com/blog/getting-started-with-the-dbt-dag confirms this structure.

---

## Difficulty Analysis — What Was Hard to Figure Out Manually

### Easy to determine
- File inventory and language detection (obvious from extensions)
- Which files are sources vs. sinks (clear from DAG structure)
- The staging layer's purpose (naming convention makes it obvious)
- Column-level schema (documented in `schema.yml`)

### Hard to determine without automation
1. **`{{ ref() }}` as DAG edges**: The lineage graph is entirely implicit in Jinja `{{ ref('model_name') }}` calls. A naive grep for `SELECT FROM` finds nothing useful — you must know dbt semantics to know that `ref()` is the dependency declaration mechanism. File: `models/customers.sql` lines 3, 8, 13.

2. **Jinja-generated SQL**: `models/orders.sql` contains a `{% for payment_method in payment_methods %}` loop (lines 20–28) that generates dynamic column names at runtime. Without executing dbt, you cannot see the actual SQL columns. Static SQL parsers (including sqlglot) will fail or produce incorrect results on this file without pre-processing.

3. **Materialization from YAML, not SQL**: Whether a model is a table or a view is not in the SQL file itself — it is set in `dbt_project.yml` lines 23–26. A file-by-file analyzer will miss this unless it also parses the project config.

4. **No explicit source declarations**: The seed tables (`raw_*`) are not declared in a `sources:` YAML block. They are referenced directly via `{{ ref('raw_customers') }}` which treats the seed as a model. This is atypical — most production dbt projects use `{{ source('schema', 'table') }}` for external sources. The automated system must recognize seeds as source nodes.

5. **Blast radius not obvious from filenames**: Without tracing the `ref()` DAG, it is not obvious from filenames alone that `stg_payments` failure cascades to both final tables. You must follow the dependency graph manually.

6. **Git velocity is misleading for this repo**: The repo is marked "no longer maintained." All-time change velocity (`customers.sql` = 12 commits) is meaningful, but 30/90-day velocity is zero. The automated system must handle this gracefully.

### Architecture priorities informed by this analysis

| Priority | Finding | System Implication |
|---|---|---|
| P0 | `{{ ref() }}` extraction is the core lineage mechanism | SQL lineage analyzer must handle `{{ ref('x') }}` before passing to sqlglot |
| P0 | Jinja blocks in SQL make static parsing incomplete | Pre-process or stub Jinja blocks before AST analysis |
| P1 | Seeds are sources, not declared as `sources:` | Repo ingester must detect `seeds/` directory and create source nodes |
| P1 | Materialization from `dbt_project.yml`, not SQL | DAG config parser must read project-level config |
| P2 | Git velocity may be zero for maintained/archived repos | Graceful fallback: show "inactive" rather than error |

---

## Verification Checklist

After the automated system runs on this repo, compare its outputs against this ground truth:

- [ ] Lineage graph contains exactly 8 nodes: `raw_customers`, `raw_orders`, `raw_payments`, `stg_customers`, `stg_orders`, `stg_payments`, `customers`, `orders`
- [ ] Lineage graph contains exactly 8 edges (listed in DAG section above)
- [ ] `raw_customers`, `raw_orders`, `raw_payments` are classified as SOURCE nodes (in-degree = 0)
- [ ] `customers` and `orders` are classified as SINK nodes (out-degree = 0)
- [ ] `stg_payments` and `stg_orders` are identified as highest-blast-radius nodes (each feeds 2 final outputs)
- [ ] `models/customers.sql` and `models/orders.sql` are identified as the highest-complexity files
- [ ] `models/customers.sql` has the highest git velocity (12 commits all-time)
- [ ] System correctly handles Jinja in `models/orders.sql` without crashing
- [ ] Materialization types are correct: staging = view, final = table
