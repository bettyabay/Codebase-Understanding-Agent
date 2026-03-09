# The Brownfield Cartographer — Project Idea

## Core Problem

When a Forward Deployed Engineer (FDE) lands on a client engagement, they face a brutal constraint: a large, unfamiliar production codebase (often 100k–1M+ lines of Python, SQL, YAML, and notebooks), original engineers who are unavailable, stale documentation, and a 72-hour window to become useful. Four specific failure modes define this situation:

- **Navigation Blindness** — no map of what matters, what is dead code, or how data flows
- **Contextual Amnesia** — every LLM conversation restarts from zero; no persistent architectural model
- **Dependency Opacity** — standard tooling cannot answer "what breaks if this table changes?" across mixed Python/SQL/YAML pipelines
- **Silent Debt** — documentation lies accumulate with every commit; you inherit them all

## The Solution

**The Brownfield Cartographer** is a multi-agent codebase intelligence system. It ingests any GitHub repository or local path and produces a living, queryable knowledge map of the system's architecture, data flows, and semantic structure — purpose-built for data engineering and data science codebases.

The core insight: an FDE does not need to memorize the codebase. They need an instrument that makes it legible. A cartographer builds maps; they do not walk every road.

## The Four Agents

| Agent | Role | Core Technology |
|---|---|---|
| **Surveyor** | Static structure analysis | tree-sitter AST parsing, NetworkX, git log |
| **Hydrologist** | Data flow & lineage | sqlglot, PySpark/pandas pattern detection, YAML parsing |
| **Semanticist** | LLM-powered purpose extraction | Gemini Flash / OpenRouter, vector embeddings, k-means clustering |
| **Archivist** | Living artifact production | Markdown generation, vector store, JSONL trace logging |

A fifth **Navigator** agent (LangGraph) provides the interactive query interface over the built knowledge graph.

## The Four Outputs

1. **CODEBASE.md** — A living context file structured for direct injection into any AI coding agent, giving it instant architectural awareness. The evolution of a CLAUDE.md/AGENTS.md pattern.
2. **onboarding_brief.md** — Answers the Five FDE Day-One Questions with file:line evidence citations.
3. **lineage_graph.json** — Serialized DataLineageGraph (NetworkX DiGraph) of the full data flow DAG crossing Python, SQL, and config boundaries.
4. **semantic_index/** — Vector store of all module Purpose Statements for semantic search.

## The Five FDE Day-One Questions

The system's north star metric. Every architectural decision is evaluated against whether it helps answer these:

1. What is the primary data ingestion path?
2. What are the 3–5 most critical output datasets/endpoints?
3. What is the blast radius if the most critical module fails?
4. Where is the business logic concentrated vs. distributed?
5. What has changed most frequently in the last 90 days?

## Knowledge Graph Schema

The central data store combines a **NetworkX graph** (structure and lineage) with a **vector store** (semantic search). Nodes are typed Pydantic models: `ModuleNode`, `DatasetNode`, `FunctionNode`, `TransformationNode`. Edges are typed: `IMPORTS`, `PRODUCES`, `CONSUMES`, `CALLS`, `CONFIGURES`.

## Navigator Query Interface (LangGraph)

| Tool | Query Type | Example |
|---|---|---|
| `find_implementation(concept)` | Semantic | "Where is the revenue calculation logic?" |
| `trace_lineage(dataset, direction)` | Graph | "What produces the daily_active_users table?" |
| `blast_radius(module_path)` | Graph | "What breaks if I change src/transforms/revenue.py?" |
| `explain_module(path)` | Generative | "Explain what src/ingestion/kafka_consumer.py does" |

## Target Codebases

- **Primary**: dbt `jaffle_shop` — canonical dbt project with SQL + YAML + Python. Lineage must match dbt's own built-in DAG visualization.
- **Primary**: Apache Airflow example DAGs — pipeline topology from Airflow operator definitions.
- **Stretch**: A real company open-source data platform (Airbnb Minerva, Spotify Backstage, etc.)
- **Self-referential**: The Week 1 submission — run Cartographer on its own codebase and compare generated CODEBASE.md against hand-written ARCHITECTURE_NOTES.md.

## Visualization Dashboard

The spec calls for outputs that are "visual and queryable" — not just JSON files. A Streamlit dashboard elevates the Cartographer from a CLI tool to a shareable, client-facing living map.

### Views

| View | Library | Description |
|---|---|---|
| **System Map** | PyVis or Plotly (network graph) | Interactive module dependency graph. Nodes sized by PageRank (architectural importance), colored by domain cluster. Hover shows purpose statement, complexity score, and change velocity. Click to expand import/export edges. |
| **Data Lineage Graph** | PyVis or Plotly | Interactive DAG of the full data flow. Nodes are datasets/tables (sources, transformations, sinks). Edges are labeled with transformation type and source file. Hover shows schema snapshot and upstream/downstream counts. |
| **Blast Radius View** | Plotly subgraph | On selecting a module or dataset, highlight the downstream dependency subgraph in red. Immediately answers "what breaks if this changes?" |
| **Domain Architecture Map** | Plotly treemap or sunburst | Modules grouped by inferred domain cluster (from Semanticist k-means). Shows business logic concentration at a glance. |
| **Git Velocity Heatmap** | Plotly heatmap | File change frequency over time. Surfaces the high-churn files that are likely pain points. |
| **Navigator Chat UI** | Streamlit `st.chat_input` | Natural language query interface over the knowledge graph. Renders answers with file:line citations inline. |

### Key Design Principles

- Every node in both graphs is **clickable** and opens a detail panel with: purpose statement, file path, domain cluster, complexity score, and documentation drift warnings if present.
- The dashboard reads directly from `.cartography/` output files — it is a **view layer only**, not coupled to analysis logic.
- All views are exportable as static HTML (PyVis default) for sharing with clients who do not have the tool installed.
- The dashboard is launched via `cartographer dashboard` subcommand in the CLI.

## Deployment Vision

This is not a homework exercise. It is a deployable FDE tool. An engineer who runs this in the first hour of a client engagement becomes the person who understands the system before anyone else does. Every capability built here is a direct accelerant on real forward-deployed work.

## Stack

- **Language**: Python
- **AST Parsing**: tree-sitter (Python, SQL, YAML, JS grammars)
- **SQL Parsing**: sqlglot (20+ dialects)
- **Graph Analysis**: NetworkX (PageRank, SCC, BFS/DFS, topological sort)
- **Semantic Embeddings**: OpenAI / sentence-transformers
- **LLM Routing**: Gemini Flash (bulk) → Claude/GPT-4 (synthesis only)
- **Agent Orchestration**: LangGraph
- **Schema Validation**: Pydantic
- **Dependency Management**: uv + pyproject.toml
- **Frontend**: Streamlit (dashboard + Navigator chat UI)
- **Graph Visualization**: PyVis (interactive HTML network graphs) or Plotly (network, heatmap, treemap)
- **Dashboard Entry Point**: `cartographer dashboard` CLI subcommand
