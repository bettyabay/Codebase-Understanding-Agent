"""Unit tests for dag_config_parser: DbtSchemaParser, DbtProjectParser, AirflowDAGParser."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from src.analyzers.dag_config_parser import (
    AirflowDAGParser,
    DbtProjectParser,
    DbtSchemaParser,
)
from src.models.nodes import StorageType


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def schema_yml(tmp_path) -> Path:
    content = textwrap.dedent("""\
        version: 2
        models:
          - name: stg_orders
            description: Staging orders model
            columns:
              - name: order_id
                data_type: integer
              - name: status
                data_type: varchar
          - name: fct_revenue
            meta:
              owner: analytics_team
    """)
    p = tmp_path / "schema.yml"
    p.write_text(content, encoding="utf-8")
    return p


@pytest.fixture()
def sources_yml(tmp_path) -> Path:
    content = textwrap.dedent("""\
        version: 2
        sources:
          - name: raw
            tables:
              - name: orders
                freshness:
                  warn_after: {count: 24, period: hour}
              - name: customers
    """)
    p = tmp_path / "sources.yml"
    p.write_text(content, encoding="utf-8")
    return p


@pytest.fixture()
def dbt_project_yml(tmp_path) -> Path:
    content = textwrap.dedent("""\
        name: my_dbt_project
        version: '1.0.0'
        profile: default_profile
        model-paths: ['models']
        seed-paths: ['seeds']
    """)
    p = tmp_path / "dbt_project.yml"
    p.write_text(content, encoding="utf-8")
    return p


@pytest.fixture()
def airflow_dag_file(tmp_path) -> Path:
    content = textwrap.dedent("""\
        from airflow import DAG
        from airflow.operators.python import PythonOperator
        from airflow.operators.dummy import DummyOperator

        dag = DAG(dag_id='etl_pipeline', schedule_interval='@daily')

        extract = PythonOperator(task_id='extract_data', python_callable=do_extract, dag=dag)
        transform = PythonOperator(task_id='transform_data', python_callable=do_transform, dag=dag)
        load = DummyOperator(task_id='load_data', dag=dag)

        extract >> transform >> load
    """)
    p = tmp_path / "etl_pipeline.py"
    p.write_text(content, encoding="utf-8")
    return p


# ── DbtSchemaParser ───────────────────────────────────────────────────────────

class TestDbtSchemaParser:
    def setup_method(self):
        self.parser = DbtSchemaParser()

    def test_parse_schema_yml_returns_dataset_nodes(self, schema_yml):
        nodes = self.parser.parse_schema_yml(schema_yml)
        assert len(nodes) == 2

    def test_model_names_extracted(self, schema_yml):
        nodes = self.parser.parse_schema_yml(schema_yml)
        names = {n.name for n in nodes}
        assert "stg_orders" in names
        assert "fct_revenue" in names

    def test_schema_snapshot_from_columns(self, schema_yml):
        nodes = self.parser.parse_schema_yml(schema_yml)
        orders = next(n for n in nodes if n.name == "stg_orders")
        assert "order_id" in orders.schema_snapshot
        assert orders.schema_snapshot["order_id"] == "integer"

    def test_owner_from_meta(self, schema_yml):
        nodes = self.parser.parse_schema_yml(schema_yml)
        revenue = next(n for n in nodes if n.name == "fct_revenue")
        assert revenue.owner == "analytics_team"

    def test_storage_type_is_table(self, schema_yml):
        nodes = self.parser.parse_schema_yml(schema_yml)
        assert all(n.storage_type == StorageType.TABLE for n in nodes)

    def test_source_file_set(self, schema_yml):
        nodes = self.parser.parse_schema_yml(schema_yml)
        assert all(n.source_file == str(schema_yml) for n in nodes)

    def test_invalid_yaml_returns_empty(self, tmp_path):
        bad = tmp_path / "bad.yml"
        bad.write_text(": : : invalid yaml :::", encoding="utf-8")
        nodes = self.parser.parse_schema_yml(bad)
        assert nodes == []

    def test_missing_file_returns_empty(self, tmp_path):
        nodes = self.parser.parse_schema_yml(tmp_path / "ghost.yml")
        assert nodes == []

    def test_parse_sources_yml_returns_dataset_nodes(self, sources_yml):
        nodes = self.parser.parse_sources_yml(sources_yml)
        assert len(nodes) == 2

    def test_sources_are_marked_source_of_truth(self, sources_yml):
        nodes = self.parser.parse_sources_yml(sources_yml)
        assert all(n.is_source_of_truth for n in nodes)

    def test_sources_freshness_sla_captured(self, sources_yml):
        nodes = self.parser.parse_sources_yml(sources_yml)
        orders_node = next(n for n in nodes if n.name == "orders")
        assert orders_node.freshness_sla != ""


# ── DbtProjectParser ──────────────────────────────────────────────────────────

class TestDbtProjectParser:
    def setup_method(self):
        self.parser = DbtProjectParser()

    def test_returns_dbt_project_object(self, dbt_project_yml):
        result = self.parser.parse_dbt_project_yml(dbt_project_yml)
        assert result is not None

    def test_project_name_extracted(self, dbt_project_yml):
        result = self.parser.parse_dbt_project_yml(dbt_project_yml)
        assert result.name == "my_dbt_project"

    def test_profile_extracted(self, dbt_project_yml):
        result = self.parser.parse_dbt_project_yml(dbt_project_yml)
        assert result.profile == "default_profile"

    def test_model_paths_extracted(self, dbt_project_yml):
        result = self.parser.parse_dbt_project_yml(dbt_project_yml)
        assert "models" in result.model_paths

    def test_seed_paths_extracted(self, dbt_project_yml):
        result = self.parser.parse_dbt_project_yml(dbt_project_yml)
        assert "seeds" in result.seed_paths

    def test_missing_file_returns_none(self, tmp_path):
        result = self.parser.parse_dbt_project_yml(tmp_path / "missing.yml")
        assert result is None

    def test_invalid_yaml_returns_none(self, tmp_path):
        bad = tmp_path / "dbt_project.yml"
        bad.write_text(": bad: yaml: :", encoding="utf-8")
        result = self.parser.parse_dbt_project_yml(bad)
        # Returns None or a default DbtProject with parent name
        assert result is None or hasattr(result, "name")


# ── AirflowDAGParser ──────────────────────────────────────────────────────────

class TestAirflowDAGParser:
    def setup_method(self):
        self.parser = AirflowDAGParser()

    def test_returns_dag_topology(self, airflow_dag_file):
        result = self.parser.parse_dag_file(airflow_dag_file)
        assert result is not None

    def test_dag_id_extracted(self, airflow_dag_file):
        result = self.parser.parse_dag_file(airflow_dag_file)
        assert result.dag_id == "etl_pipeline"

    def test_task_ids_extracted(self, airflow_dag_file):
        result = self.parser.parse_dag_file(airflow_dag_file)
        task_ids = {t.task_id for t in result.tasks}
        assert "extract_data" in task_ids
        assert "transform_data" in task_ids
        assert "load_data" in task_ids

    def test_rshift_dependencies_extracted(self, airflow_dag_file):
        result = self.parser.parse_dag_file(airflow_dag_file)
        # extract >> transform and transform >> load should be captured
        assert len(result.dependencies) >= 2

    def test_source_file_set(self, airflow_dag_file):
        result = self.parser.parse_dag_file(airflow_dag_file)
        assert result.source_file == str(airflow_dag_file)

    def test_non_airflow_file_returns_none(self, tmp_path):
        plain_py = tmp_path / "utils.py"
        plain_py.write_text("def helper(): pass", encoding="utf-8")
        result = self.parser.parse_dag_file(plain_py)
        assert result is None

    def test_set_upstream_syntax(self, tmp_path):
        content = textwrap.dedent("""\
            from airflow import DAG
            dag = DAG(dag_id='dep_test')
            task_b.set_upstream(task_a)
        """)
        f = tmp_path / "dag_set_upstream.py"
        f.write_text(content, encoding="utf-8")
        result = self.parser.parse_dag_file(f)
        assert result is not None
        assert ("task_a", "task_b") in result.dependencies

    def test_set_downstream_syntax(self, tmp_path):
        content = textwrap.dedent("""\
            from airflow import DAG
            dag = DAG(dag_id='dep_test')
            task_a.set_downstream(task_b)
        """)
        f = tmp_path / "dag_downstream.py"
        f.write_text(content, encoding="utf-8")
        result = self.parser.parse_dag_file(f)
        assert result is not None
        assert ("task_a", "task_b") in result.dependencies

    def test_missing_file_returns_none(self, tmp_path):
        result = self.parser.parse_dag_file(tmp_path / "missing.py")
        assert result is None

    def test_dag_id_defaults_to_file_stem(self, tmp_path):
        content = "from airflow import DAG\ndag = DAG()\n"
        f = tmp_path / "my_custom_dag.py"
        f.write_text(content, encoding="utf-8")
        result = self.parser.parse_dag_file(f)
        assert result is not None
        assert result.dag_id == "my_custom_dag"
