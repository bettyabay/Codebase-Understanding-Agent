from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class StorageType(str, Enum):
    TABLE = "table"
    FILE = "file"
    STREAM = "stream"
    API = "api"


class Language(str, Enum):
    PYTHON = "python"
    SQL = "sql"
    YAML = "yaml"
    NOTEBOOK = "notebook"
    JAVASCRIPT = "javascript"
    UNKNOWN = "unknown"


class ModuleNode(BaseModel):
    path: str
    language: Language = Language.PYTHON
    purpose_statement: str = ""
    domain_cluster: str = ""
    complexity_score: int = 0
    change_velocity_30d: int = 0
    is_dead_code_candidate: bool = False
    last_modified: Optional[datetime] = None
    pagerank_score: float = 0.0
    in_cycle: bool = False
    documentation_drift: bool = False
    lines_of_code: int = 0
    imports: list[str] = Field(default_factory=list)
    exports: list[str] = Field(default_factory=list)


class DatasetNode(BaseModel):
    name: str
    storage_type: StorageType = StorageType.TABLE
    schema_snapshot: dict = Field(default_factory=dict)
    freshness_sla: str = ""
    owner: str = ""
    is_source_of_truth: bool = False
    source_file: str = ""
    line_number: int = 0


class FunctionNode(BaseModel):
    qualified_name: str
    parent_module: str
    signature: str = ""
    purpose_statement: str = ""
    call_count_within_repo: int = 0
    is_public_api: bool = False
    line_start: int = 0
    line_end: int = 0


class TransformationNode(BaseModel):
    name: str
    source_datasets: list[str] = Field(default_factory=list)
    target_datasets: list[str] = Field(default_factory=list)
    transformation_type: str = "unknown"
    source_file: str = ""
    line_range: tuple[int, int] = (0, 0)
    sql_query_if_applicable: str = ""
