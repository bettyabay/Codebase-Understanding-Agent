from __future__ import annotations

import logging
from pathlib import Path

import networkx as nx
from rich.console import Console
from rich.progress import Progress, TextColumn

from src.analyzers.repo_ingester import (
    FileRecord,
    extract_git_velocity,
    identify_high_velocity_files,
    walk_repo,
)
from src.analyzers.tree_sitter_analyzer import PythonASTAnalyzer
from src.graph.knowledge_graph import KnowledgeGraph
from src.models.edges import ImportEdge
from src.models.nodes import Language, ModuleNode

logger = logging.getLogger(__name__)
console = Console()

_py_analyzer = PythonASTAnalyzer()


class Surveyor:
    """Agent 1: Static Structure Analyst.

    Builds the module graph with imports, PageRank, circular dependency detection,
    dead code flagging, and git change velocity.
    """

    def analyze(self, repo_path: Path, kg: KnowledgeGraph) -> KnowledgeGraph:
        console.print("[bold cyan]Surveyor[/bold cyan] - scanning repository structure...")

        files = walk_repo(repo_path)
        velocity = extract_git_velocity(repo_path, days=30)
        high_velocity = identify_high_velocity_files(velocity)

        python_files = [f for f in files if f.language == Language.PYTHON]
        sql_files = [f for f in files if f.language == Language.SQL]
        yaml_files = [f for f in files if f.language == Language.YAML]

        console.print(
            f"  Found [yellow]{len(files)}[/yellow] source files "
            f"([yellow]{len(python_files)}[/yellow] Python, "
            f"[yellow]{len(sql_files)}[/yellow] SQL, "
            f"[yellow]{len(yaml_files)}[/yellow] YAML)"
        )

        with Progress(TextColumn("{task.description}"), console=console) as progress:
            task = progress.add_task("Parsing modules...", total=len(python_files))

            for record in python_files:
                self._analyze_python_file(record, kg, velocity, high_velocity)
                progress.advance(task)

        # Add SQL and YAML files as lightweight module nodes so they appear
        # in the System Map and are eligible for PageRank and velocity scoring.
        for record in sql_files + yaml_files:
            self._add_file_as_module(record, kg, velocity, high_velocity)

        self._compute_pagerank(kg)
        self._detect_cycles(kg)
        self._flag_dead_code(kg)

        stats = kg.stats()
        console.print(
            f"  [green]OK[/green] Surveyor complete - "
            f"{stats['modules']} modules, {stats['module_edges']} import edges"
        )
        return kg

    def _analyze_python_file(
        self,
        record: FileRecord,
        kg: KnowledgeGraph,
        velocity: dict[str, int],
        high_velocity: set[str],
    ) -> None:
        try:
            source = record.path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning("Cannot read %s: %s", record.path, exc)
            kg.record_parse_error(str(record.path), "surveyor", str(exc))
            return

        rel_path = str(record.path)
        rel_key = _to_module_key(record.path)

        imports = _py_analyzer.extract_imports(source)
        functions = _py_analyzer.extract_functions(source, module_path=rel_key)
        complexity = _py_analyzer.compute_complexity(source)
        loc = _py_analyzer.count_lines(source)
        exports = [f.qualified_name.split("::")[-1] for f in functions if f.is_public_api]

        rel_str = str(record.path.name)
        vel = velocity.get(rel_str, 0)

        module = ModuleNode(
            path=rel_key,
            language=Language.PYTHON,
            complexity_score=complexity,
            change_velocity_30d=vel,
            last_modified=record.last_modified,
            lines_of_code=loc,
            imports=imports,
            exports=exports,
        )
        kg.add_module(module)

        for func in functions:
            kg.add_function(func)

        for imp in imports:
            normalized = imp.replace(".", "/")
            kg.add_import_edge(ImportEdge(source_module=rel_key, target_module=normalized))

    def _add_file_as_module(
        self,
        record: FileRecord,
        kg: KnowledgeGraph,
        velocity: dict[str, int],
        high_velocity: set[str],
    ) -> None:
        """Add a SQL or YAML file as a lightweight ModuleNode (no AST parsing)."""
        rel_key = _to_module_key(record.path)
        if rel_key in {m.path for m in kg.all_modules()}:
            return  # already registered by Python parser
        try:
            loc = len(record.path.read_text(encoding="utf-8", errors="replace").splitlines())
        except OSError as exc:
            kg.record_parse_error(str(record.path), "surveyor", str(exc))
            return
        vel = velocity.get(record.path.name, velocity.get(str(record.path), 0))
        module = ModuleNode(
            path=rel_key,
            language=record.language,
            change_velocity_30d=vel,
            last_modified=record.last_modified,
            lines_of_code=loc,
        )
        kg.add_module(module)

    def _compute_pagerank(self, kg: KnowledgeGraph) -> None:
        if kg.module_graph.number_of_nodes() == 0:
            return
        try:
            scores = nx.pagerank(kg.module_graph, weight="weight")
        except nx.PowerIterationFailedConvergence:
            scores = {n: 1.0 / len(kg.module_graph) for n in kg.module_graph.nodes()}

        for node_id, score in scores.items():
            if node_id in kg._modules:
                kg._modules[node_id].pagerank_score = score
                kg.module_graph.nodes[node_id]["pagerank_score"] = score

    def _detect_cycles(self, kg: KnowledgeGraph) -> None:
        sccs = list(nx.strongly_connected_components(kg.module_graph))
        for scc in sccs:
            if len(scc) > 1:
                for node_id in scc:
                    if node_id in kg._modules:
                        kg._modules[node_id].in_cycle = True
                        kg.module_graph.nodes[node_id]["in_cycle"] = True

        cycle_count = sum(1 for scc in sccs if len(scc) > 1)
        if cycle_count:
            console.print(f"  [yellow]WARN[/yellow]  {cycle_count} circular dependency groups detected")

    def _flag_dead_code(self, kg: KnowledgeGraph) -> None:
        dead = 0
        for node_id in kg.module_graph.nodes():
            if kg.module_graph.in_degree(node_id) == 0:
                if node_id in kg._modules:
                    mod = kg._modules[node_id]
                    if not mod.exports:
                        mod.is_dead_code_candidate = True
                        kg.module_graph.nodes[node_id]["is_dead_code_candidate"] = True
                        dead += 1
        if dead:
            console.print(f"  [dim]{dead} dead-code candidates flagged[/dim]")

    def top_modules_by_pagerank(self, kg: KnowledgeGraph, n: int = 10) -> list[ModuleNode]:
        return sorted(kg.all_modules(), key=lambda m: m.pagerank_score, reverse=True)[:n]


_ROOT_ANCHORS = {"src", "lib", "app", "models", "seeds", "macros", "analyses"}
_STRIP_EXTENSIONS = {".py", ".sql", ".yml", ".yaml"}


def _to_module_key(path: Path) -> str:
    """Normalize a file path to a slash-separated module key, stripping the extension."""
    parts = path.parts
    try:
        src_idx = next(i for i, p in enumerate(parts) if p in _ROOT_ANCHORS)
        parts = parts[src_idx:]
    except StopIteration:
        parts = parts[-3:] if len(parts) > 3 else parts
    key = "/".join(parts)
    for ext in _STRIP_EXTENSIONS:
        if key.endswith(ext):
            key = key[: -len(ext)]
            break
    return key
