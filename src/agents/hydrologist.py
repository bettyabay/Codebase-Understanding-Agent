from __future__ import annotations

import logging
from collections import deque
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from src.analyzers.dag_config_parser import (
    AirflowDAGParser,
    DbtProjectParser,
    DbtSchemaParser,
)
from src.analyzers.repo_ingester import walk_repo
from src.analyzers.sql_lineage import SQLLineageAnalyzer
from src.analyzers.tree_sitter_analyzer import PythonDataFlowAnalyzer
from src.graph.knowledge_graph import KnowledgeGraph
from src.models.nodes import DatasetNode, Language, StorageType, TransformationNode

logger = logging.getLogger(__name__)
console = Console()

_sql_analyzer = SQLLineageAnalyzer()
_dag_parser = AirflowDAGParser()
_dbt_schema_parser = DbtSchemaParser()
_dbt_project_parser = DbtProjectParser()
_py_flow_analyzer = PythonDataFlowAnalyzer()


class Hydrologist:
    """Agent 2: Data Flow & Lineage Analyst.

    Builds the DataLineageGraph by analyzing SQL, Python, and config files.
    """

    def analyze(self, repo_path: Path, kg: KnowledgeGraph) -> KnowledgeGraph:
        console.print("[bold cyan]Hydrologist[/bold cyan] — building data lineage graph…")

        repo_type = self._detect_repo_type(repo_path)
        console.print(f"  Detected repo type: [yellow]{repo_type}[/yellow]")

        files = walk_repo(repo_path)

        sql_files = [f for f in files if f.language == Language.SQL]
        yaml_files = [f for f in files if f.language == Language.YAML]
        py_files = [f for f in files if f.language == Language.PYTHON]

        # dbt-specific: parse schema/sources before SQL so nodes already exist
        if repo_type == "dbt":
            self._ingest_dbt_metadata(repo_path, yaml_files, kg)

        # SQL lineage
        with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as prog:
            t = prog.add_task(f"Analyzing {len(sql_files)} SQL files…", total=len(sql_files))
            for record in sql_files:
                self._ingest_sql_file(record.path, kg)
                prog.advance(t)

        # Airflow DAG topology
        if repo_type in ("airflow", "generic"):
            self._ingest_airflow_dags(py_files, kg)

        # Python data flow
        with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as prog:
            t = prog.add_task(f"Scanning {len(py_files)} Python files for data I/O…", total=len(py_files))
            for record in py_files:
                self._ingest_python_dataflow(record.path, kg)
                prog.advance(t)

        stats = kg.stats()
        console.print(
            f"  [green]✓[/green] Hydrologist complete — "
            f"{stats['datasets']} datasets, {stats['transformations']} transformations, "
            f"{stats['lineage_edges']} lineage edges"
        )
        return kg

    # ── Private helpers ────────────────────────────────────────────────────────

    def _detect_repo_type(self, repo_path: Path) -> str:
        if (repo_path / "dbt_project.yml").exists():
            return "dbt"
        for f in repo_path.rglob("*.py"):
            try:
                if "from airflow" in f.read_text(encoding="utf-8", errors="replace"):
                    return "airflow"
            except OSError:
                continue
        return "generic"

    def _ingest_dbt_metadata(self, repo_path: Path, yaml_files: list, kg: KnowledgeGraph) -> None:
        dbt_proj = _dbt_project_parser.parse_dbt_project_yml(repo_path / "dbt_project.yml")
        if dbt_proj:
            console.print(f"  dbt project: [bold]{dbt_proj.name}[/bold]")

        for record in yaml_files:
            fname = record.path.name.lower()
            if fname.startswith("schema") or fname == "schema.yml":
                for node in _dbt_schema_parser.parse_schema_yml(record.path):
                    kg.add_dataset(node)
            if fname.startswith("sources") or fname == "sources.yml":
                for node in _dbt_schema_parser.parse_sources_yml(record.path):
                    kg.add_dataset(node)

        # Add seed CSV files as source datasets
        for seed_dir in (repo_path / "seeds", repo_path / "data"):
            if seed_dir.exists():
                for csv_file in seed_dir.glob("*.csv"):
                    kg.add_dataset(DatasetNode(
                        name=csv_file.stem,
                        storage_type=StorageType.FILE,
                        is_source_of_truth=True,
                        source_file=str(csv_file),
                    ))

    def _ingest_sql_file(self, path: Path, kg: KnowledgeGraph) -> None:
        deps_list = _sql_analyzer.analyze_file(path)
        for dep in deps_list:
            if not dep.target_table:
                continue

            # Ensure target dataset node exists
            if not kg.get_dataset(dep.target_table):
                kg.add_dataset(DatasetNode(
                    name=dep.target_table,
                    storage_type=StorageType.TABLE,
                    source_file=dep.source_file,
                ))

            # Ensure source dataset nodes exist
            for src in dep.source_tables:
                if not kg.get_dataset(src):
                    kg.add_dataset(DatasetNode(
                        name=src,
                        storage_type=StorageType.TABLE,
                    ))

            transform_name = f"sql::{dep.target_table}"
            kg.add_transformation(TransformationNode(
                name=transform_name,
                source_datasets=dep.source_tables,
                target_datasets=[dep.target_table],
                transformation_type="sql",
                source_file=dep.source_file,
                sql_query_if_applicable=dep.source_file,
            ))

    def _ingest_airflow_dags(self, py_files: list, kg: KnowledgeGraph) -> None:
        for record in py_files:
            topology = _dag_parser.parse_dag_file(record.path)
            if topology is None:
                continue
            # Add tasks as transformation nodes
            for i, (upstream, downstream) in enumerate(topology.dependencies):
                kg.add_dataset(DatasetNode(name=upstream, storage_type=StorageType.STREAM))
                kg.add_dataset(DatasetNode(name=downstream, storage_type=StorageType.STREAM))
                kg.add_transformation(TransformationNode(
                    name=f"airflow::{topology.dag_id}::{upstream}_to_{downstream}",
                    source_datasets=[upstream],
                    target_datasets=[downstream],
                    transformation_type="airflow_task",
                    source_file=str(record.path),
                ))

    def _ingest_python_dataflow(self, path: Path, kg: KnowledgeGraph) -> None:
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return

        calls = _py_flow_analyzer.analyze(source, str(path))
        reads = [c for c in calls if c.call_type == "read"]
        writes = [c for c in calls if c.call_type == "write"]

        if not reads and not writes:
            return

        transform_name = f"python::{path.name}"

        for call in reads + writes:
            if not kg.get_dataset(call.dataset_name):
                kg.add_dataset(DatasetNode(
                    name=call.dataset_name,
                    storage_type=StorageType.FILE,
                    source_file=str(path),
                    line_number=call.line_number,
                ))

        if reads or writes:
            kg.add_transformation(TransformationNode(
                name=transform_name,
                source_datasets=[c.dataset_name for c in reads],
                target_datasets=[c.dataset_name for c in writes],
                transformation_type="python",
                source_file=str(path),
            ))

    # ── Graph queries ──────────────────────────────────────────────────────────

    def blast_radius(self, kg: KnowledgeGraph, node_name: str) -> list[dict]:
        """BFS downstream from node_name through PRODUCES edges."""
        if node_name not in kg.lineage_graph:
            return []

        visited: set[str] = set()
        queue: deque[tuple[str, int]] = deque([(node_name, 0)])
        results: list[dict] = []

        while queue:
            current, depth = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            if current != node_name:
                edge_data = kg.lineage_graph.get_edge_data(
                    list(kg.lineage_graph.predecessors(current))[0] if kg.lineage_graph.predecessors(current) else node_name,
                    current,
                    default={},
                )
                results.append({
                    "node": current,
                    "depth": depth,
                    "source_file": edge_data.get("source_file", ""),
                    "line_range": edge_data.get("line_range", (0, 0)),
                })
            for successor in kg.lineage_graph.successors(current):
                if successor not in visited:
                    queue.append((successor, depth + 1))

        return sorted(results, key=lambda x: x["depth"])

    def find_sources(self, kg: KnowledgeGraph) -> list[DatasetNode]:
        """Return dataset nodes with no incoming edges (true data sources)."""
        sources = []
        for node_id in kg.lineage_graph.nodes():
            if kg.lineage_graph.in_degree(node_id) == 0:
                dataset = kg.get_dataset(node_id)
                if dataset:
                    sources.append(dataset)
        return sources

    def find_sinks(self, kg: KnowledgeGraph) -> list[DatasetNode]:
        """Return dataset nodes with no outgoing edges (final outputs)."""
        sinks = []
        for node_id in kg.lineage_graph.nodes():
            if kg.lineage_graph.out_degree(node_id) == 0:
                dataset = kg.get_dataset(node_id)
                if dataset:
                    sinks.append(dataset)
        return sinks

    def trace_lineage(
        self, kg: KnowledgeGraph, dataset: str, direction: str = "upstream"
    ) -> list[dict]:
        """BFS upstream or downstream from a dataset node."""
        if dataset not in kg.lineage_graph:
            return []

        visited: set[str] = set()
        queue: deque[tuple[str, int]] = deque([(dataset, 0)])
        results: list[dict] = []

        while queue:
            current, depth = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            if current != dataset:
                results.append({"node": current, "depth": depth})

            neighbors = (
                kg.lineage_graph.predecessors(current)
                if direction == "upstream"
                else kg.lineage_graph.successors(current)
            )
            for neighbor in neighbors:
                if neighbor not in visited:
                    queue.append((neighbor, depth + 1))

        return sorted(results, key=lambda x: x["depth"])
