"""Unit tests for Pydantic data models (nodes and edges)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.edges import CallsEdge, ConfiguresEdge, ConsumesEdge, ImportEdge, ProducesEdge
from src.models.nodes import (
    DatasetNode,
    FunctionNode,
    Language,
    ModuleNode,
    StorageType,
    TransformationNode,
)


# ── Enums ─────────────────────────────────────────────────────────────────────

class TestStorageType:
    def test_all_members_exist(self):
        assert StorageType.TABLE == "table"
        assert StorageType.FILE == "file"
        assert StorageType.STREAM == "stream"
        assert StorageType.API == "api"

    def test_is_str_enum(self):
        assert isinstance(StorageType.TABLE, str)


class TestLanguage:
    def test_all_members_exist(self):
        assert Language.PYTHON == "python"
        assert Language.SQL == "sql"
        assert Language.YAML == "yaml"
        assert Language.NOTEBOOK == "notebook"
        assert Language.JAVASCRIPT == "javascript"
        assert Language.UNKNOWN == "unknown"


# ── ModuleNode ─────────────────────────────────────────────────────────────────

class TestModuleNode:
    def test_required_field(self):
        with pytest.raises(ValidationError):
            ModuleNode()  # path is required

    def test_defaults(self):
        m = ModuleNode(path="src/foo.py")
        assert m.language == Language.PYTHON
        assert m.complexity_score == 0
        assert m.change_velocity_30d == 0
        assert m.is_dead_code_candidate is False
        assert m.pagerank_score == 0.0
        assert m.in_cycle is False
        assert m.documentation_drift is False
        assert m.lines_of_code == 0
        assert m.imports == []
        assert m.exports == []
        assert m.last_modified is None

    def test_custom_values(self):
        m = ModuleNode(
            path="src/core.py",
            language=Language.SQL,
            complexity_score=15,
            pagerank_score=0.42,
            imports=["os", "sys"],
            exports=["run"],
            in_cycle=True,
        )
        assert m.language == Language.SQL
        assert m.complexity_score == 15
        assert m.pagerank_score == pytest.approx(0.42)
        assert m.imports == ["os", "sys"]
        assert m.exports == ["run"]
        assert m.in_cycle is True

    def test_model_dump_round_trip(self):
        m = ModuleNode(path="src/a.py", lines_of_code=50)
        data = m.model_dump()
        m2 = ModuleNode(**data)
        assert m2.path == m.path
        assert m2.lines_of_code == 50


# ── DatasetNode ────────────────────────────────────────────────────────────────

class TestDatasetNode:
    def test_required_field(self):
        with pytest.raises(ValidationError):
            DatasetNode()  # name is required

    def test_defaults(self):
        d = DatasetNode(name="orders")
        assert d.storage_type == StorageType.TABLE
        assert d.schema_snapshot == {}
        assert d.freshness_sla == ""
        assert d.owner == ""
        assert d.is_source_of_truth is False
        assert d.source_file == ""
        assert d.line_number == 0

    def test_custom_values(self):
        d = DatasetNode(
            name="events_stream",
            storage_type=StorageType.STREAM,
            owner="data-eng",
            is_source_of_truth=True,
        )
        assert d.storage_type == StorageType.STREAM
        assert d.owner == "data-eng"
        assert d.is_source_of_truth is True


# ── FunctionNode ───────────────────────────────────────────────────────────────

class TestFunctionNode:
    def test_required_fields(self):
        with pytest.raises(ValidationError):
            FunctionNode()

    def test_defaults(self):
        fn = FunctionNode(qualified_name="mod::helper", parent_module="mod")
        assert fn.signature == ""
        assert fn.call_count_within_repo == 0
        assert fn.is_public_api is False
        assert fn.line_start == 0
        assert fn.line_end == 0

    def test_public_api_flag(self):
        fn = FunctionNode(qualified_name="mod::process", parent_module="mod", is_public_api=True)
        assert fn.is_public_api is True


# ── TransformationNode ─────────────────────────────────────────────────────────

class TestTransformationNode:
    def test_required_field(self):
        with pytest.raises(ValidationError):
            TransformationNode()

    def test_defaults(self):
        t = TransformationNode(name="etl_job")
        assert t.source_datasets == []
        assert t.target_datasets == []
        assert t.transformation_type == "unknown"
        assert t.sql_query_if_applicable == ""
        assert t.line_range == (0, 0)

    def test_custom_values(self):
        t = TransformationNode(
            name="agg_sales",
            source_datasets=["raw_orders"],
            target_datasets=["agg_sales_daily"],
            transformation_type="sql",
        )
        assert t.source_datasets == ["raw_orders"]
        assert t.target_datasets == ["agg_sales_daily"]
        assert t.transformation_type == "sql"


# ── Edge models ───────────────────────────────────────────────────────────────

class TestImportEdge:
    def test_required_fields(self):
        with pytest.raises(ValidationError):
            ImportEdge()

    def test_defaults(self):
        e = ImportEdge(source_module="a", target_module="b")
        assert e.import_count == 1

    def test_custom_count(self):
        e = ImportEdge(source_module="a", target_module="b", import_count=5)
        assert e.import_count == 5


class TestProducesEdge:
    def test_required_fields(self):
        with pytest.raises(ValidationError):
            ProducesEdge()

    def test_defaults(self):
        e = ProducesEdge(transformation="t1", dataset="d1")
        assert e.source_file == ""
        assert e.line_range == (0, 0)


class TestConsumesEdge:
    def test_defaults(self):
        e = ConsumesEdge(transformation="t1", dataset="d1")
        assert e.source_file == ""
        assert e.line_range == (0, 0)


class TestCallsEdge:
    def test_required_fields(self):
        with pytest.raises(ValidationError):
            CallsEdge()

    def test_values(self):
        e = CallsEdge(caller="mod_a::fn_x", callee="mod_b::fn_y")
        assert e.caller == "mod_a::fn_x"
        assert e.callee == "mod_b::fn_y"


class TestConfiguresEdge:
    def test_required_fields(self):
        with pytest.raises(ValidationError):
            ConfiguresEdge()

    def test_values(self):
        e = ConfiguresEdge(config_file="airflow.cfg", target="dag_etl")
        assert e.config_file == "airflow.cfg"
        assert e.target == "dag_etl"
