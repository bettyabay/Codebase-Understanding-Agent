"""Unit tests for repo_ingester helpers."""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.analyzers.repo_ingester import (
    FileRecord,
    _is_binary,
    derive_repo_name,
    identify_high_velocity_files,
    walk_repo,
)
from src.models.nodes import Language


# ── Helpers ───────────────────────────────────────────────────────────────────

def _write(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")


# ── _is_binary ─────────────────────────────────────────────────────────────────

class TestIsBinary:
    def test_text_file_returns_false(self, tmp_path):
        f = tmp_path / "script.py"
        f.write_text("print('hello')", encoding="utf-8")
        assert _is_binary(f) is False

    def test_null_byte_file_returns_true(self, tmp_path):
        f = tmp_path / "data.bin"
        f.write_bytes(b"some\x00binary\x00data")
        assert _is_binary(f) is True

    def test_empty_file_returns_false(self, tmp_path):
        f = tmp_path / "empty.py"
        f.write_bytes(b"")
        assert _is_binary(f) is False


# ── walk_repo ─────────────────────────────────────────────────────────────────

class TestWalkRepo:
    def test_finds_python_files(self, tmp_path):
        _write(tmp_path / "src" / "main.py", "x = 1")
        records = walk_repo(tmp_path)
        paths = [r.path.name for r in records]
        assert "main.py" in paths

    def test_finds_sql_files(self, tmp_path):
        _write(tmp_path / "models" / "orders.sql", "SELECT 1")
        records = walk_repo(tmp_path)
        assert any(r.path.name == "orders.sql" for r in records)

    def test_finds_yaml_files(self, tmp_path):
        _write(tmp_path / "config" / "airflow.yml", "version: 2")
        records = walk_repo(tmp_path)
        assert any(r.path.suffix == ".yml" for r in records)

    def test_skips_venv_directory(self, tmp_path):
        _write(tmp_path / ".venv" / "site.py", "# should be skipped")
        records = walk_repo(tmp_path)
        assert all(".venv" not in str(r.path) for r in records)

    def test_skips_pycache_directory(self, tmp_path):
        _write(tmp_path / "__pycache__" / "compiled.py", "# skip me")
        records = walk_repo(tmp_path)
        assert all("__pycache__" not in str(r.path) for r in records)

    def test_skips_unknown_extensions(self, tmp_path):
        _write(tmp_path / "readme.md", "# docs")
        _write(tmp_path / "app.py", "pass")
        records = walk_repo(tmp_path)
        assert all(r.path.suffix != ".md" for r in records)

    def test_skips_binary_files(self, tmp_path):
        binary = tmp_path / "lib.so"
        binary.write_bytes(b"ELF\x7f\x00binary")
        # .so is not in LANGUAGE_MAP, but .py with null bytes should be skipped
        py_binary = tmp_path / "corrupt.py"
        py_binary.write_bytes(b"import\x00os")
        records = walk_repo(tmp_path)
        assert not any(r.path.name == "corrupt.py" for r in records)

    def test_correct_language_assignment(self, tmp_path):
        _write(tmp_path / "model.sql", "SELECT 1")
        records = walk_repo(tmp_path)
        sql_records = [r for r in records if r.path.suffix == ".sql"]
        assert all(r.language == Language.SQL for r in sql_records)

    def test_file_record_has_size_and_mtime(self, tmp_path):
        _write(tmp_path / "app.py", "x = 1\n")
        records = walk_repo(tmp_path)
        assert records[0].size_bytes > 0
        assert records[0].last_modified is not None

    def test_empty_repo_returns_empty_list(self, tmp_path):
        records = walk_repo(tmp_path)
        assert records == []

    def test_skips_hidden_directories(self, tmp_path):
        _write(tmp_path / ".hidden_dir" / "secret.py", "pass")
        records = walk_repo(tmp_path)
        assert all(".hidden_dir" not in str(r.path) for r in records)


# ── identify_high_velocity_files ───────────────────────────────────────────────

class TestIdentifyHighVelocityFiles:
    def test_empty_velocity_returns_empty_set(self):
        assert identify_high_velocity_files({}) == set()

    def test_returns_top_20_pct_by_default(self):
        velocity = {f"file_{i}.py": i for i in range(10)}
        result = identify_high_velocity_files(velocity, top_pct=0.20)
        assert len(result) == 2  # 20% of 10
        assert "file_9.py" in result
        assert "file_8.py" in result

    def test_minimum_one_file_returned(self):
        velocity = {"single.py": 5}
        result = identify_high_velocity_files(velocity, top_pct=0.10)
        assert result == {"single.py"}

    def test_respects_custom_percentage(self):
        velocity = {f"f{i}.py": i for i in range(20)}
        result = identify_high_velocity_files(velocity, top_pct=0.50)
        assert len(result) == 10

    def test_higher_commit_count_files_are_in_result(self):
        velocity = {"hot.py": 100, "cold.py": 1}
        result = identify_high_velocity_files(velocity, top_pct=0.50)
        assert "hot.py" in result


# ── clone_if_remote (local path passthrough) ──────────────────────────────────

class TestDeriveRepoName:
    def test_github_url_slug(self):
        assert derive_repo_name("https://github.com/dbt-labs/jaffle-shop.git") == "jaffle_shop"

    def test_strips_git_suffix(self):
        assert derive_repo_name("https://github.com/apache/airflow.git") == "airflow"

    def test_local_path(self):
        name = derive_repo_name("/home/user/my-project")
        assert name == "my_project"

    def test_sanitizes_hyphens(self):
        assert derive_repo_name("https://github.com/org/my-repo") == "my_repo"

    def test_empty_fallback(self):
        assert derive_repo_name("") == "unknown_repo"


class TestCloneIfRemote:
    def test_local_path_is_returned_resolved(self, tmp_path):
        from src.analyzers.repo_ingester import clone_if_remote

        result = clone_if_remote(str(tmp_path))
        assert result == tmp_path.resolve()

    def test_remote_url_clones_into_named_subdir(self, tmp_path):
        from src.analyzers.repo_ingester import clone_if_remote

        mock_repo = MagicMock()
        with patch("git.Repo.clone_from", return_value=mock_repo) as mock_clone:
            cache = tmp_path / "repo_cache"
            result = clone_if_remote("https://github.com/org/repo.git", cache_dir=cache)
            mock_clone.assert_called_once()
            # Result should be cache_dir/<repo_name>, not cache_dir itself
            assert result == cache / "repo"

    def test_existing_clone_is_reused(self, tmp_path):
        from src.analyzers.repo_ingester import clone_if_remote

        # Pre-create a .git directory to simulate existing clone
        dest = tmp_path / "repo"
        (dest / ".git").mkdir(parents=True)
        result = clone_if_remote("https://github.com/org/repo.git", cache_dir=tmp_path)
        assert result == dest


class TestExtractGitVelocityWeekly:
    def test_returns_empty_for_non_git_dir(self, tmp_path):
        from src.analyzers.repo_ingester import extract_git_velocity_weekly

        files, weeks, matrix = extract_git_velocity_weekly(tmp_path)
        assert files == []
        assert weeks == []
        assert matrix == []

    def test_return_types_and_shape(self, tmp_path):
        from src.analyzers.repo_ingester import extract_git_velocity_weekly

        # Init a minimal git repo with one commit so we get real output
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True)
        (tmp_path / "a.py").write_text("x = 1")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True)

        files, weeks, matrix = extract_git_velocity_weekly(tmp_path, top_n=5, weeks=4)

        assert isinstance(files, list)
        assert isinstance(weeks, list)
        assert isinstance(matrix, list)
        if files:
            assert len(matrix) == len(files)
            assert all(len(row) == len(weeks) for row in matrix)
