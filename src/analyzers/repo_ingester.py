from __future__ import annotations

import os
import re
import subprocess
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from pydantic import BaseModel
from rich.console import Console

from src.models.nodes import Language

console = Console()

SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env",
    ".tox", "dist", "build", ".eggs", "*.egg-info", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "site-packages",
}

LANGUAGE_MAP: dict[str, Language] = {
    ".py": Language.PYTHON,
    ".sql": Language.SQL,
    ".yml": Language.YAML,
    ".yaml": Language.YAML,
    ".ipynb": Language.NOTEBOOK,
    ".js": Language.JAVASCRIPT,
    ".ts": Language.JAVASCRIPT,
}

MAX_FILE_SIZE_BYTES = 1_000_000  # 1 MB


class FileRecord(BaseModel):
    path: Path
    language: Language
    size_bytes: int
    last_modified: Optional[datetime] = None

    model_config = {"arbitrary_types_allowed": True}


def derive_repo_name(repo_path: str) -> str:
    """Derive a short filesystem-safe name from a repo URL or local path.

    Examples:
      https://github.com/dbt-labs/jaffle_shop  → jaffle_shop
      https://github.com/apache/airflow.git    → airflow
      /home/user/my-project                    → my_project
    """
    name = repo_path.rstrip("/")
    if name.endswith(".git"):
        name = name[:-4]
    name = name.split("/")[-1]
    name = re.sub(r"[^\w]", "_", name).lower().strip("_")
    return name or "unknown_repo"


def clone_if_remote(repo_path: str, cache_dir: Optional[Path] = None) -> Path:
    """Clone a GitHub URL into cache_dir/<repo_name>/, or return the local path unchanged.

    The destination is always a named subdirectory so multiple repos can coexist
    under the same cache root without overwriting each other.
    """
    if repo_path.startswith(("http://", "https://", "git@")):
        repo_name = derive_repo_name(repo_path)
        root = cache_dir or Path(tempfile.mkdtemp(prefix="cartographer_"))
        dest = root / repo_name
        if dest.exists() and (dest / ".git").exists():
            console.print(f"[cyan]Using existing clone[/cyan] at {dest}")
            return dest
        dest.mkdir(parents=True, exist_ok=True)
        console.print(f"[cyan]Cloning[/cyan] {repo_path} -> {dest}")
        try:
            import git
            git.Repo.clone_from(repo_path, dest, depth=100)
        except Exception as exc:
            console.print(f"[red]Clone failed: {exc}[/red]")
            raise
        return dest
    return Path(repo_path).resolve()


def walk_repo(root: Path) -> list[FileRecord]:
    """Walk the repo and return all analyzable source files."""
    records: list[FileRecord] = []

    for dirpath, dirnames, filenames in os.walk(root):
        # Prune skip dirs in-place so os.walk doesn't recurse into them
        dirnames[:] = [
            d for d in dirnames
            if d not in SKIP_DIRS and not d.startswith(".")
        ]

        for filename in filenames:
            filepath = Path(dirpath) / filename
            suffix = filepath.suffix.lower()

            if suffix not in LANGUAGE_MAP:
                continue

            try:
                size = filepath.stat().st_size
            except OSError:
                continue

            if size > MAX_FILE_SIZE_BYTES:
                continue

            # Quick binary check
            if _is_binary(filepath):
                continue

            try:
                mtime = datetime.fromtimestamp(filepath.stat().st_mtime)
            except OSError:
                mtime = None

            records.append(
                FileRecord(
                    path=filepath,
                    language=LANGUAGE_MAP[suffix],
                    size_bytes=size,
                    last_modified=mtime,
                )
            )

    return records


def _is_binary(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            chunk = f.read(1024)
        return b"\x00" in chunk
    except OSError:
        return True


def extract_git_velocity(root: Path, days: int = 30) -> dict[str, int]:
    """Return {relative_file_path: commit_count} for commits in the last `days` days."""
    velocity: dict[str, int] = {}
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    try:
        result = subprocess.run(
            [
                "git", "log",
                f"--since={since}",
                "--name-only",
                "--pretty=format:",
                "--no-merges",
            ],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return velocity

    for line in result.stdout.splitlines():
        line = line.strip()
        if line and not line.startswith("commit"):
            velocity[line] = velocity.get(line, 0) + 1

    return velocity


def identify_high_velocity_files(velocity: dict[str, int], top_pct: float = 0.20) -> set[str]:
    """Return the top `top_pct` of files by commit count (the high-churn core)."""
    if not velocity:
        return set()
    sorted_files = sorted(velocity.items(), key=lambda x: x[1], reverse=True)
    cutoff = max(1, int(len(sorted_files) * top_pct))
    return {f for f, _ in sorted_files[:cutoff]}


def extract_git_velocity_weekly(
    root: Path,
    top_n: int = 20,
    weeks: int = 12,
) -> tuple[list[str], list[str], list[list[int]]]:
    """Return (file_names, week_labels, matrix) for a 2D commit-frequency heatmap.

    week_labels: ISO calendar week strings like "2024-W48" (x-axis, chronological).
    matrix: rows=files (top_n by total commits), cols=weeks (values=commit count).
    """
    from collections import defaultdict

    since = (datetime.now() - timedelta(weeks=weeks)).strftime("%Y-%m-%d")
    try:
        result = subprocess.run(
            [
                "git", "log",
                f"--since={since}",
                "--format=WEEK %ad",
                "--date=format:%G-W%V",
                "--name-only",
                "--no-merges",
            ],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return [], [], []

    if result.returncode != 0:
        return [], [], []

    file_week: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    current_week = ""
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("WEEK "):
            current_week = line[5:]
        elif line and current_week:
            file_week[line][current_week] += 1

    if not file_week:
        return [], [], []

    totals = {f: sum(w.values()) for f, w in file_week.items()}
    top_files = sorted(totals, key=lambda f: totals[f], reverse=True)[:top_n]
    all_weeks = sorted({w for counts in file_week.values() for w in counts})

    matrix = [
        [file_week[f].get(w, 0) for w in all_weeks]
        for f in top_files
    ]
    display_names = [f.split("/")[-1] if "/" in f else f for f in top_files]
    return display_names, all_weeks, matrix
