# Todo — The Brownfield Cartographer

Deadlines: **Interim Thu Mar 12 03:00 UTC** | **Final Sun Mar 15 03:00 UTC**

---

## Phase 0 — Reconnaissance & Target Selection

- [ ] Select primary target codebase (dbt jaffle_shop recommended)
- [ ] Clone target repo locally
- [ ] Spend 30 minutes manually exploring the repo
- [ ] Manually answer the Five FDE Day-One Questions by hand
- [ ] Document what was hardest to figure out manually and where you got lost
- [ ] Write `RECONNAISSANCE.md` with manual answers + difficulty analysis
- [ ] Select secondary target codebase (Apache Airflow example DAGs)

---

## Phase 1 — Surveyor Agent (Static Structure) `[INTERIM]`

- [ ] Set up `pyproject.toml` with `uv` and lock dependencies
- [ ] Install tree-sitter and grammars: Python, SQL, YAML, JavaScript
- [ ] Implement `LanguageRouter` — selects correct grammar from file extension
- [ ] Define Pydantic schemas in `src/models/`: `ModuleNode`, `FunctionNode`, `DatasetNode`, `TransformationNode`, edge types
- [ ] Implement `analyze_module(path)` → returns `ModuleNode`
  - [ ] Extract Python import statements + relative path resolution
  - [ ] Extract public functions/classes with signatures
  - [ ] Compute cyclomatic complexity and comment ratio
- [ ] Implement `extract_git_velocity(path, days=30)` using `git log --follow`
  - [ ] Identify top 20% of files by change frequency (high-velocity core)
- [ ] Build module import graph as NetworkX DiGraph
  - [ ] Run PageRank to identify architectural hubs (most-imported modules)
  - [ ] Detect strongly connected components (circular dependencies)
  - [ ] Flag dead code candidates (exported symbols with no inbound references)
- [ ] Serialize graph to `.cartography/module_graph.json`
- [ ] Write `src/agents/surveyor.py` wrapping the above
- [ ] Write `src/graph/knowledge_graph.py` — NetworkX wrapper with serialization
- [ ] Write `src/cli.py` — entry point accepting repo path (local or GitHub URL)
- [ ] Write `src/orchestrator.py` — wires Surveyor output and serializes to `.cartography/`
- [ ] Write `src/analyzers/tree_sitter_analyzer.py` with `LanguageRouter`

---

## Phase 2 — Hydrologist Agent (Data Lineage) `[INTERIM]`

- [ ] Implement `PythonDataFlowAnalyzer` using tree-sitter
  - [ ] Detect `pandas.read_csv`, `read_sql`, `to_csv`, `to_sql`
  - [ ] Detect `SQLAlchemy.execute()` calls
  - [ ] Detect PySpark `spark.read` / `.write` patterns
  - [ ] Log f-string / dynamic references as "dynamic reference, cannot resolve"
- [ ] Implement `SQLLineageAnalyzer` using sqlglot
  - [ ] Parse `.sql` files and dbt model files
  - [ ] Extract table dependencies from SELECT / FROM / JOIN / WITH (CTE) chains
  - [ ] Support: PostgreSQL, BigQuery, Snowflake, DuckDB dialects
- [ ] Implement `DAGConfigAnalyzer`
  - [ ] Parse Airflow DAG Python files for operator dependencies
  - [ ] Parse dbt `schema.yml` for model topology and `ref()` relationships
- [ ] Merge all three analyzers into `DataLineageGraph` (NetworkX DiGraph)
  - [ ] Nodes: `DatasetNode` instances
  - [ ] Edges: `PRODUCES` and `CONSUMES` with `source_file` + `line_range` metadata
- [ ] Implement `blast_radius(node)` — BFS/DFS to find all downstream dependents
- [ ] Implement `find_sources()` — nodes with in-degree = 0
- [ ] Implement `find_sinks()` — nodes with out-degree = 0
- [ ] Serialize to `.cartography/lineage_graph.json`
- [ ] Write `src/agents/hydrologist.py`
- [ ] Write `src/analyzers/sql_lineage.py`
- [ ] Write `src/analyzers/dag_config_parser.py`

---

## Phase 3 — Semanticist Agent (LLM-Powered Analysis) `[FINAL]`

- [ ] Implement `ContextWindowBudget` — token estimation + cumulative spend tracking
- [ ] Implement tiered model selection: Gemini Flash for bulk, Claude/GPT-4 for synthesis
- [ ] Implement `generate_purpose_statement(module_node)`
  - [ ] Prompt with actual code (not docstring) — ask for 2–3 sentence business-function statement
  - [ ] Cross-reference with existing docstring
  - [ ] Flag discrepancies as "Documentation Drift"
- [ ] Implement `cluster_into_domains()`
  - [ ] Embed all Purpose Statements (sentence-transformers or OpenAI embeddings)
  - [ ] Run k-means clustering (k = 5–8)
  - [ ] Label each cluster with an inferred domain name
  - [ ] Produce Domain Architecture Map
- [ ] Implement `answer_day_one_questions()`
  - [ ] Synthesis prompt fed full Surveyor + Hydrologist output
  - [ ] Must return answers with specific evidence citations (file path + line number)
- [ ] Write `src/agents/semanticist.py`

---

## Phase 4 — Archivist & Navigator `[FINAL]`

- [ ] Implement `generate_CODEBASE_md()` with required sections:
  - [ ] Architecture Overview (1 paragraph)
  - [ ] Critical Path (top 5 modules by PageRank)
  - [ ] Data Sources & Sinks (from Hydrologist)
  - [ ] Known Debt (circular deps + doc drift flags)
  - [ ] High-Velocity Files (top files by git change frequency)
  - [ ] Module Purpose Index
- [ ] Implement `generate_onboarding_brief()` — answers to the Five FDE Day-One Questions with evidence
- [ ] Implement `cartography_trace.jsonl` logging — every agent action, evidence source, confidence level
- [ ] Build vector store in `semantic_index/` from all Purpose Statements
- [ ] Implement incremental update mode — re-analyze only files changed since last run (`git diff`)
- [ ] Build Navigator LangGraph agent in `src/agents/navigator.py`
  - [ ] Tool: `find_implementation(concept)` — semantic search over vector store
  - [ ] Tool: `trace_lineage(dataset, direction)` — graph traversal with file:line citations
  - [ ] Tool: `blast_radius(module_path)` — downstream dependency graph
  - [ ] Tool: `explain_module(path)` — LLM generative explanation with evidence
  - [ ] Every answer must cite: source file, line range, analysis method (static vs. LLM)
- [ ] Update `src/cli.py` with subcommands: `analyze` (full pipeline) and `query` (Navigator interactive mode)
- [ ] Update `src/orchestrator.py` to run full pipeline: Surveyor → Hydrologist → Semanticist → Archivist
- [ ] Write `src/agents/archivist.py`
- [ ] Build Streamlit query UI (optional but preferred over raw CLI)

---

## Phase 5 — Visualization Dashboard `[FINAL]`

- [ ] Install dependencies: `pyvis`, `plotly`, `streamlit`
- [ ] Build `src/dashboard/app.py` — Streamlit multi-page app (reads from `.cartography/` only, no analysis logic)
- [ ] Add `dashboard` subcommand to `src/cli.py` — launches Streamlit app pointed at a `.cartography/` directory
- [ ] **System Map view** (PyVis or Plotly network graph)
  - [ ] Nodes sized by PageRank score
  - [ ] Nodes colored by domain cluster (from Semanticist)
  - [ ] Hover tooltip: purpose statement, complexity score, change velocity, dead code flag
  - [ ] Click to expand: show all import/export edges for that module
  - [ ] Highlight circular dependency edges in red
- [ ] **Data Lineage Graph view** (PyVis or Plotly network graph)
  - [ ] Nodes: datasets/tables — shaped/colored by type (source, transformation, sink)
  - [ ] Edges labeled with transformation type and source file
  - [ ] Hover tooltip: schema snapshot, upstream count, downstream count
  - [ ] On node click: show upstream and downstream subgraphs only
- [ ] **Blast Radius view**
  - [ ] Module/dataset selector input
  - [ ] Renders downstream dependency subgraph highlighted in red
  - [ ] Lists affected files with file:line citations
- [ ] **Domain Architecture Map view** (Plotly treemap or sunburst)
  - [ ] Modules grouped by inferred domain cluster
  - [ ] Size = lines of code; color intensity = change velocity
- [ ] **Git Velocity Heatmap view** (Plotly heatmap)
  - [ ] Files on Y-axis, time buckets on X-axis
  - [ ] Surfaces high-churn files (likely pain points)
- [ ] **Navigator Chat UI view** (Streamlit `st.chat_input`)
  - [ ] Natural language query box backed by Navigator LangGraph agent
  - [ ] Renders answers with file:line citations inline
  - [ ] Shows which tool was invoked (semantic search vs. graph traversal vs. LLM)
- [ ] All PyVis graphs exportable as static HTML (for sharing with clients without the tool)
- [ ] Dashboard reads `.cartography/module_graph.json`, `lineage_graph.json`, `semantic_index/` — never re-runs analysis

---

## Cartography Artifacts `[FINAL]`

Run the full pipeline against at least 2 target codebases and commit their `.cartography/` output folders:

- [ ] dbt jaffle_shop
  - [ ] `.cartography/CODEBASE.md`
  - [ ] `.cartography/onboarding_brief.md`
  - [ ] `.cartography/module_graph.json`
  - [ ] `.cartography/lineage_graph.json`
  - [ ] `.cartography/cartography_trace.jsonl`
  - [ ] Verify lineage graph matches dbt's own built-in DAG visualization
- [ ] Apache Airflow example DAGs
  - [ ] `.cartography/CODEBASE.md`
  - [ ] `.cartography/onboarding_brief.md`
  - [ ] `.cartography/module_graph.json`
  - [ ] `.cartography/lineage_graph.json`
  - [ ] `.cartography/cartography_trace.jsonl`
- [ ] Self-referential: run on own Week 1 repo
  - [ ] Compare generated `CODEBASE.md` against hand-written `ARCHITECTURE_NOTES.md`
  - [ ] Document discrepancies (bugs in Cartographer vs. gaps in Week 1 docs)

---

## Documentation & Reports

- [ ] `README.md` — install instructions, how to run `analyze` and `query` against any GitHub URL
- [ ] Interim PDF Report (due Thu Mar 12)
  - [ ] RECONNAISSANCE.md content
  - [ ] Architecture diagram of the four-agent pipeline with data flow
  - [ ] Progress summary (working / in-progress)
  - [ ] Early accuracy observations on module graph and lineage graph
  - [ ] Known gaps and plan for final
- [ ] Final PDF Report (due Sun Mar 15)
  - [ ] RECONNAISSANCE.md — manual answers vs. system-generated comparison
  - [ ] Finalized architecture diagram
  - [ ] Accuracy analysis: which Day-One answers were correct, which were wrong, and why
  - [ ] Limitations: what the Cartographer fails to understand
  - [ ] FDE Applicability: one paragraph on real client engagement usage
  - [ ] Self-audit results with discrepancies explained

---

## Video Demo (max 6 min, due Sun Mar 15)

- [ ] **Step 1 — Cold Start** (required): Run `analyze` on an unfamiliar codebase, show `CODEBASE.md` being generated, time it
- [ ] **Step 2 — Lineage Query** (required): Ask upstream sources for an output dataset, show graph traversal with file:line citations
- [ ] **Step 3 — Blast Radius** (required): Run `blast_radius()` on a module, show downstream dependency graph
- [ ] **Step 4 — Day-One Brief** (mastery): Read Five FDE Answers aloud, verify 2+ answers by navigating to cited file:line
- [ ] **Step 5 — Living Context Injection** (mastery): Inject `CODEBASE.md` into a fresh AI agent session, compare answer quality with vs. without context
- [ ] **Step 6 — Self-Audit** (mastery): Show one discrepancy between own Week 1 docs and generated output, explain it
- [ ] **Bonus — Dashboard Demo** (standout): Launch `cartographer dashboard`, show the interactive System Map and Data Lineage Graph, hover over nodes to reveal purpose statements, demonstrate Blast Radius view and Navigator Chat UI

---

## Engineering Quality Checklist

- [ ] Graceful degradation on unparseable files (log + skip, never crash)
- [ ] No hardcoded repo paths anywhere
- [ ] All node/edge types validated through Pydantic schemas
- [ ] Error handling covers: missing grammars, binary files, encoding errors, empty repos
- [ ] All LLM calls log token usage against `ContextWindowBudget`
- [ ] `cartography_trace.jsonl` entries include: timestamp, agent, action, evidence_source, confidence_level
- [ ] Incremental mode only re-analyzes files changed since last `cartography_trace.jsonl` entry
- [ ] Dashboard is a pure view layer — never triggers analysis, only reads `.cartography/` outputs
- [ ] All graph views export to static HTML for client sharing (no tool install required)
