from __future__ import annotations

import os
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


def clone_if_remote(repo_path: str, target_dir: Optional[Path] = None) -> Path:
    """Clone a GitHub URL to a temp directory, or return the local path unchanged."""
    if repo_path.startswith(("http://", "https://", "git@")):
        dest = target_dir or Path(tempfile.mkdtemp(prefix="cartographer_"))
        if dest.exists():
            if (dest / ".git").exists():
                console.print(f"[cyan]Using existing clone[/cyan] at {dest}")
                return dest
            if any(dest.iterdir()):
                dest = dest.parent / f"{dest.name}_{int(datetime.now().timestamp())}"
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
