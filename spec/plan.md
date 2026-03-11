# Implementation Plan — The Brownfield Cartographer

A sequential, dependency-ordered build guide. Each step produces a working, testable artifact before the next step begins. Do not skip ahead — later steps depend on the outputs of earlier ones.

---

## Step 1 — Project Scaffold & Dependencies

**Goal**: A runnable project with all dependencies installed and a working CLI entry point.

1. Create the project directory structure:
   ```
   src/
     agents/
     analyzers/
     dashboard/
     graph/
     models/
   tests/
   .cartography/       ← output directory (git-ignored)
   spec/
   ```
2. Initialize `pyproject.toml` with `uv`. Add all dependencies up front:
   - `tree-sitter`, `tree-sitter-python`, `tree-sitter-languages`
   - `sqlglot`
   - `networkx`
   - `pydantic`
   - `langgraph`, `langchain-core`
   - `sentence-transformers` or `openai`
   - `chromadb` (vector store)
   - `streamlit`, `pyvis`, `plotly`
   - `gitpython`
   - `rich` (CLI output formatting)
   - `typer` (CLI framework)
3. Run `uv lock` and commit `uv.lock`.
4. Create `src/cli.py` using Typer with four placeholder subcommands: `analyze`, `query`, `dashboard`, `update`.
5. Verify: `python src/cli.py --help` prints all four commands without errors.

---

## Step 2 — Pydantic Data Models

**Goal**: All data contracts defined before any analysis code is written. Every subsequent step imports from here — nothing else defines schemas.

Create `src/models/nodes.py`:
- `ModuleNode`: `path`, `language`, `purpose_statement`, `domain_cluster`, `complexity_score`, `change_velocity_30d`, `is_dead_code_candidate`, `last_modified`
- `DatasetNode`: `name`, `storage_type` (enum: `table|file|stream|api`), `schema_snapshot`, `freshness_sla`, `owner`, `is_source_of_truth`
- `FunctionNode`: `qualified_name`, `parent_module`, `signature`, `purpose_statement`, `call_count_within_repo`, `is_public_api`
- `TransformationNode`: `source_datasets`, `target_datasets`, `transformation_type`, `source_file`, `line_range`, `sql_query_if_applicable`

Create `src/models/edges.py`:
- `ImportEdge`: `source_module`, `target_module`, `import_count`
- `ProducesEdge`: `transformation`, `dataset`, `source_file`, `line_range`
- `ConsumesEdge`: `transformation`, `dataset`, `source_file`, `line_range`
- `CallsEdge`: `caller`, `callee`
- `ConfiguresEdge`: `config_file`, `target`

Create `src/models/graph.py`:
- `KnowledgeGraphData`: a Pydantic model wrapping all nodes and edges lists — used for serialization to/from `.cartography/*.json`

Verify: `python -c "from src.models.nodes import ModuleNode; print('ok')"` succeeds.

---

## Step 3 — Knowledge Graph Store

**Goal**: A central in-memory store backed by NetworkX that all agents read from and write to. This is the single source of truth.

Create `src/graph/knowledge_graph.py`:
1. `KnowledgeGraph` class wrapping two `nx.DiGraph` instances: `module_graph` and `lineage_graph`
2. Methods:
   - `add_module(node: ModuleNode)` — adds to `module_graph`
   - `add_dataset(node: DatasetNode)` — adds to `lineage_graph`
   - `add_transformation(node: TransformationNode)` — adds edges to `lineage_graph`
   - `add_import_edge(edge: ImportEdge)` — adds to `module_graph`
   - `get_module(path: str) -> ModuleNode`
   - `all_modules() -> list[ModuleNode]`
   - `all_datasets() -> list[DatasetNode]`
3. Serialization:
   - `save(output_dir: Path)` — writes `module_graph.json` and `lineage_graph.json` using NetworkX's `node_link_data`
   - `load(output_dir: Path)` — reads them back and reconstructs both graphs

Verify: create a graph, add two modules with an import edge, save to disk, reload, and assert the edge is present.

---

## Step 4 — Repo Ingestion & Git Velocity

**Goal**: Given a local path or GitHub URL, produce a list of all analyzable files with their git change metadata.

Create `src/analyzers/repo_ingester.py`:
1. `clone_if_remote(repo_path: str) -> Path` — if URL, clone to a temp dir using `gitpython`; if local path, return as-is
2. `walk_repo(root: Path) -> list[FileRecord]` where `FileRecord` has `path`, `language`, `size_bytes`, `last_modified`
   - Skip: `.git/`, `node_modules/`, `__pycache__/`, binary files, files > 1MB
   - Detect language from extension: `.py` → Python, `.sql` → SQL, `.yml`/`.yaml` → YAML, `.ipynb` → Notebook
3. `extract_git_velocity(root: Path, days: int = 30) -> dict[str, int]` — runs `git log --follow --name-only` and returns a `{file_path: commit_count}` map
   - Identify the top 20% of files by change count (high-velocity core)

Verify: point at the dbt `jaffle_shop` repo, print the file list and top 5 highest-velocity files.

---

## Step 5 — Tree-sitter Analyzer (The Surveyor's Core)

**Goal**: Parse any Python, SQL, or YAML file into structured AST data without regex.

Create `src/analyzers/tree_sitter_analyzer.py`:
1. `LanguageRouter` class:
   - `get_parser(language: str) -> Parser` — returns a cached tree-sitter `Parser` for the given language
   - Supported: `python`, `sql`, `yaml`
2. `PythonASTAnalyzer`:
   - `extract_imports(tree) -> list[str]` — walks the AST for `import_statement` and `import_from_statement` nodes, returns module names
   - `extract_functions(tree) -> list[FunctionNode]` — finds `function_definition` nodes, extracts name, args, decorators, line range
   - `extract_classes(tree) -> list[str]` — finds `class_definition` nodes
   - `compute_complexity(tree) -> int` — counts branches: `if`, `for`, `while`, `except`, `with` nodes (approximation of cyclomatic complexity)
3. `YAMLASTAnalyzer`:
   - `extract_keys(tree) -> list[str]` — walks the tree for top-level keys (used by DAG config parser)

**Error handling**: if tree-sitter fails to parse a file (e.g., encoding error, unsupported syntax), log the error and return empty results — never raise.

Verify: parse `jaffle_shop/models/staging/stg_orders.sql` and `jaffle_shop/dbt_project.yml`, print extracted symbols.

---

## Step 6 — SQL Lineage Analyzer

**Goal**: Given a `.sql` or `.dbt` model file, extract the full table dependency graph using sqlglot.

Create `src/analyzers/sql_lineage.py`:
1. `SQLLineageAnalyzer`:
   - `detect_dialect(file_path: Path) -> str` — infer from path hints (`dbt` → default, `bq` → bigquery, `snowflake` → snowflake)
   - `extract_dependencies(sql: str, dialect: str) -> SQLDependency` where `SQLDependency` has `source_tables: list[str]` and `target_table: str`
     - Parse with `sqlglot.parse(sql, dialect=dialect)`
     - Walk the AST for `From`, `Join`, `Table` nodes to collect upstream tables
     - Handle CTEs: a CTE name is an intermediate node, not a real table
   - `analyze_file(path: Path) -> list[SQLDependency]` — reads file, detects dialect, returns dependencies
2. For dbt models: the file name (without `.sql`) is the target table. All `ref()` calls are upstream dependencies — parse `{{ ref('table_name') }}` as a special case before passing to sqlglot.

Verify: run against all `.sql` files in `jaffle_shop/models/`, print the dependency graph. Compare with dbt's own `dbt ls --select` lineage output.

---

## Step 7 — DAG Config Analyzer

**Goal**: Extract pipeline topology from Airflow DAG Python files and dbt `schema.yml` without executing the code.

Create `src/analyzers/dag_config_parser.py`:
1. `DbtSchemaParser`:
   - `parse_schema_yml(path: Path) -> list[DatasetNode]` — reads `schema.yml`, extracts model names, column definitions, and descriptions
   - `parse_sources_yml(path: Path) -> list[DatasetNode]` — extracts source table definitions (these become source nodes in the lineage graph)
2. `AirflowDAGParser`:
   - `parse_dag_file(path: Path) -> DAGTopology` where `DAGTopology` has `dag_id`, `tasks: list[TaskNode]`, `dependencies: list[tuple[str, str]]`
   - Use tree-sitter Python AST to find `>>` operator chains and `set_upstream`/`set_downstream` calls — do not `exec()` the file
3. `dbtProjectParser`:
   - `parse_dbt_project_yml(path: Path) -> dbtProject` — extracts `name`, `model-paths`, `seed-paths`, `profile`

Verify: parse `jaffle_shop/dbt_project.yml` and all `schema.yml` files, print all source and model nodes found.

---

## Step 8 — Python Data Flow Analyzer

**Goal**: Detect pandas/SQLAlchemy/PySpark read and write operations in Python files to build the data lineage edges.

Add `PythonDataFlowAnalyzer` to `src/analyzers/tree_sitter_analyzer.py` (or a separate file if it grows large):
1. Use tree-sitter to find `call` AST nodes matching these patterns:
   - `pd.read_csv(...)`, `pd.read_sql(...)`, `pd.to_csv(...)`, `pd.to_sql(...)` → extract the first string argument as the dataset path
   - `spark.read.csv(...)`, `spark.read.parquet(...)`, `.write.parquet(...)` → extract path argument
   - `engine.execute(...)`, `session.query(...)` → extract SQL string argument if literal
2. For each detected call:
   - If argument is a string literal: create a `DatasetNode` with that path as name
   - If argument is an f-string or variable: create a `DatasetNode` with `name="dynamic:<variable_name>"` and log a warning
3. Return `list[DataFlowCall]` with `call_type` (read|write), `dataset_name`, `source_file`, `line_number`

Verify: run on a PySpark file, confirm read/write calls are detected with correct line numbers.

---

## Step 9 — Surveyor Agent

**Goal**: Orchestrate Steps 4–5 into a complete module graph with PageRank, circular dependency detection, and dead code flagging.

Create `src/agents/surveyor.py`:
1. `Surveyor.analyze(repo_path: Path, kg: KnowledgeGraph)`:
   a. Call `repo_ingester.walk_repo()` → file list
   b. Call `repo_ingester.extract_git_velocity()` → velocity map
   c. For each Python file: call `tree_sitter_analyzer.analyze_module()` → `ModuleNode`; add to `kg`
   d. For each import edge found: call `kg.add_import_edge()`
   e. After all files processed:
      - Run `nx.pagerank(kg.module_graph)` → assign `pagerank_score` to each `ModuleNode`
      - Run `nx.strongly_connected_components()` → flag nodes in cycles
      - Flag dead code: nodes with `in_degree == 0` and `is_public_api == False`
   f. Attach `change_velocity_30d` from the git velocity map to each `ModuleNode`
2. Returns the populated `KnowledgeGraph`

Verify: run Surveyor on `jaffle_shop`, print top 5 modules by PageRank. They should be the most-imported utility/config files.

---

## Step 10 — Hydrologist Agent

**Goal**: Orchestrate Steps 6–8 into the complete data lineage graph.

Create `src/agents/hydrologist.py`:
1. `Hydrologist.analyze(repo_path: Path, kg: KnowledgeGraph)`:
   a. Detect repo type: look for `dbt_project.yml` (dbt), `dag` files with Airflow imports (Airflow), or generic Python
   b. Run `SQLLineageAnalyzer` on all `.sql` files → `list[SQLDependency]`
   c. Run `DbtSchemaParser` / `AirflowDAGParser` on all config files → topology nodes
   d. Run `PythonDataFlowAnalyzer` on all `.py` files → data flow calls
   e. Merge into `kg.lineage_graph`: add all `DatasetNode`s and `TransformationNode`s; add `PRODUCES` and `CONSUMES` edges
2. `blast_radius(kg: KnowledgeGraph, node_name: str) -> list[str]`:
   - BFS/DFS over `kg.lineage_graph` starting from `node_name`, traversing `PRODUCES` edges downstream
   - Returns list of all affected dataset and module names with their `source_file`
3. `find_sources(kg: KnowledgeGraph) -> list[DatasetNode]` — nodes with `in_degree == 0`
4. `find_sinks(kg: KnowledgeGraph) -> list[DatasetNode]` — nodes with `out_degree == 0`

Verify: run Hydrologist on `jaffle_shop`, call `find_sources()` and `find_sinks()`. Sources should be raw seed files; sinks should be final model outputs. Cross-check with `dbt ls`.

---

## Step 11 — Interim Checkpoint

**Goal**: Validate that Steps 1–10 produce correct artifacts before building LLM-dependent components.

1. Wire up `src/orchestrator.py` to run Surveyor → Hydrologist in sequence
2. Update `src/cli.py` `analyze` subcommand to call the orchestrator and save outputs to `.cartography/`
3. Run against `jaffle_shop`: confirm `.cartography/module_graph.json` and `.cartography/lineage_graph.json` are produced
4. Manually inspect the lineage graph and verify it matches dbt's own DAG
5. Run against Apache Airflow example DAGs: confirm pipeline topology is extracted
6. Write `RECONNAISSANCE.md` (manual Day-One answers for your chosen target) — this becomes the ground truth for accuracy measurement
7. Prepare Interim PDF Report

---

## Step 12 — Semanticist Agent

**Goal**: Add LLM-powered purpose extraction, documentation drift detection, and domain clustering.

Create `src/agents/semanticist.py`:
1. `ContextWindowBudget`:
   - `estimate_tokens(text: str) -> int` — use `len(text) // 4` as a fast approximation
   - `track_spend(tokens: int, model: str)` — accumulates total token spend
   - `select_model(token_count: int) -> str` — returns `"gemini-flash"` for < 4000 tokens, `"gpt-4"` or `"claude"` for synthesis tasks
2. `generate_purpose_statement(module: ModuleNode, source_code: str) -> str`:
   - Prompt: "Given the following Python source code, write a 2–3 sentence description of what this module does in terms of business function, not implementation detail. Do NOT use the docstring — derive your answer from the code."
   - After generating: read the existing docstring (if present) and compare. If semantically different, set `module.documentation_drift = True` and log the discrepancy.
3. `cluster_into_domains(modules: list[ModuleNode]) -> dict[str, str]`:
   - Embed all `purpose_statement` strings using `sentence-transformers`
   - Run k-means with `k=6` (adjustable)
   - For each cluster centroid, call the LLM: "Given these module descriptions, what is the business domain name for this cluster?" → returns a label like `"ingestion"`, `"transformation"`, `"serving"`, `"monitoring"`
   - Assign `domain_cluster` on each `ModuleNode`
4. `answer_day_one_questions(kg: KnowledgeGraph) -> dict[str, str]`:
   - Build a synthesis context from: top 10 modules by PageRank, all sources/sinks, high-velocity files, circular dependency list
   - Single LLM call (expensive model): "Given this architectural summary, answer these five questions with specific file:line evidence: [questions]"
   - Parse response into a structured dict

Verify: run on `jaffle_shop`, print the five Day-One answers. At least 3 should be verifiable by manual inspection.

---

## Step 13 — Archivist Agent

**Goal**: Produce all final output artifacts from the populated knowledge graph.

Create `src/agents/archivist.py`:
1. `generate_CODEBASE_md(kg: KnowledgeGraph, day_one_answers: dict) -> str`:
   Render a Markdown string with these exact sections:
   - `## Architecture Overview` — 1 paragraph synthesized from top-5 PageRank modules and domain cluster map
   - `## Critical Path` — top 5 modules by PageRank with their purpose statements and file paths
   - `## Data Sources & Sinks` — tables from `find_sources()` and `find_sinks()` with storage type and owner
   - `## Known Debt` — list of: circular dependency cycles (file paths), documentation drift flags (file + docstring vs. actual)
   - `## High-Velocity Files` — top 10 files by `change_velocity_30d` with commit counts
   - `## Module Purpose Index` — full table: `module_path | domain | purpose_statement`
2. `generate_onboarding_brief(day_one_answers: dict, kg: KnowledgeGraph) -> str`:
   - Structured Markdown with each of the 5 FDE questions as a heading, the answer as body text, and evidence citations as `> File: src/..., Line: 42` blockquotes
3. `log_trace(action: str, agent: str, evidence_source: str, confidence: float)`:
   - Appends a JSONL line to `.cartography/cartography_trace.jsonl` with timestamp, agent, action, evidence_source, confidence_level
4. `build_semantic_index(modules: list[ModuleNode], output_dir: Path)`:
   - Embed all `purpose_statement` strings into ChromaDB collection at `output_dir/semantic_index/`
   - Store `module_path` as metadata on each embedding

Verify: run full pipeline on `jaffle_shop`, open `CODEBASE.md` and read it — it should be immediately useful as a context document injected into an AI session.

---

## Step 14 — Navigator Agent (LangGraph)

**Goal**: A conversational query agent with four tools backed by the knowledge graph.

Create `src/agents/navigator.py`:
1. Load `KnowledgeGraph` from `.cartography/` at startup
2. Load ChromaDB semantic index from `.cartography/semantic_index/`
3. Define four LangGraph tools:
   - `find_implementation(concept: str) -> str`:
     - Embed `concept` and query ChromaDB for top-5 nearest module purpose statements
     - Return: module paths, purpose statements, and file:line evidence
     - Cite method: `[semantic search]`
   - `trace_lineage(dataset: str, direction: str) -> str`:
     - `direction` is `upstream` or `downstream`
     - BFS from `dataset` node in the lineage graph in the appropriate direction
     - Return: ordered list of nodes with `source_file` and `line_range` per edge
     - Cite method: `[graph traversal]`
   - `blast_radius(module_path: str) -> str`:
     - Call `hydrologist.blast_radius()` for the given node
     - Return: all downstream dependents with file:line citations, sorted by dependency depth
     - Cite method: `[graph traversal]`
   - `explain_module(path: str) -> str`:
     - Load source code from disk
     - Call LLM with full source for a detailed explanation
     - Cross-reference with `ModuleNode.purpose_statement` from the graph
     - Cite method: `[LLM inference from source]`
4. Build the LangGraph `StateGraph` with a ReAct loop: the agent selects tools based on the user's query, calls them, and formats the final answer
5. Update `src/cli.py` `query` subcommand to start an interactive REPL backed by the Navigator agent

Verify: from the CLI, ask "What produces the orders table?" and confirm the answer cites the correct dbt model file and line.

---

## Step 15 — Incremental Update Mode

**Goal**: Re-analyze only changed files on subsequent runs rather than the full codebase.

Add to `src/orchestrator.py`:
1. `get_last_run_commit(output_dir: Path) -> str | None`:
   - Read the last entry in `cartography_trace.jsonl` and extract the `repo_commit` field
2. `get_changed_files(repo_path: Path, since_commit: str) -> list[Path]`:
   - Run `git diff --name-only <since_commit> HEAD` via `gitpython`
3. In `analyze()`: if `output_dir` already has a `module_graph.json`, load it, get changed files, re-analyze only those files, and merge the updated nodes back into the existing graph
4. Add `update` subcommand to `src/cli.py` that calls incremental mode

Verify: run full analysis, make a trivial commit to the target repo, run `update`, and confirm only the changed file is re-analyzed.

---

## Step 16 — Visualization Dashboard

**Goal**: A Streamlit multi-page app that renders all knowledge graph outputs as interactive, clickable views.

Create `src/dashboard/app.py`:

**Page 1 — System Map**:
1. Load `module_graph.json` into NetworkX
2. Build a PyVis `Network`, add nodes sized by PageRank score, colored by `domain_cluster`
3. Node hover tooltip: purpose statement + complexity score + change velocity
4. Render in Streamlit via `st.components.v1.html(net.generate_html())`
5. Sidebar filter: filter by domain cluster or minimum PageRank threshold

**Page 2 — Data Lineage Graph**:
1. Load `lineage_graph.json` into NetworkX
2. Build PyVis `Network`, nodes colored by type (source=green, transformation=blue, sink=red)
3. Edge labels: transformation type + source file (truncated)
4. Node hover: schema snapshot + upstream/downstream count

**Page 3 — Blast Radius**:
1. Dropdown selector: all modules and datasets
2. On selection: call `hydrologist.blast_radius()`, extract the subgraph, render it in PyVis with downstream nodes highlighted red
3. Below the graph: table of affected files with file:line citations

**Page 4 — Domain Architecture Map**:
1. Build Plotly treemap: parent = domain cluster, child = module, size = lines of code, color = change velocity
2. Click a module to show its purpose statement in a sidebar panel

**Page 5 — Git Velocity Heatmap**:
1. Load velocity data from `module_graph.json` node attributes
2. Build Plotly heatmap: Y-axis = top 30 files, X-axis = weekly buckets, value = commit count
3. Highlight the top 20% (high-velocity core) with a distinct color band

**Page 6 — Navigator Chat**:
1. `st.chat_input` box backed by the Navigator LangGraph agent
2. Render tool invocations as collapsed expanders: `> Used: trace_lineage(dataset="orders", direction="upstream")`
3. Render file:line citations as inline code links

Add `dashboard` subcommand to `src/cli.py` that runs `streamlit run src/dashboard/app.py -- --cartography-dir <path>`

Verify: launch dashboard against `jaffle_shop` cartography output. All six pages load without errors. Hover a node in the System Map and confirm the purpose statement appears.

---

## Step 17 — Final Integration & Hardening

**Goal**: The system runs end-to-end on any public GitHub URL without crashing.

1. Test against all required target codebases:
   - `dbt jaffle_shop` — verify lineage graph matches dbt's own DAG
   - Apache Airflow example DAGs — verify pipeline topology is correct
   - Own Week 1 repo — compare generated `CODEBASE.md` with hand-written `ARCHITECTURE_NOTES.md`
2. Harden error handling throughout:
   - Any file that fails to parse: log to `cartography_trace.jsonl` with `confidence=0.0`, skip it, never raise
   - Any LLM call that fails: retry once, then fall back to an empty `purpose_statement` with a warning flag
   - Any missing `.cartography/` directory: create it automatically
3. Final `README.md`:
   - Installation: `uv sync`
   - Analyze a GitHub URL: `python src/cli.py analyze https://github.com/dbt-labs/jaffle-shop.git`
   - Interactive query: `python src/cli.py query --cartography-dir .cartography/`
   - Launch dashboard: `python src/cli.py dashboard --cartography-dir .cartography/`
4. Prepare Final PDF Report and record the 6-minute demo video

---

## Build Order Summary

| Step | Deliverable | Depends On |
|---|---|---|
| 1 | Project scaffold + CLI skeleton | — |
| 2 | Pydantic schemas | 1 |
| 3 | KnowledgeGraph store | 2 |
| 4 | Repo ingester + git velocity | 3 |
| 5 | Tree-sitter analyzer | 4 |
| 6 | SQL lineage analyzer | 5 |
| 7 | DAG config parser | 5 |
| 8 | Python data flow analyzer | 5 |
| 9 | Surveyor agent | 4, 5 |
| 10 | Hydrologist agent | 6, 7, 8, 9 |
| **11** | **Interim checkpoint** | **9, 10** |
| 12 | Semanticist agent | 10 |
| 13 | Archivist agent | 12 |
| 14 | Navigator agent | 13 |
| 15 | Incremental update mode | 14 |
| 16 | Visualization dashboard | 13, 14 |
| **17** | **Final integration & hardening** | **all** |
