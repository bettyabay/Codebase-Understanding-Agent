"""Unit tests for the Surveyor agent (PageRank, cycles, dead-code flagging)."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.agents.surveyor import Surveyor, _to_module_key
from src.graph.knowledge_graph import KnowledgeGraph
from src.models.edges import ImportEdge
from src.models.nodes import ModuleNode


surveyor = Surveyor()


# ── _to_module_key helper ─────────────────────────────────────────────────────

class TestToModuleKey:
    def test_strips_py_extension(self):
        key = _to_module_key(Path("src/utils/helpers.py"))
        assert not key.endswith(".py")

    def test_normalises_from_src_root(self):
        key = _to_module_key(Path("/home/user/project/src/models/nodes.py"))
        assert "src/models/nodes" == key or key.startswith("src/")

    def test_normalises_from_lib_root(self):
        key = _to_module_key(Path("/project/lib/core/engine.py"))
        assert "lib/core/engine" == key or "core/engine" in key

    def test_no_src_takes_last_three_parts(self):
        key = _to_module_key(Path("a/b/c/d/e.py"))
        parts = key.split("/")
        assert len(parts) <= 3


# ── _compute_pagerank ─────────────────────────────────────────────────────────

class TestComputePageRank:
    def _build_kg_with_chain(self) -> KnowledgeGraph:
        """Creates: a -> b -> c where b is the structural hub."""
        kg = KnowledgeGraph()
        for name in ["a", "b", "c"]:
            kg.add_module(ModuleNode(path=name))
        kg.add_import_edge(ImportEdge(source_module="a", target_module="b"))
        kg.add_import_edge(ImportEdge(source_module="b", target_module="c"))
        return kg

    def test_pagerank_scores_assigned_after_compute(self):
        kg = self._build_kg_with_chain()
        surveyor._compute_pagerank(kg)
        # All modules that are registered should have scores
        for m in kg.all_modules():
            assert m.pagerank_score >= 0

    def test_hub_node_has_higher_pagerank(self):
        """Node 'c' is pointed to by 'b' and should accumulate more score."""
        kg = self._build_kg_with_chain()
        surveyor._compute_pagerank(kg)
        scores = {m.path: m.pagerank_score for m in kg.all_modules()}
        # 'c' has an incoming edge, 'a' has none — c should score >= a
        assert scores.get("c", 0) >= scores.get("a", 0)

    def test_empty_graph_does_not_raise(self):
        kg = KnowledgeGraph()
        surveyor._compute_pagerank(kg)  # should be a no-op

    def test_single_isolated_node(self):
        kg = KnowledgeGraph()
        kg.add_module(ModuleNode(path="solo"))
        surveyor._compute_pagerank(kg)
        assert kg._modules["solo"].pagerank_score >= 0


# ── _detect_cycles ─────────────────────────────────────────────────────────────

class TestDetectCycles:
    def test_flags_modules_in_cycle(self):
        kg = KnowledgeGraph()
        kg.add_module(ModuleNode(path="x"))
        kg.add_module(ModuleNode(path="y"))
        # x -> y and y -> x = cycle
        kg.add_import_edge(ImportEdge(source_module="x", target_module="y"))
        kg.add_import_edge(ImportEdge(source_module="y", target_module="x"))

        surveyor._detect_cycles(kg)

        assert kg._modules["x"].in_cycle is True
        assert kg._modules["y"].in_cycle is True

    def test_no_cycle_not_flagged(self):
        kg = KnowledgeGraph()
        kg.add_module(ModuleNode(path="p"))
        kg.add_module(ModuleNode(path="q"))
        kg.add_import_edge(ImportEdge(source_module="p", target_module="q"))

        surveyor._detect_cycles(kg)

        assert kg._modules["p"].in_cycle is False
        assert kg._modules["q"].in_cycle is False

    def test_larger_cycle_detected(self):
        kg = KnowledgeGraph()
        for n in ["a", "b", "c"]:
            kg.add_module(ModuleNode(path=n))
        # a -> b -> c -> a
        kg.add_import_edge(ImportEdge(source_module="a", target_module="b"))
        kg.add_import_edge(ImportEdge(source_module="b", target_module="c"))
        kg.add_import_edge(ImportEdge(source_module="c", target_module="a"))

        surveyor._detect_cycles(kg)

        assert all(kg._modules[n].in_cycle for n in ["a", "b", "c"])


# ── _flag_dead_code ────────────────────────────────────────────────────────────

class TestFlagDeadCode:
    def test_isolated_no_export_flagged(self):
        kg = KnowledgeGraph()
        kg.add_module(ModuleNode(path="orphan", exports=[]))
        surveyor._flag_dead_code(kg)
        assert kg._modules["orphan"].is_dead_code_candidate is True

    def test_module_with_exports_not_flagged(self):
        kg = KnowledgeGraph()
        kg.add_module(ModuleNode(path="useful", exports=["run"]))
        surveyor._flag_dead_code(kg)
        assert kg._modules["useful"].is_dead_code_candidate is False

    def test_module_with_incoming_edge_not_flagged(self):
        kg = KnowledgeGraph()
        kg.add_module(ModuleNode(path="lib", exports=[]))
        kg.add_module(ModuleNode(path="consumer", exports=[]))
        kg.add_import_edge(ImportEdge(source_module="consumer", target_module="lib"))
        surveyor._flag_dead_code(kg)
        # 'lib' has in_degree=1 so NOT dead code
        assert kg._modules["lib"].is_dead_code_candidate is False


# ── top_modules_by_pagerank ────────────────────────────────────────────────────

class TestTopModulesByPagerank:
    def test_returns_correct_count(self):
        kg = KnowledgeGraph()
        for i in range(5):
            kg.add_module(ModuleNode(path=f"m{i}", pagerank_score=float(i)))
        top = surveyor.top_modules_by_pagerank(kg, n=3)
        assert len(top) == 3

    def test_sorted_descending_by_pagerank(self):
        kg = KnowledgeGraph()
        kg.add_module(ModuleNode(path="low", pagerank_score=0.1))
        kg.add_module(ModuleNode(path="high", pagerank_score=0.9))
        top = surveyor.top_modules_by_pagerank(kg, n=2)
        assert top[0].path == "high"
        assert top[1].path == "low"

    def test_n_larger_than_modules_returns_all(self):
        kg = KnowledgeGraph()
        kg.add_module(ModuleNode(path="only_one"))
        top = surveyor.top_modules_by_pagerank(kg, n=100)
        assert len(top) == 1

    def test_empty_graph_returns_empty(self):
        kg = KnowledgeGraph()
        assert surveyor.top_modules_by_pagerank(kg, n=5) == []


# ── Full analyze pipeline (integration-style with real tmp_path files) ─────────

class TestSurveyorAnalyze:
    def test_analyze_populates_module_graph(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "main.py").write_text("import os\nimport sys\n\ndef run(): pass\n", encoding="utf-8")
        (src / "utils.py").write_text("def helper(): return 1\n", encoding="utf-8")

        kg = KnowledgeGraph()
        surveyor.analyze(tmp_path, kg)

        assert len(kg.all_modules()) >= 2

    def test_analyze_returns_kg(self, tmp_path):
        (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
        kg = KnowledgeGraph()
        result = surveyor.analyze(tmp_path, kg)
        assert result is kg
