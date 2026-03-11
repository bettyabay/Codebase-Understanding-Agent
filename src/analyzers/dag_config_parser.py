from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel

from src.models.nodes import DatasetNode, StorageType

logger = logging.getLogger(__name__)


# ── Shared data structures ────────────────────────────────────────────────────

class TaskNode(BaseModel):
    task_id: str
    operator: str = ""
    source_file: str = ""


class DAGTopology(BaseModel):
    dag_id: str
    tasks: list[TaskNode] = []
    dependencies: list[tuple[str, str]] = []
    source_file: str = ""

    model_config = {"arbitrary_types_allowed": True}


class DbtProject(BaseModel):
    name: str
    model_paths: list[str] = []
    seed_paths: list[str] = []
    profile: str = ""
    source_file: str = ""


# ── dbt parsers ───────────────────────────────────────────────────────────────

class DbtSchemaParser:
    """Parses dbt schema.yml and sources.yml files into DatasetNodes."""

    def parse_schema_yml(self, path: Path) -> list[DatasetNode]:
        """Extract model definitions from a dbt schema.yml."""
        nodes: list[DatasetNode] = []
        try:
            content = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace"))
        except Exception as exc:
            logger.warning("Could not parse %s: %s", path, exc)
            return nodes

        if not isinstance(content, dict):
            return nodes

        for model in content.get("models", []):
            name = model.get("name", "")
            if not name:
                continue
            schema_snapshot = {}
            for col in model.get("columns", []):
                col_name = col.get("name", "")
                col_type = col.get("data_type", "unknown")
                if col_name:
                    schema_snapshot[col_name] = col_type
            nodes.append(
                DatasetNode(
                    name=name,
                    storage_type=StorageType.TABLE,
                    schema_snapshot=schema_snapshot,
                    owner=model.get("meta", {}).get("owner", ""),
                    source_file=str(path),
                )
            )
        return nodes

    def parse_sources_yml(self, path: Path) -> list[DatasetNode]:
        """Extract source table definitions from dbt sources.yml."""
        nodes: list[DatasetNode] = []
        try:
            content = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace"))
        except Exception as exc:
            logger.warning("Could not parse %s: %s", path, exc)
            return nodes

        if not isinstance(content, dict):
            return nodes

        for source in content.get("sources", []):
            source_name = source.get("name", "")
            for table in source.get("tables", []):
                table_name = table.get("name", "")
                if not table_name:
                    continue
                # Use source__table naming to match {{ source('src', 'tbl') }} →
                # ecom__raw_customers format produced by the SQL lineage analyzer.
                canonical_name = f"{source_name}__{table_name}" if source_name else table_name
                freshness = ""
                if "freshness" in table:
                    freshness = str(table["freshness"])
                nodes.append(
                    DatasetNode(
                        name=canonical_name,
                        storage_type=StorageType.TABLE,
                        freshness_sla=freshness,
                        is_source_of_truth=True,
                        source_file=str(path),
                    )
                )
        return nodes


class DbtProjectParser:
    """Parses dbt_project.yml."""

    def parse_dbt_project_yml(self, path: Path) -> Optional[DbtProject]:
        try:
            content = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace"))
        except Exception as exc:
            logger.warning("Could not parse %s: %s", path, exc)
            return None

        if not isinstance(content, dict):
            return None

        return DbtProject(
            name=content.get("name", path.parent.name),
            model_paths=content.get("model-paths", content.get("model_paths", ["models"])),
            seed_paths=content.get("seed-paths", content.get("seed_paths", ["seeds"])),
            profile=content.get("profile", ""),
            source_file=str(path),
        )


# ── Airflow DAG parser ────────────────────────────────────────────────────────

# Patterns for operator instantiation: task_id = SomeOperator(task_id='foo', ...)
_TASK_ID_RE = re.compile(r"task_id\s*=\s*['\"]([^'\"]+)['\"]")
_OPERATOR_RE = re.compile(r"(\w+Operator|\w+Sensor|\w+Hook)\s*\(")
_DAG_ID_RE = re.compile(r"dag_id\s*=\s*['\"]([^'\"]+)['\"]")
# Matches a full chained expression like: a >> b >> c >> d
_DEP_RSHIFT_CHAIN_RE = re.compile(r"[\w_]+(?:\s*>>\s*[\w_]+)+")
_DEP_LSHIFT_RE = re.compile(r"([\w_]+)\s*<<\s*([\w_]+)")
_SET_UPSTREAM_RE = re.compile(r"([\w_]+)\.set_upstream\(\s*([\w_]+)\s*\)")
_SET_DOWNSTREAM_RE = re.compile(r"([\w_]+)\.set_downstream\(\s*([\w_]+)\s*\)")


class AirflowDAGParser:
    """Extracts pipeline topology from Airflow DAG files using AST + regex."""

    def parse_dag_file(self, path: Path) -> Optional[DAGTopology]:
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

        if "from airflow" not in source and "import airflow" not in source:
            return None

        dag_id_match = _DAG_ID_RE.search(source)
        dag_id = dag_id_match.group(1) if dag_id_match else path.stem

        task_ids = _TASK_ID_RE.findall(source)
        operators = _OPERATOR_RE.findall(source)

        tasks = [
            TaskNode(
                task_id=tid,
                operator=operators[i] if i < len(operators) else "",
                source_file=str(path),
            )
            for i, tid in enumerate(task_ids)
        ]

        deps: list[tuple[str, str]] = []

        # Expand chained >> expressions: a >> b >> c → [(a,b), (b,c)]
        for chain_match in _DEP_RSHIFT_CHAIN_RE.finditer(source):
            parts = [p.strip() for p in chain_match.group(0).split(">>")]
            for i in range(len(parts) - 1):
                deps.append((parts[i], parts[i + 1]))
        for m in _DEP_LSHIFT_RE.finditer(source):
            deps.append((m.group(2), m.group(1)))
        for m in _SET_DOWNSTREAM_RE.finditer(source):
            deps.append((m.group(1), m.group(2)))
        for m in _SET_UPSTREAM_RE.finditer(source):
            deps.append((m.group(2), m.group(1)))

        return DAGTopology(
            dag_id=dag_id,
            tasks=tasks,
            dependencies=list(set(deps)),
            source_file=str(path),
        )
