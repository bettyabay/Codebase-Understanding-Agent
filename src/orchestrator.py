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
from src.analyzers.repo_ingester import clone_if_remote
from src.graph.knowledge_graph import KnowledgeGraph

logger = logging.getLogger(__name__)
console = Console()


class Orchestrator:
    """Wires all four agents in sequence and manages incremental updates."""

    def __init__(self, output_dir: Optional[Path] = None) -> None:
        self.output_dir = output_dir or Path(".cartography")
        self.surveyor = Surveyor()
        self.hydrologist = Hydrologist()
        self.semanticist = Semanticist()
        self.archivist = Archivist()

    def analyze(
        self,
        repo_path: str,
        skip_llm: bool = False,
        incremental: bool = False,
    ) -> KnowledgeGraph:
        """Run the full analysis pipeline: Surveyor -> Hydrologist -> Semanticist -> Archivist."""

        resolved_path = clone_if_remote(repo_path, self.output_dir.parent / "repo_cache")
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

        # Phase 2: Hydrologist
        self.archivist.log_trace("hydrologist_start", "hydrologist", "data_flow_analysis", 1.0, self.output_dir)
        self.hydrologist.analyze(repo_path, kg)
        self.archivist.log_trace("hydrologist_complete", "hydrologist", "data_flow_analysis", 1.0, self.output_dir,
                                 extra={"datasets": len(kg.all_datasets())})

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

        console.print(f"\n[bold green]Analysis complete![/bold green] Output: [bold]{self.output_dir}[/bold]")
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
