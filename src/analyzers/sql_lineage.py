from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Jinja2 / dbt ref() patterns
_DBT_REF_RE = re.compile(r"\{\{\s*ref\s*\(\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}")
_DBT_SOURCE_RE = re.compile(r"\{\{\s*source\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}")
_JINJA_RE = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.DOTALL)

DIALECT_HINTS: dict[str, str] = {
    "bigquery": "bigquery",
    "bq": "bigquery",
    "snowflake": "snowflake",
    "redshift": "redshift",
    "duckdb": "duckdb",
    "spark": "spark",
    "postgres": "postgres",
    "postgresql": "postgres",
    "mysql": "mysql",
}


class SQLDependency(BaseModel):
    target_table: str
    source_tables: list[str]
    cte_names: list[str] = []
    source_file: str = ""
    dialect: str = "default"
    dbt_refs: list[str] = []
    dbt_sources: list[str] = []


class SQLLineageAnalyzer:
    """Extracts table-level lineage from SQL and dbt model files using sqlglot."""

    def detect_dialect(self, file_path: Path) -> str:
        path_str = str(file_path).lower()
        for hint, dialect in DIALECT_HINTS.items():
            if hint in path_str:
                return dialect
        return "default"

    def extract_dependencies(self, sql: str, dialect: str = "default", target_table: str = "") -> SQLDependency:
        """Parse SQL and return all upstream table dependencies."""
        try:
            import sqlglot
            import sqlglot.expressions as exp
        except ImportError:
            logger.error("sqlglot not installed")
            return SQLDependency(target_table=target_table, source_tables=[])

        # Extract dbt ref() and source() before stripping Jinja
        dbt_refs = _DBT_REF_RE.findall(sql)
        dbt_sources = [f"{s}.{t}" for s, t in _DBT_SOURCE_RE.findall(sql)]

        # Replace dbt Jinja with placeholder identifiers so sqlglot can parse
        clean_sql = sql
        for ref_name in dbt_refs:
            clean_sql = re.sub(
                r"\{\{\s*ref\s*\(\s*['\"]" + re.escape(ref_name) + r"['\"]\s*\)\s*\}\}",
                ref_name,
                clean_sql,
            )
        for match in _DBT_SOURCE_RE.finditer(sql):
            clean_sql = clean_sql.replace(match.group(0), f"{match.group(1)}__{match.group(2)}")
        # Strip remaining Jinja
        clean_sql = _JINJA_RE.sub("placeholder_expr", clean_sql)

        source_tables: list[str] = []
        cte_names: list[str] = []

        try:
            parse_dialect = None if dialect == "default" else dialect
            statements = sqlglot.parse(clean_sql, dialect=parse_dialect, error_level=sqlglot.ErrorLevel.WARN)
        except Exception as exc:
            logger.debug("sqlglot parse error: %s", exc)
            statements = []

        for statement in statements:
            if statement is None:
                continue

            # Collect CTE names so we don't treat them as real tables
            for cte in statement.find_all(exp.CTE):
                alias = cte.alias
                if alias:
                    cte_names.append(alias)

            # Collect all FROM / JOIN table references
            for table in statement.find_all(exp.Table):
                name = table.name
                if not name or name in cte_names or name == "placeholder_expr":
                    continue
                db = table.db
                full_name = f"{db}.{name}" if db else name
                if full_name not in source_tables:
                    source_tables.append(full_name)

        # Merge dbt refs into source_tables
        for ref in dbt_refs:
            if ref not in source_tables:
                source_tables.append(ref)
        for src in dbt_sources:
            # Use __ to match the Jinja substitution format (schema__table),
            # preventing ecom__raw_x and ecom_raw_x from becoming two separate nodes.
            canonical = src.replace(".", "__")
            if canonical not in source_tables:
                source_tables.append(canonical)

        return SQLDependency(
            target_table=target_table,
            source_tables=source_tables,
            cte_names=cte_names,
            dialect=dialect,
            dbt_refs=dbt_refs,
            dbt_sources=dbt_sources,
        )

    def analyze_file(self, path: Path) -> list[SQLDependency]:
        """Analyze a SQL file and return its dependencies."""
        try:
            sql = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning("Cannot read %s: %s", path, exc)
            return []

        dialect = self.detect_dialect(path)

        # For dbt models: target table = file stem
        target_table = path.stem

        dep = self.extract_dependencies(sql, dialect=dialect, target_table=target_table)
        dep.source_file = str(path)
        return [dep]

    def build_lineage_pairs(self, dependencies: list[SQLDependency]) -> list[tuple[str, str, str]]:
        """Convert SQLDependency list to (source, target, source_file) tuples."""
        pairs: list[tuple[str, str, str]] = []
        for dep in dependencies:
            for src in dep.source_tables:
                if src != dep.target_table:
                    pairs.append((src, dep.target_table, dep.source_file))
        return pairs
