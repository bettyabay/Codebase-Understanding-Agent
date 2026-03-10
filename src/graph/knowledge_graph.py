from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import networkx as nx
from networkx.readwrite import json_graph

from src.models.edges import ImportEdge, ProducesEdge, ConsumesEdge, ConfiguresEdge
from src.models.nodes import DatasetNode, FunctionNode, ModuleNode, TransformationNode


class KnowledgeGraph:
    """Central in-memory knowledge graph backed by two NetworkX DiGraphs.

    module_graph: tracks files, their imports, and structural relationships.
    lineage_graph: tracks datasets, transformations, and data flow (PRODUCES/CONSUMES).
    """

    def __init__(self) -> None:
        self.module_graph: nx.DiGraph = nx.DiGraph()
        self.lineage_graph: nx.DiGraph = nx.DiGraph()
        self._modules: dict[str, ModuleNode] = {}
        self._datasets: dict[str, DatasetNode] = {}
        self._transformations: dict[str, TransformationNode] = {}
        self._functions: dict[str, FunctionNode] = {}
        # Parse failures accumulated during analysis; flushed to trace by orchestrator
        self.parse_errors: list[dict] = []

    def record_parse_error(self, file_path: str, agent: str, error: str) -> None:
        """Record a file-level parse failure to be flushed to cartography_trace.jsonl."""
        self.parse_errors.append({"file": file_path, "agent": agent, "error": error})

    # ── Module graph ─────────────────────────────────────────────────────────

    def add_module(self, node: ModuleNode) -> None:
        self._modules[node.path] = node
        self.module_graph.add_node(node.path, **node.model_dump())

    def add_import_edge(self, edge: ImportEdge) -> None:
        if edge.source_module not in self.module_graph:
            self.module_graph.add_node(edge.source_module)
        if edge.target_module not in self.module_graph:
            self.module_graph.add_node(edge.target_module)
        if self.module_graph.has_edge(edge.source_module, edge.target_module):
            self.module_graph[edge.source_module][edge.target_module]["weight"] += 1
        else:
            self.module_graph.add_edge(
                edge.source_module,
                edge.target_module,
                edge_type="IMPORTS",
                weight=edge.import_count,
            )

    def add_function(self, node: FunctionNode) -> None:
        self._functions[node.qualified_name] = node

    def get_module(self, path: str) -> Optional[ModuleNode]:
        return self._modules.get(path)

    def all_modules(self) -> list[ModuleNode]:
        return list(self._modules.values())

    def all_functions(self) -> list[FunctionNode]:
        return list(self._functions.values())

    # ── Lineage graph ─────────────────────────────────────────────────────────

    def add_dataset(self, node: DatasetNode) -> None:
        self._datasets[node.name] = node
        self.lineage_graph.add_node(node.name, node_type="dataset", **node.model_dump())

    def add_transformation(self, node: TransformationNode) -> None:
        self._transformations[node.name] = node
        self.lineage_graph.add_node(node.name, node_type="transformation", **node.model_dump())
        for source in node.source_datasets:
            if source not in self.lineage_graph:
                self.lineage_graph.add_node(source, node_type="dataset", name=source)
            self.lineage_graph.add_edge(
                source,
                node.name,
                edge_type="CONSUMES",
                source_file=node.source_file,
                line_range=node.line_range,
            )
        for target in node.target_datasets:
            if target not in self.lineage_graph:
                self.lineage_graph.add_node(target, node_type="dataset", name=target)
            self.lineage_graph.add_edge(
                node.name,
                target,
                edge_type="PRODUCES",
                source_file=node.source_file,
                line_range=node.line_range,
            )

    def add_configures_edge(self, edge: ConfiguresEdge) -> None:
        self.module_graph.add_edge(
            edge.config_file,
            edge.target,
            edge_type="CONFIGURES",
        )

    def get_dataset(self, name: str) -> Optional[DatasetNode]:
        return self._datasets.get(name)

    def all_datasets(self) -> list[DatasetNode]:
        return list(self._datasets.values())

    def all_transformations(self) -> list[TransformationNode]:
        return list(self._transformations.values())

    # ── Serialization ─────────────────────────────────────────────────────────

    def save(self, output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)

        module_data = json_graph.node_link_data(self.module_graph)
        with open(output_dir / "module_graph.json", "w", encoding="utf-8") as f:
            json.dump(module_data, f, indent=2, default=str)

        lineage_data = json_graph.node_link_data(self.lineage_graph)
        with open(output_dir / "lineage_graph.json", "w", encoding="utf-8") as f:
            json.dump(lineage_data, f, indent=2, default=str)

    @classmethod
    def load(cls, output_dir: Path) -> "KnowledgeGraph":
        kg = cls()

        module_path = output_dir / "module_graph.json"
        if module_path.exists():
            with open(module_path, encoding="utf-8") as f:
                data = json.load(f)
            kg.module_graph = json_graph.node_link_graph(data)
            for node_id, attrs in kg.module_graph.nodes(data=True):
                try:
                    kg._modules[node_id] = ModuleNode(**{**attrs, "path": node_id})
                except Exception:
                    pass

        lineage_path = output_dir / "lineage_graph.json"
        if lineage_path.exists():
            with open(lineage_path, encoding="utf-8") as f:
                data = json.load(f)
            kg.lineage_graph = json_graph.node_link_graph(data)
            for node_id, attrs in kg.lineage_graph.nodes(data=True):
                if attrs.get("node_type") == "dataset":
                    try:
                        kg._datasets[node_id] = DatasetNode(**{**attrs, "name": node_id})
                    except Exception:
                        pass
                elif attrs.get("node_type") == "transformation":
                    try:
                        kg._transformations[node_id] = TransformationNode(
                            **{**attrs, "name": node_id}
                        )
                    except Exception:
                        pass

        return kg

    def stats(self) -> dict:
        return {
            "modules": len(self._modules),
            "datasets": len(self._datasets),
            "transformations": len(self._transformations),
            "functions": len(self._functions),
            "module_edges": self.module_graph.number_of_edges(),
            "lineage_edges": self.lineage_graph.number_of_edges(),
        }
