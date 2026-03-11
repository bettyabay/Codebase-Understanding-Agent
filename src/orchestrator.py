from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Optional

from rich.console import Console

from src.agents.archivist import Archivist
from src.agents.hydrologist import Hydrologist
from src.agents.semanticist import Semanticist
from src.agents.surveyor import Surveyor
from src.analyzers.repo_ingester import clone_if_remote, derive_repo_name, extract_git_velocity_weekly
from src.graph.knowledge_graph import KnowledgeGraph

logger = logging.getLogger(__name__)
console = Console()


class Orchestrator:
    """Wires all four agents in sequence and manages incremental updates."""

    # Root directories — individual repo outputs live under <root>/<repo_name>/
    CACHE_ROOT = Path("repo_cache")
    CARTOGRAPHY_ROOT = Path(".cartography")

    def __init__(self, output_dir: Optional[Path] = None) -> None:
        # output_dir, if given explicitly, is the fully-resolved per-repo directory.
        # If omitted, it is resolved later once the repo name is known.
        self._explicit_output_dir = output_dir
        self.surveyor = Surveyor()
        self.hydrologist = Hydrologist()
        self.semanticist = Semanticist()
        self.archivist = Archivist()

    def analyze(
        self,
        repo_path: str,
        repo_name: Optional[str] = None,
        skip_llm: bool = False,
        incremental: bool = False,
    ) -> KnowledgeGraph:
        """Run the full analysis pipeline: Surveyor -> Hydrologist -> Semanticist -> Archivist."""
        name = repo_name or derive_repo_name(repo_path)
        self.output_dir = self._explicit_output_dir or (self.CARTOGRAPHY_ROOT / name)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        resolved_path = clone_if_remote(repo_path, self.CACHE_ROOT)
        repo_commit = self._get_current_commit(resolved_path)

        if incremental and (self.output_dir / "module_graph.json").exists():
            kg = self._run_incremental(resolved_path, repo_commit)
        else:
            kg = self._run_full(resolved_path, repo_commit, skip_llm)

        return kg

    def _run_full(self, repo_path: Path, repo_commit: str, skip_llm: bool) -> KnowledgeGraph:
        console.print(f"\n[bold]Brownfield Cartographer[/bold] - analyzing [cyan]{repo_path}[/cyan]")

        kg = KnowledgeGraph()

        # Phase 1: Surveyor
        self.archivist.log_trace("surveyor_start", "surveyor", "static_analysis", 1.0, self.output_dir)
        self.surveyor.analyze(repo_path, kg)
        self.archivist.log_trace("surveyor_complete", "surveyor", "static_analysis", 1.0, self.output_dir,
                                 extra={"modules": len(kg.all_modules())})
        self._flush_parse_errors(kg)

        # Phase 2: Hydrologist
        self.archivist.log_trace("hydrologist_start", "hydrologist", "data_flow_analysis", 1.0, self.output_dir)
        self.hydrologist.analyze(repo_path, kg)
        self.archivist.log_trace("hydrologist_complete", "hydrologist", "data_flow_analysis", 1.0, self.output_dir,
                                 extra={"datasets": len(kg.all_datasets())})
        self._flush_parse_errors(kg)

        # Bridge SQL/dbt lineage into the module graph so the System Map shows
        # SQL model dependencies (e.g. orders.sql → stg_orders.sql).
        self._bridge_sql_lineage_to_modules(kg)

        # Phase 3: Semanticist (optional - requires API key)
        day_one_answers: dict = {}
        if not skip_llm:
            self.archivist.log_trace("semanticist_start", "semanticist", "llm_analysis", 0.9, self.output_dir)
            day_one_answers = self.semanticist.analyze(kg, repo_path)
            self.archivist.log_trace("semanticist_complete", "semanticist", "llm_analysis", 0.9, self.output_dir)

        # Phase 4: Archivist
        self.archivist.produce_artifacts(kg, self.output_dir, day_one_answers, repo_commit)

        # Build semantic index (if purpose statements were generated)
        if any(m.purpose_statement for m in kg.all_modules()):
            self.archivist.build_semantic_index(kg, self.output_dir)

        # Save weekly git velocity data for 2D heatmap
        files, weeks, matrix = extract_git_velocity_weekly(repo_path)
        weekly_path = self.output_dir / "git_velocity_weekly.json"
        weekly_path.write_text(
            json.dumps({"files": files, "weeks": weeks, "matrix": matrix}),
            encoding="utf-8",
        )

        console.print(f"\n[bold green]Analysis complete![/bold green] Output: [bold]{self.output_dir}[/bold]")
        console.print(f"  Repo cache: [dim]repo_cache/{self.output_dir.name}[/dim]")
        _print_summary(kg)
        return kg

    def _run_incremental(self, repo_path: Path, repo_commit: str) -> KnowledgeGraph:
        """Re-analyze only files changed since the last run."""
        console.print("[bold]Incremental update[/bold] - loading existing graph...")
        kg = KnowledgeGraph.load(self.output_dir)

        last_commit = self._get_last_run_commit()
        if not last_commit:
            console.print("  No previous commit found - falling back to full analysis")
            return self._run_full(repo_path, repo_commit, skip_llm=True)

        changed_files = self._get_changed_files(repo_path, last_commit)
        if not changed_files:
            console.print("  [green]No changes since last run.[/green]")
            return kg

        console.print(f"  Re-analyzing {len(changed_files)} changed files...")
        for changed_path in changed_files:
            full_path = repo_path / changed_path
            if not full_path.exists():
                continue
            suffix = full_path.suffix.lower()
            if suffix == ".py":
                from src.analyzers.repo_ingester import FileRecord, LANGUAGE_MAP
                record = FileRecord(
                    path=full_path,
                    language=LANGUAGE_MAP.get(suffix, "unknown"),  # type: ignore
                    size_bytes=full_path.stat().st_size,
                )
                self.surveyor._analyze_python_file(record, kg, {}, set())
                self.hydrologist._ingest_python_dataflow(full_path, kg)
            elif suffix == ".sql":
                self.hydrologist._ingest_sql_file(full_path, kg)

        self.surveyor._compute_pagerank(kg)
        self.archivist.produce_artifacts(kg, self.output_dir, {}, repo_commit)
        return kg

    def _get_current_commit(self, repo_path: Path) -> str:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo_path, capture_output=True, text=True, timeout=10
            )
            return result.stdout.strip()
        except Exception:
            return ""

    def _get_last_run_commit(self) -> Optional[str]:
        trace_path = self.output_dir / "cartography_trace.jsonl"
        if not trace_path.exists():
            return None
        try:
            lines = trace_path.read_text(encoding="utf-8").strip().splitlines()
            for line in reversed(lines):
                entry = json.loads(line)
                if "repo_commit" in entry and entry["repo_commit"]:
                    return entry["repo_commit"]
        except Exception:
            pass
        return None

    def _bridge_sql_lineage_to_modules(self, kg) -> None:
        """Wire SQL model dependencies (from lineage) as ImportEdges in the module graph.

        This makes SQL-only repos (e.g. dbt) show a meaningful graph in the System Map.
        """
        from pathlib import Path as _Path
        from src.models.edges import ImportEdge
        from src.agents.surveyor import _to_module_key

        # Map each dataset name to the module key of the SQL file that produces it
        dataset_to_module: dict[str, str] = {}
        for transform in kg.all_transformations():
            if transform.transformation_type != "sql" or not transform.source_file:
                continue
            module_key = _to_module_key(_Path(transform.source_file))
            for target_ds in transform.target_datasets:
                dataset_to_module[target_ds] = module_key

        # For each SQL transformation, create ImportEdges from consuming module → producing module
        added = 0
        for transform in kg.all_transformations():
            if transform.transformation_type != "sql" or not transform.source_file:
                continue
            consumer_key = _to_module_key(_Path(transform.source_file))
            for src_ds in transform.source_datasets:
                producer_key = dataset_to_module.get(src_ds)
                if producer_key and producer_key != consumer_key:
                    kg.add_import_edge(ImportEdge(
                        source_module=consumer_key,
                        target_module=producer_key,
                    ))
                    added += 1

        if added:
            console.print(f"  [dim]Bridged {added} SQL lineage -> module import edges[/dim]")

    def _flush_parse_errors(self, kg) -> None:
        """Write accumulated parse errors to the trace file (confidence=0.0) and clear the list."""
        for err in kg.parse_errors:
            self.archivist.log_trace(
                action="parse_error",
                agent=err["agent"],
                evidence_source=err["file"],
                confidence=0.0,
                output_dir=self.output_dir,
                extra={"error": err["error"]},
            )
        kg.parse_errors.clear()

    def _get_changed_files(self, repo_path: Path, since_commit: str) -> list[Path]:
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", since_commit, "HEAD"],
                cwd=repo_path, capture_output=True, text=True, timeout=15
            )
            return [Path(line.strip()) for line in result.stdout.splitlines() if line.strip()]
        except Exception:
            return []


def _print_summary(kg: KnowledgeGraph) -> None:
    stats = kg.stats()
    console.print(f"\n  [dim]Modules:[/dim]        {stats['modules']}")
    console.print(f"  [dim]Datasets:[/dim]       {stats['datasets']}")
    console.print(f"  [dim]Transformations:[/dim] {stats['transformations']}")
    console.print(f"  [dim]Import edges:[/dim]   {stats['module_edges']}")
    console.print(f"  [dim]Lineage edges:[/dim]  {stats['lineage_edges']}")
