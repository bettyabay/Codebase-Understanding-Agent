from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv
from rich.console import Console

load_dotenv()

app = typer.Typer(
    name="cartographer",
    help="Brownfield Cartographer — codebase intelligence for FDE onboarding",
    no_args_is_help=True,
)
console = Console()


@app.command()
def analyze(
    repo: str = typer.Argument(..., help="Local path or GitHub URL to analyze"),
    output: Path = typer.Option(Path(".cartography"), "--output", "-o", help="Output directory for artifacts"),
    skip_llm: bool = typer.Option(False, "--skip-llm", help="Skip LLM analysis (faster, no API key needed)"),
    incremental: bool = typer.Option(False, "--incremental", "-i", help="Re-analyze only changed files"),
) -> None:
    """Run the full analysis pipeline: Surveyor → Hydrologist → Semanticist → Archivist."""
    from src.orchestrator import Orchestrator

    orchestrator = Orchestrator(output_dir=output)
    orchestrator.analyze(repo, skip_llm=skip_llm, incremental=incremental)


@app.command()
def query(
    cartography_dir: Path = typer.Option(Path(".cartography"), "--cartography-dir", "-c", help="Path to .cartography/ output"),
    repo: Optional[str] = typer.Option(None, "--repo", help="Original repo path (for source code lookup)"),
) -> None:
    """Start an interactive query session (Navigator agent)."""
    from src.agents.navigator import Navigator
    from src.graph.knowledge_graph import KnowledgeGraph

    if not cartography_dir.exists():
        console.print(f"[red]Error:[/red] {cartography_dir} not found. Run 'analyze' first.")
        raise typer.Exit(1)

    console.print(f"Loading knowledge graph from [cyan]{cartography_dir}[/cyan]…")
    kg = KnowledgeGraph.load(cartography_dir)

    stats = kg.stats()
    console.print(
        f"  Loaded {stats['modules']} modules, {stats['datasets']} datasets, "
        f"{stats['transformations']} transformations"
    )

    repo_path = Path(repo) if repo else None
    navigator = Navigator(kg, repo_path=repo_path, cartography_dir=cartography_dir)
    navigator.repl()


@app.command()
def dashboard(
    cartography_dir: Path = typer.Option(Path(".cartography"), "--cartography-dir", "-c", help="Path to .cartography/ output"),
    port: int = typer.Option(8501, "--port", "-p", help="Streamlit port"),
) -> None:
    """Launch the interactive visualization dashboard."""
    if not cartography_dir.exists():
        console.print(f"[red]Error:[/red] {cartography_dir} not found. Run 'analyze' first.")
        raise typer.Exit(1)

    dashboard_script = Path(__file__).parent / "dashboard" / "app.py"
    console.print(f"Launching dashboard at http://localhost:{port}")
    try:
        subprocess.run(
            [
                sys.executable, "-m", "streamlit", "run",
                str(dashboard_script),
                "--server.port", str(port),
                "--",
                "--cartography-dir", str(cartography_dir),
            ],
            check=True,
        )
    except KeyboardInterrupt:
        pass
    except subprocess.CalledProcessError as exc:
        console.print(f"[red]Dashboard failed:[/red] {exc}")
        raise typer.Exit(1)


@app.command()
def update(
    repo: str = typer.Argument(..., help="Local path or GitHub URL"),
    output: Path = typer.Option(Path(".cartography"), "--output", "-o"),
) -> None:
    """Incrementally re-analyze only files changed since the last run."""
    from src.orchestrator import Orchestrator

    orchestrator = Orchestrator(output_dir=output)
    orchestrator.analyze(repo, incremental=True)


if __name__ == "__main__":
    app()
