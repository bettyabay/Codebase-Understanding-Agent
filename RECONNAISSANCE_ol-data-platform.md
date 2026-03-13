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
  - `dg_deployments/`, `dg_projects`: deployment and Dagster configuration.
  - `bin/`: operational scripts (dbt staging model generator, uv operations).
  - `.github/workflows/`: CI for tests/formatting/builds.

---

### Day-One Question 1 — What Is the Primary Data Ingestion Path?


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

