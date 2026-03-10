"""Unit tests for the KnowledgeGraph class."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.graph.knowledge_graph import KnowledgeGraph
from src.models.edges import ConfiguresEdge, ImportEdge
from src.models.nodes import DatasetNode, FunctionNode, ModuleNode, StorageType, TransformationNode


@pytest.fixture()
def kg() -> KnowledgeGraph:
    return KnowledgeGraph()


@pytest.fixture()
def module_a() -> ModuleNode:
    return ModuleNode(path="src/a", imports=["os"], exports=["run"])


@pytest.fixture()
def module_b() -> ModuleNode:
    return ModuleNode(path="src/b", imports=["src/a"])


# ── Module graph ──────────────────────────────────────────────────────────────

class TestAddModule:
    def test_stores_in_internal_dict(self, kg, module_a):
        kg.add_module(module_a)
        assert kg.get_module("src/a") is module_a

    def test_adds_node_to_module_graph(self, kg, module_a):
        kg.add_module(module_a)
        assert "src/a" in kg.module_graph

    def test_all_modules_returns_all(self, kg, module_a, module_b):
        kg.add_module(module_a)
        kg.add_module(module_b)
        paths = {m.path for m in kg.all_modules()}
        assert paths == {"src/a", "src/b"}

    def test_get_module_missing_returns_none(self, kg):
        assert kg.get_module("nonexistent") is None


class TestAddImportEdge:
    def test_creates_edge_in_graph(self, kg, module_a, module_b):
        kg.add_module(module_a)
        kg.add_module(module_b)
        edge = ImportEdge(source_module="src/b", target_module="src/a")
        kg.add_import_edge(edge)
        assert kg.module_graph.has_edge("src/b", "src/a")

    def test_auto_creates_missing_nodes(self, kg):
        edge = ImportEdge(source_module="phantom_src", target_module="phantom_dst")
        kg.add_import_edge(edge)
        assert "phantom_src" in kg.module_graph
        assert "phantom_dst" in kg.module_graph

    def test_increments_weight_on_duplicate(self, kg):
        e = ImportEdge(source_module="a", target_module="b", import_count=1)
        kg.add_import_edge(e)
        kg.add_import_edge(e)
        assert kg.module_graph["a"]["b"]["weight"] == 2

    def test_initial_weight_from_import_count(self, kg):
        e = ImportEdge(source_module="x", target_module="y", import_count=3)
        kg.add_import_edge(e)
        assert kg.module_graph["x"]["y"]["weight"] == 3


class TestFunctions:
    def test_add_and_retrieve_functions(self, kg):
        fn = FunctionNode(qualified_name="src/a::run", parent_module="src/a")
        kg.add_function(fn)
        functions = kg.all_functions()
        assert len(functions) == 1
        assert functions[0].qualified_name == "src/a::run"


# ── Lineage graph ─────────────────────────────────────────────────────────────

class TestAddDataset:
    def test_stores_dataset(self, kg):
        d = DatasetNode(name="orders")
        kg.add_dataset(d)
        assert kg.get_dataset("orders") is d

    def test_adds_node_to_lineage_graph(self, kg):
        d = DatasetNode(name="events")
        kg.add_dataset(d)
        assert "events" in kg.lineage_graph

    def test_all_datasets(self, kg):
        kg.add_dataset(DatasetNode(name="a"))
        kg.add_dataset(DatasetNode(name="b"))
        assert {d.name for d in kg.all_datasets()} == {"a", "b"}

    def test_get_dataset_missing_returns_none(self, kg):
        assert kg.get_dataset("ghost") is None


class TestAddTransformation:
    def test_edges_created_for_sources_and_targets(self, kg):
        t = TransformationNode(
            name="etl",
            source_datasets=["raw"],
            target_datasets=["clean"],
        )
        kg.add_transformation(t)
        assert kg.lineage_graph.has_edge("raw", "etl")
        assert kg.lineage_graph.has_edge("etl", "clean")

    def test_auto_creates_dataset_nodes_in_lineage_graph(self, kg):
        t = TransformationNode(name="t", source_datasets=["s1"], target_datasets=["s2"])
        kg.add_transformation(t)
        assert "s1" in kg.lineage_graph
        assert "s2" in kg.lineage_graph

    def test_all_transformations(self, kg):
        kg.add_transformation(TransformationNode(name="t1"))
        kg.add_transformation(TransformationNode(name="t2"))
        names = {t.name for t in kg.all_transformations()}
        assert names == {"t1", "t2"}


class TestConfiguresEdge:
    def test_adds_edge_to_module_graph(self, kg):
        e = ConfiguresEdge(config_file="cfg.yml", target="pipeline_dag")
        kg.add_configures_edge(e)
        assert kg.module_graph.has_edge("cfg.yml", "pipeline_dag")


# ── Stats ─────────────────────────────────────────────────────────────────────

class TestStats:
    def test_empty_graph_stats(self, kg):
        s = kg.stats()
        assert s == {
            "modules": 0,
            "datasets": 0,
            "transformations": 0,
            "functions": 0,
            "module_edges": 0,
            "lineage_edges": 0,
        }

    def test_populated_stats(self, kg):
        kg.add_module(ModuleNode(path="m1"))
        kg.add_dataset(DatasetNode(name="d1"))
        kg.add_function(FunctionNode(qualified_name="m1::fn", parent_module="m1"))
        s = kg.stats()
        assert s["modules"] == 1
        assert s["datasets"] == 1
        assert s["functions"] == 1


# ── Serialization ─────────────────────────────────────────────────────────────

class TestSaveLoad:
    def test_round_trip_module_graph(self, kg, tmp_path):
        kg.add_module(ModuleNode(path="src/foo", lines_of_code=42))
        kg.add_import_edge(ImportEdge(source_module="src/foo", target_module="os"))
        kg.save(tmp_path)

        assert (tmp_path / "module_graph.json").exists()
        assert (tmp_path / "lineage_graph.json").exists()

        kg2 = KnowledgeGraph.load(tmp_path)
        assert "src/foo" in kg2.module_graph
        assert kg2.module_graph.has_edge("src/foo", "os")

    def test_round_trip_lineage_graph(self, kg, tmp_path):
        kg.add_dataset(DatasetNode(name="raw_orders", storage_type=StorageType.TABLE))
        kg.add_transformation(TransformationNode(
            name="clean_orders",
            source_datasets=["raw_orders"],
            target_datasets=["final_orders"],
        ))
        kg.save(tmp_path)
        kg2 = KnowledgeGraph.load(tmp_path)
        assert "raw_orders" in kg2.lineage_graph
        assert kg2.lineage_graph.has_edge("raw_orders", "clean_orders")

    def test_load_empty_dir_returns_empty_graph(self, tmp_path):
        kg = KnowledgeGraph.load(tmp_path)
        assert kg.stats()["modules"] == 0

    def test_save_creates_parent_dirs(self, kg, tmp_path):
        nested = tmp_path / "deep" / "nested"
        kg.add_module(ModuleNode(path="x"))
        kg.save(nested)
        assert (nested / "module_graph.json").exists()

    def test_json_is_valid(self, kg, tmp_path):
        kg.add_module(ModuleNode(path="m"))
        kg.save(tmp_path)
        data = json.loads((tmp_path / "module_graph.json").read_text())
        assert "nodes" in data


class TestParseErrors:
    def test_record_and_clear(self):
        kg = KnowledgeGraph()
        assert kg.parse_errors == []

        kg.record_parse_error("src/bad.py", "surveyor", "SyntaxError: invalid syntax")
        kg.record_parse_error("models/broken.sql", "hydrologist", "Unexpected token")

        assert len(kg.parse_errors) == 2
        assert kg.parse_errors[0]["file"] == "src/bad.py"
        assert kg.parse_errors[0]["agent"] == "surveyor"
        assert kg.parse_errors[1]["agent"] == "hydrologist"

        kg.parse_errors.clear()
        assert kg.parse_errors == []
