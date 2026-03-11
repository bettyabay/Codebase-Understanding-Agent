# Brownfield Cartographer

A multi-agent codebase intelligence system for rapid FDE onboarding in production environments.

Point it at any GitHub repository or local path. It produces a living, queryable map of the system's architecture, data flows, and semantic structure in minutes.

## What It Produces

| Artifact | Description |
|---|---|
| `CODEBASE.md` | Living context file for injecting into AI coding agents |
| `onboarding_brief.md` | Answers to the Five FDE Day-One Questions with file:line evidence |
| `module_graph.json` | Full module dependency graph with PageRank scores |
| `lineage_graph.json` | Data lineage DAG from sources to sinks across Python, SQL, and YAML |
| `git_velocity_weekly.json` | Weekly commit frequency matrix for the 2D heatmap dashboard |
| `cartography_trace.jsonl` | Audit log of every analysis action (including parse failures at confidence=0.0) |
| `semantic_index/` | ChromaDB vector store of module purpose statements |

## Installation

```bash
# Install uv (if not already installed)
pip install uv

# Install all dependencies
uv sync

# Or with pip
pip install -e .
```

### Environment Variables (for LLM analysis)

Create a `.env` file in the project root:

```env
# Primary: Gemini 2.5 Flash free tier (recommended)
GOOGLE_API_KEY=AIza...      # or GEMINI_API_KEY=

# Rate-limit fallback: Groq free tier (Llama 3.3 70B)
GROQ_API_KEY=gsk_...

# Last resort / alternative
OPENAI_API_KEY=sk-...
```

**LLM priority**: Gemini 2.5 Flash → Groq Llama 3.3 70B (on 429/rate-limit) → OpenAI GPT-4o-mini.  
Without any API key, pass `--skip-llm` to run static analysis only (Surveyor + Hydrologist). All structural outputs — module graph, lineage graph, git heatmap — are produced regardless of LLM availability.

## Usage

### Analyze a Repository

```bash
# Analyze a GitHub URL (auto-derives repo name: jaffle_shop)
python src/cli.py analyze https://github.com/dbt-labs/jaffle-shop.git

# Analyze a local path
python src/cli.py analyze /path/to/your/repo

# Override the repo name used for output directories
python src/cli.py analyze https://github.com/dbt-labs/jaffle-shop.git --name my_dbt_project

# Skip LLM analysis (faster, no API key needed)
python src/cli.py analyze https://github.com/dbt-labs/jaffle-shop.git --skip-llm

# Custom output directory (overrides the .cartography/<name>/ default)
python src/cli.py analyze /path/to/repo --output ./my-cartography
```

Outputs land in `.cartography/<repo_name>/` and the clone in `repo_cache/<repo_name>/`.

### Analyze Multiple Repos

Each repo gets its own namespace:

```bash
python src/cli.py analyze https://github.com/dbt-labs/jaffle-shop.git --skip-llm
python src/cli.py analyze https://github.com/apache/airflow --skip-llm

# Results:
#   .cartography/jaffle_shop/
#   .cartography/airflow/
#   repo_cache/jaffle_shop/
#   repo_cache/airflow/
```

### Analyze This Repo (Self-referential run)

```bash
python src/cli.py analyze . --name cartographer --skip-llm
# Generates .cartography/cartographer/CODEBASE.md
# Compare against RECONNAISSANCE.md to measure accuracy
```

### Interactive Query

```bash
# Start the Navigator REPL
python src/cli.py query --cartography-dir .cartography/jaffle_shop

# With source code lookup for explain_module
python src/cli.py query --cartography-dir .cartography/jaffle_shop --repo repo_cache/jaffle_shop
```

Example queries:
```
cartographer> What produces the orders table?
cartographer> blast radius of src/transforms/revenue.py
cartographer> Where is the revenue calculation logic?
cartographer> Explain what src/ingestion/kafka_consumer.py does
```

### Launch the Dashboard

```bash
# Point at the root .cartography/ to get a repo-selector dropdown
python src/cli.py dashboard --cartography-dir .cartography/

# Or point directly at a single repo's output
python src/cli.py dashboard --cartography-dir .cartography/jaffle_shop

# Custom port
python src/cli.py dashboard --cartography-dir .cartography/ --port 8502
```

The dashboard opens at `http://localhost:8501` with six views:

1. **System Map** — Interactive module graph, nodes sized by PageRank, colored by domain
2. **Data Lineage Graph** — Full DAG from sources to sinks
3. **Blast Radius** — Select any node to see all downstream dependents highlighted
4. **Domain Architecture Map** — Plotly treemap of modules by business domain
5. **Git Velocity Heatmap** — 2D weekly heatmap: files × weeks, color = commit intensity; surfaces sustained pain points and one-off churn bursts
6. **Navigator Chat** — Natural language queries backed by the knowledge graph

### Incremental Update

```bash
# After new commits to the repo, re-analyze only changed files
python src/cli.py update /path/to/repo

# With explicit name
python src/cli.py update /path/to/repo --name my_project
```

## The Four Agents

```
Surveyor ──────► module_graph.json
  AST parsing, PageRank, git velocity, dead code detection

Hydrologist ───► lineage_graph.json
  SQL lineage (sqlglot), Python data flow, Airflow/dbt DAG topology

Semanticist ───► purpose statements, domain clusters, Day-One answers
  LLM purpose extraction, documentation drift detection, k-means clustering

Archivist ─────► CODEBASE.md, onboarding_brief.md, semantic_index/
  Artifact generation, vector store, trace logging
```

## Error Hardening

The pipeline is designed to never crash on a single bad file:

- **Parse failures** are caught at the individual file level, logged to `cartography_trace.jsonl` with `confidence=0.0`, and skipped — the rest of the analysis continues.
- **LLM call failures** are retried once with exponential backoff, then fall back to an empty `purpose_statement` with a warning in the trace.
- **Missing `.cartography/` directories** are created automatically.
- **Binary files and encoding errors** are silently skipped by the file walker.

## Project Structure

```
src/
  agents/
    surveyor.py        # Static structure analysis
    hydrologist.py     # Data flow & lineage
    semanticist.py     # LLM-powered purpose extraction
    archivist.py       # Artifact generation
    navigator.py       # LangGraph query agent (4 tools)
  analyzers/
    repo_ingester.py       # Clone repos, walk files, git velocity (daily + weekly)
    tree_sitter_analyzer.py  # AST parsing + Python data flow
    sql_lineage.py         # sqlglot-based SQL dependency extraction
    dag_config_parser.py   # Airflow/dbt YAML config parsing
  graph/
    knowledge_graph.py   # NetworkX-backed central data store
  models/
    nodes.py   # Pydantic schemas: ModuleNode, DatasetNode, etc.
    edges.py   # Pydantic schemas: ImportEdge, ProducesEdge, etc.
  dashboard/
    app.py     # Streamlit multi-page visualization app
  orchestrator.py  # Full pipeline wiring + incremental updates
  cli.py           # Typer CLI (analyze, query, dashboard, update)
tests/
spec/
  idea.md   # Project concept and architecture
  plan.md   # Step-by-step implementation plan
```

## The Five FDE Day-One Questions

The system's north star. The `onboarding_brief.md` answers all five:

1. What is the primary data ingestion path?
2. What are the 3–5 most critical output datasets/endpoints?
3. What is the blast radius if the most critical module fails?
4. Where is the business logic concentrated vs. distributed?
5. What has changed most frequently in the last 90 days?

## Stack

- **AST Parsing**: `tree-sitter` + `tree-sitter-languages`
- **SQL Parsing**: `sqlglot` (20+ dialects)
- **Graph Analysis**: `networkx` (PageRank, SCC, BFS/DFS)
- **Embeddings**: `sentence-transformers`
- **Vector Store**: `chromadb`
- **LLM**: Gemini 2.5 Flash (Navigator + bulk, free tier via `GOOGLE_API_KEY`) / OpenAI GPT-4o-mini (fallback)
- **Agent Orchestration**: `langgraph`
- **Dashboard**: `streamlit` + `pyvis` + `plotly`
- **CLI**: `typer`

## Troubleshooting

| Symptom | Fix |
|---|---|
| `No git velocity data found` on heatmap | Re-run `analyze` — `git_velocity_weekly.json` is generated fresh each run |
| `LLM not configured` in onboarding brief | Set `OPENAI_API_KEY` or `GOOGLE_API_KEY` in `.env`, or pass `--skip-llm` |
| Dashboard shows no repos | Run `analyze` first; point `--cartography-dir` at the root `.cartography/` |
| Heatmap bar chart instead of 2D grid | Old analysis — re-run `analyze` to regenerate `git_velocity_weekly.json` |
| `ModuleNotFoundError: src.*` | Run from the project root, not from inside `src/` |
| Slow analysis on large repos | Use `--skip-llm` for pure static analysis (10–30x faster) |
