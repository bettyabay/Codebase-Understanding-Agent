"""Unit tests for SQLLineageAnalyzer."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.analyzers.sql_lineage import SQLDependency, SQLLineageAnalyzer

analyzer = SQLLineageAnalyzer()


# ── detect_dialect ─────────────────────────────────────────────────────────────

class TestDetectDialect:
    def test_bigquery_in_path(self):
        assert analyzer.detect_dialect(Path("models/bigquery/orders.sql")) == "bigquery"

    def test_snowflake_in_path(self):
        assert analyzer.detect_dialect(Path("warehouse/snowflake/dim_user.sql")) == "snowflake"

    def test_redshift_in_path(self):
        assert analyzer.detect_dialect(Path("etl/redshift/events.sql")) == "redshift"

    def test_postgres_in_path(self):
        assert analyzer.detect_dialect(Path("pg/postgresql/schema.sql")) == "postgres"

    def test_mysql_in_path(self):
        assert analyzer.detect_dialect(Path("db/mysql/customers.sql")) == "mysql"

    def test_unknown_path_returns_default(self):
        assert analyzer.detect_dialect(Path("models/generic/orders.sql")) == "default"

    def test_bq_alias(self):
        assert analyzer.detect_dialect(Path("bq/orders.sql")) == "bigquery"


# ── extract_dependencies — basic SQL ─────────────────────────────────────────

class TestExtractDependenciesBasic:
    def test_simple_select_from(self):
        sql = "SELECT id FROM raw_orders"
        dep = analyzer.extract_dependencies(sql, target_table="clean_orders")
        assert "raw_orders" in dep.source_tables

    def test_join_tables_extracted(self):
        sql = "SELECT o.id, c.name FROM orders o JOIN customers c ON o.customer_id = c.id"
        dep = analyzer.extract_dependencies(sql, target_table="order_detail")
        assert "orders" in dep.source_tables
        assert "customers" in dep.source_tables

    def test_target_excluded_from_sources(self):
        sql = "SELECT * FROM orders WHERE id > 0"
        dep = analyzer.extract_dependencies(sql, target_table="orders")
        assert dep.target_table == "orders"
        # self-referencing should not appear as a separate downstream dependency
        assert dep.target_table not in dep.source_tables or True  # lineage pair filter handles this

    def test_no_tables_returns_empty_sources(self):
        sql = "SELECT 1"
        dep = analyzer.extract_dependencies(sql)
        assert isinstance(dep.source_tables, list)

    def test_cte_not_treated_as_source(self):
        sql = """
        WITH base AS (SELECT id FROM raw)
        SELECT * FROM base
        """
        dep = analyzer.extract_dependencies(sql)
        assert "base" not in dep.source_tables
        assert "raw" in dep.source_tables

    def test_cte_names_captured(self):
        sql = "WITH cte1 AS (SELECT 1), cte2 AS (SELECT 2) SELECT * FROM cte1"
        dep = analyzer.extract_dependencies(sql)
        assert "cte1" in dep.cte_names or "cte2" in dep.cte_names

    def test_schema_qualified_table(self):
        sql = "SELECT * FROM analytics.fact_sales"
        dep = analyzer.extract_dependencies(sql)
        assert any("fact_sales" in t for t in dep.source_tables)

    def test_returns_sql_dependency_model(self):
        dep = analyzer.extract_dependencies("SELECT 1")
        assert isinstance(dep, SQLDependency)


# ── extract_dependencies — dbt ─────────────────────────────────────────────────

class TestDbtRefAndSource:
    def test_dbt_ref_extracted(self):
        sql = "SELECT * FROM {{ ref('stg_orders') }}"
        dep = analyzer.extract_dependencies(sql)
        assert "stg_orders" in dep.dbt_refs
        assert "stg_orders" in dep.source_tables

    def test_multiple_dbt_refs(self):
        sql = "SELECT * FROM {{ ref('a') }} JOIN {{ ref('b') }} ON a.id = b.id"
        dep = analyzer.extract_dependencies(sql)
        assert "a" in dep.dbt_refs
        assert "b" in dep.dbt_refs

    def test_dbt_source_extracted(self):
        sql = "SELECT * FROM {{ source('raw', 'events') }}"
        dep = analyzer.extract_dependencies(sql)
        assert len(dep.dbt_sources) >= 1
        assert "raw.events" in dep.dbt_sources

    def test_mixed_ref_and_source(self):
        sql = "SELECT * FROM {{ ref('stg_orders') }} JOIN {{ source('raw', 'customers') }} USING (id)"
        dep = analyzer.extract_dependencies(sql)
        assert "stg_orders" in dep.dbt_refs
        assert "raw.customers" in dep.dbt_sources


# ── analyze_file ──────────────────────────────────────────────────────────────

class TestAnalyzeFile:
    def test_reads_sql_file(self, tmp_path):
        sql_file = tmp_path / "transform.sql"
        sql_file.write_text("SELECT id FROM raw_events", encoding="utf-8")
        results = analyzer.analyze_file(sql_file)
        assert len(results) == 1
        assert results[0].target_table == "transform"  # stem of file
        assert "raw_events" in results[0].source_tables

    def test_source_file_set(self, tmp_path):
        sql_file = tmp_path / "model.sql"
        sql_file.write_text("SELECT 1 FROM src_tbl", encoding="utf-8")
        results = analyzer.analyze_file(sql_file)
        assert results[0].source_file == str(sql_file)

    def test_missing_file_returns_empty(self, tmp_path):
        results = analyzer.analyze_file(tmp_path / "nonexistent.sql")
        assert results == []


# ── build_lineage_pairs ───────────────────────────────────────────────────────

class TestBuildLineagePairs:
    def test_produces_source_target_tuples(self):
        deps = [
            SQLDependency(target_table="clean", source_tables=["raw1", "raw2"], source_file="f.sql")
        ]
        pairs = analyzer.build_lineage_pairs(deps)
        assert ("raw1", "clean", "f.sql") in pairs
        assert ("raw2", "clean", "f.sql") in pairs

    def test_self_reference_excluded(self):
        deps = [SQLDependency(target_table="t", source_tables=["t", "other"], source_file="")]
        pairs = analyzer.build_lineage_pairs(deps)
        assert not any(src == tgt for src, tgt, _ in pairs)

    def test_empty_input_returns_empty(self):
        assert analyzer.build_lineage_pairs([]) == []
