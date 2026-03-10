"""Unit tests for the Hydrologist agent graph-query methods."""
from __future__ import annotations

import pytest

from src.agents.hydrologist import Hydrologist
from src.graph.knowledge_graph import KnowledgeGraph
from src.models.nodes import DatasetNode, StorageType, TransformationNode


hydro = Hydrologist()


# ── Shared fixture ─────────────────────────────────────────────────────────────

@pytest.fixture()
def lineage_kg() -> KnowledgeGraph:
    """
    Builds the following lineage graph:
        raw_orders → clean_orders → agg_sales → final_report
                                 ↑
                      raw_customers
    """
    kg = KnowledgeGraph()
    for name in ["raw_orders", "raw_customers", "clean_orders", "agg_sales", "final_report"]:
        kg.add_dataset(DatasetNode(name=name, storage_type=StorageType.TABLE))

    kg.add_transformation(TransformationNode(
        name="clean",
        source_datasets=["raw_orders", "raw_customers"],
        target_datasets=["clean_orders"],
    ))
    kg.add_transformation(TransformationNode(
        name="aggregate",
        source_datasets=["clean_orders"],
        target_datasets=["agg_sales"],
    ))
    kg.add_transformation(TransformationNode(
        name="report",
        source_datasets=["agg_sales"],
        target_datasets=["final_report"],
    ))
    return kg


# ── find_sources ──────────────────────────────────────────────────────────────

class TestFindSources:
    def test_returns_nodes_with_no_incoming_edges(self, lineage_kg):
        sources = hydro.find_sources(lineage_kg)
        source_names = {s.name for s in sources}
        assert "raw_orders" in source_names
        assert "raw_customers" in source_names

    def test_derived_nodes_not_included_in_sources(self, lineage_kg):
        sources = hydro.find_sources(lineage_kg)
        source_names = {s.name for s in sources}
        assert "clean_orders" not in source_names
        assert "final_report" not in source_names

    def test_empty_graph_returns_empty(self):
        kg = KnowledgeGraph()
        assert hydro.find_sources(kg) == []

    def test_all_isolated_nodes_are_sources(self):
        kg = KnowledgeGraph()
        kg.add_dataset(DatasetNode(name="iso_a"))
        kg.add_dataset(DatasetNode(name="iso_b"))
        sources = hydro.find_sources(kg)
        assert len(sources) == 2


# ── find_sinks ────────────────────────────────────────────────────────────────

class TestFindSinks:
    def test_returns_nodes_with_no_outgoing_dataset_edges(self, lineage_kg):
        sinks = hydro.find_sinks(lineage_kg)
        sink_names = {s.name for s in sinks}
        assert "final_report" in sink_names

    def test_intermediate_nodes_not_in_sinks(self, lineage_kg):
        sinks = hydro.find_sinks(lineage_kg)
        sink_names = {s.name for s in sinks}
        assert "clean_orders" not in sink_names

    def test_empty_graph_returns_empty(self):
        assert hydro.find_sinks(KnowledgeGraph()) == []


# ── trace_lineage ─────────────────────────────────────────────────────────────

class TestTraceLineage:
    def test_upstream_from_final_finds_all_ancestors(self, lineage_kg):
        result = hydro.trace_lineage(lineage_kg, "final_report", direction="upstream")
        node_names = {r["node"] for r in result}
        assert "agg_sales" in node_names
        assert "aggregate" in node_names

    def test_downstream_from_raw_finds_descendants(self, lineage_kg):
        result = hydro.trace_lineage(lineage_kg, "raw_orders", direction="downstream")
        node_names = {r["node"] for r in result}
        assert "clean_orders" in node_names or "clean" in node_names

    def test_unknown_node_returns_empty(self, lineage_kg):
        result = hydro.trace_lineage(lineage_kg, "nonexistent_table")
        assert result == []

    def test_result_sorted_by_depth(self, lineage_kg):
        result = hydro.trace_lineage(lineage_kg, "raw_orders", direction="downstream")
        depths = [r["depth"] for r in result]
        assert depths == sorted(depths)

    def test_each_result_has_node_and_depth_keys(self, lineage_kg):
        result = hydro.trace_lineage(lineage_kg, "agg_sales", direction="upstream")
        for entry in result:
            assert "node" in entry
            assert "depth" in entry

    def test_start_node_not_in_results(self, lineage_kg):
        result = hydro.trace_lineage(lineage_kg, "agg_sales")
        assert not any(r["node"] == "agg_sales" for r in result)


# ── blast_radius ──────────────────────────────────────────────────────────────

class TestBlastRadius:
    def test_downstream_nodes_returned(self, lineage_kg):
        result = hydro.blast_radius(lineage_kg, "clean_orders")
        node_names = {r["node"] for r in result}
        assert "agg_sales" in node_names or "aggregate" in node_names

    def test_unknown_node_returns_empty(self, lineage_kg):
        assert hydro.blast_radius(lineage_kg, "ghost_table") == []

    def test_result_includes_depth(self, lineage_kg):
        result = hydro.blast_radius(lineage_kg, "raw_orders")
        for entry in result:
            assert "depth" in entry
            assert "node" in entry

    def test_sorted_by_depth(self, lineage_kg):
        result = hydro.blast_radius(lineage_kg, "raw_orders")
        depths = [r["depth"] for r in result]
        assert depths == sorted(depths)

    def test_start_node_not_in_results(self, lineage_kg):
        result = hydro.blast_radius(lineage_kg, "raw_orders")
        assert not any(r["node"] == "raw_orders" for r in result)

    def test_terminal_sink_has_no_blast_radius(self, lineage_kg):
        result = hydro.blast_radius(lineage_kg, "final_report")
        assert result == []


# ── _detect_repo_type ─────────────────────────────────────────────────────────

class TestDetectRepoType:
    def test_dbt_repo_detected_by_dbt_project_yml(self, tmp_path):
        (tmp_path / "dbt_project.yml").write_text("name: myproject\n", encoding="utf-8")
        assert hydro._detect_repo_type(tmp_path) == "dbt"

    def test_airflow_repo_detected_by_import(self, tmp_path):
        src = tmp_path / "dag.py"
        src.write_text("from airflow import DAG\n", encoding="utf-8")
        assert hydro._detect_repo_type(tmp_path) == "airflow"

    def test_generic_repo_when_no_signals(self, tmp_path):
        (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
        assert hydro._detect_repo_type(tmp_path) == "generic"
