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
| `cartography_trace.jsonl` | Audit log of every analysis action |
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
# At least one of these is needed for Semanticist agent
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=AIza...   # or GEMINI_API_KEY=
```

Without an API key, the `--skip-llm` flag will run static analysis only (Surveyor + Hydrologist).

## Usage

### Analyze a Repository

```bash
# Analyze a GitHub URL
python src/cli.py analyze https://github.com/dbt-labs/jaffle_shop

# Analyze a local path
python src/cli.py analyze /path/to/your/repo

# Skip LLM analysis (faster, no API key needed)
python src/cli.py analyze https://github.com/dbt-labs/jaffle_shop --skip-llm

# Custom output directory
python src/cli.py analyze /path/to/repo --output ./my-cartography
```

### Interactive Query

```bash
# Start the Navigator REPL
python src/cli.py query --cartography-dir .cartography/

# With source code lookup for explain_module
python src/cli.py query --cartography-dir .cartography/ --repo /path/to/repo
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
python src/cli.py dashboard --cartography-dir .cartography/

# Custom port
python src/cli.py dashboard --cartography-dir .cartography/ --port 8502
```

The dashboard opens at `http://localhost:8501` with six views:

1. **System Map** — Interactive module graph, nodes sized by PageRank, colored by domain
2. **Data Lineage Graph** — Full DAG from sources to sinks
3. **Blast Radius** — Select any node to see all downstream dependents highlighted
4. **Domain Architecture Map** — Plotly treemap of modules by business domain
5. **Git Velocity Heatmap** — High-churn files (pain points)
6. **Navigator Chat** — Natural language queries backed by the knowledge graph

### Incremental Update

```bash
# After new commits to the repo, re-analyze only changed files
python src/cli.py update /path/to/repo
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
    repo_ingester.py       # Clone repos, walk files, git velocity
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
  todo.md   # Task checklist
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
- **LLM**: OpenAI GPT-4o-mini (synthesis) / Gemini Flash (bulk)
- **Agent Orchestration**: `langgraph`
- **Dashboard**: `streamlit` + `pyvis` + `plotly`
- **CLI**: `typer`
