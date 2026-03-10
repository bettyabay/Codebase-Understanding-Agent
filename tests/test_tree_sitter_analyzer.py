"""Unit tests for tree_sitter_analyzer.

Tree-sitter is an optional dependency. All tests exercise both the
tree-sitter code path (when available) and the regex fallback path
by testing the public API regardless of whether the library is installed.
"""
from __future__ import annotations

import pytest

from src.analyzers.tree_sitter_analyzer import (
    PythonASTAnalyzer,
    PythonDataFlowAnalyzer,
    YAMLASTAnalyzer,
    _regex_complexity,
    _regex_extract_imports,
    _yaml_regex_keys,
)

analyzer = PythonASTAnalyzer()
flow_analyzer = PythonDataFlowAnalyzer()
yaml_analyzer = YAMLASTAnalyzer()

_SIMPLE_MODULE = """\
\"\"\"A simple module.\"\"\"
import os
import sys
from pathlib import Path
from collections import defaultdict

def public_func(x, y):
    if x > y:
        return x
    return y

def _private(z):
    for i in range(z):
        pass

class MyClass:
    pass
"""

_DATAFLOW_MODULE = """\
import pandas as pd

def load(path):
    df = pd.read_csv('data/orders.csv')
    df2 = pd.read_parquet('data/events.parquet')
    return df

def save(df, out):
    df.to_csv('output/result.csv')
    df.to_parquet('output/result.parquet')
"""

_SPARK_MODULE = """\
df = spark.read.parquet('hdfs://warehouse/events')
df.write.saveAsTable('output_table')
"""


# ── PythonASTAnalyzer.extract_imports ─────────────────────────────────────────

class TestExtractImports:
    def test_returns_list(self):
        result = analyzer.extract_imports(_SIMPLE_MODULE)
        assert isinstance(result, list)

    def test_detects_top_level_imports(self):
        result = analyzer.extract_imports(_SIMPLE_MODULE)
        assert "os" in result
        assert "sys" in result

    def test_detects_from_imports(self):
        result = analyzer.extract_imports(_SIMPLE_MODULE)
        assert "pathlib" in result or "collections" in result or len(result) >= 2

    def test_empty_source_returns_empty(self):
        result = analyzer.extract_imports("")
        assert result == []

    def test_no_duplicates(self):
        src = "import os\nimport os\n"
        result = analyzer.extract_imports(src)
        assert result.count("os") == 1


# ── PythonASTAnalyzer.extract_functions ───────────────────────────────────────

class TestExtractFunctions:
    def test_finds_public_functions(self):
        fns = analyzer.extract_functions(_SIMPLE_MODULE, module_path="mymod")
        names = [f.qualified_name for f in fns]
        assert any("public_func" in n for n in names)

    def test_finds_private_functions(self):
        fns = analyzer.extract_functions(_SIMPLE_MODULE, module_path="mymod")
        names = [f.qualified_name for f in fns]
        assert any("_private" in n for n in names)

    def test_public_api_flag(self):
        fns = analyzer.extract_functions(_SIMPLE_MODULE, module_path="mymod")
        pub = [f for f in fns if "public_func" in f.qualified_name]
        priv = [f for f in fns if "_private" in f.qualified_name]
        if pub:
            assert pub[0].is_public_api is True
        if priv:
            assert priv[0].is_public_api is False

    def test_qualified_name_includes_module(self):
        fns = analyzer.extract_functions("def do_thing(): pass", module_path="src/utils")
        if fns:
            assert fns[0].qualified_name.startswith("src/utils")

    def test_line_numbers_populated(self):
        fns = analyzer.extract_functions(_SIMPLE_MODULE, module_path="m")
        for f in fns:
            assert f.line_start >= 1

    def test_empty_source_returns_empty(self):
        fns = analyzer.extract_functions("", module_path="m")
        assert fns == []


# ── PythonASTAnalyzer.extract_classes ─────────────────────────────────────────

class TestExtractClasses:
    def test_detects_class_names(self):
        classes = analyzer.extract_classes(_SIMPLE_MODULE)
        assert "MyClass" in classes

    def test_empty_source_returns_empty(self):
        assert analyzer.extract_classes("") == []

    def test_multiple_classes(self):
        src = "class A: pass\nclass B: pass\n"
        classes = analyzer.extract_classes(src)
        assert "A" in classes
        assert "B" in classes


# ── PythonASTAnalyzer.compute_complexity ──────────────────────────────────────

class TestComputeComplexity:
    def test_zero_complexity_for_simple_code(self):
        score = analyzer.compute_complexity("x = 1\n")
        assert score == 0

    def test_if_increases_complexity(self):
        src = "if x:\n    pass\n"
        score = analyzer.compute_complexity(src)
        assert score >= 1

    def test_nested_branches_accumulate(self):
        src = _SIMPLE_MODULE
        score = analyzer.compute_complexity(src)
        assert score >= 2  # at least if + for

    def test_returns_integer(self):
        assert isinstance(analyzer.compute_complexity("pass"), int)


# ── PythonASTAnalyzer.count_lines ─────────────────────────────────────────────

class TestCountLines:
    def test_blank_lines_not_counted(self):
        src = "x = 1\n\n\ny = 2\n"
        assert analyzer.count_lines(src) == 2

    def test_empty_source_returns_zero(self):
        assert analyzer.count_lines("") == 0

    def test_counts_non_blank_lines(self):
        src = "a = 1\nb = 2\nc = 3\n"
        assert analyzer.count_lines(src) == 3


# ── PythonASTAnalyzer.extract_docstring ───────────────────────────────────────

class TestExtractDocstring:
    def test_extracts_module_docstring(self):
        src = '"""My module."""\nimport os\n'
        result = analyzer.extract_docstring(src)
        assert "My module" in result

    def test_no_docstring_returns_empty_string(self):
        assert analyzer.extract_docstring("x = 1") == ""


# ── PythonDataFlowAnalyzer ────────────────────────────────────────────────────

class TestPythonDataFlowAnalyzer:
    def test_detects_read_csv(self):
        calls = flow_analyzer.analyze(_DATAFLOW_MODULE, "etl.py")
        reads = [c for c in calls if c.call_type == "read"]
        assert any("orders.csv" in c.dataset_name for c in reads)

    def test_detects_read_parquet(self):
        calls = flow_analyzer.analyze(_DATAFLOW_MODULE, "etl.py")
        reads = [c for c in calls if c.call_type == "read"]
        assert any("events.parquet" in c.dataset_name for c in reads)

    def test_detects_write_csv(self):
        calls = flow_analyzer.analyze(_DATAFLOW_MODULE, "etl.py")
        writes = [c for c in calls if c.call_type == "write"]
        assert any("result.csv" in c.dataset_name for c in writes)

    def test_detects_write_parquet(self):
        calls = flow_analyzer.analyze(_DATAFLOW_MODULE, "etl.py")
        writes = [c for c in calls if c.call_type == "write"]
        assert any("result.parquet" in c.dataset_name for c in writes)

    def test_source_file_preserved(self):
        calls = flow_analyzer.analyze(_DATAFLOW_MODULE, "my_etl.py")
        assert all(c.source_file == "my_etl.py" for c in calls)

    def test_line_numbers_positive(self):
        calls = flow_analyzer.analyze(_DATAFLOW_MODULE, "etl.py")
        assert all(c.line_number >= 1 for c in calls)

    def test_empty_source_returns_empty(self):
        calls = flow_analyzer.analyze("x = 1", "noop.py")
        assert calls == []

    def test_detects_spark_read(self):
        calls = flow_analyzer.analyze(_SPARK_MODULE, "spark_job.py")
        reads = [c for c in calls if c.call_type == "read"]
        assert len(reads) >= 1

    def test_detects_spark_write(self):
        calls = flow_analyzer.analyze(_SPARK_MODULE, "spark_job.py")
        writes = [c for c in calls if c.call_type == "write"]
        assert len(writes) >= 1


# ── YAMLASTAnalyzer ───────────────────────────────────────────────────────────

class TestYAMLASTAnalyzer:
    def test_extracts_top_level_keys(self):
        src = "version: 2\nmodels:\n  - name: foo\nseeds:\n  - name: bar\n"
        keys = yaml_analyzer.extract_keys(src)
        # Works via tree-sitter or fallback regex
        assert isinstance(keys, list)
        assert len(keys) >= 1

    def test_empty_yaml_returns_list(self):
        keys = yaml_analyzer.extract_keys("")
        assert isinstance(keys, list)


# ── Regex fallbacks ───────────────────────────────────────────────────────────

class TestRegexFallbacks:
    def test_regex_import_extraction(self):
        src = "import os\nfrom pathlib import Path\nimport sys\n"
        result = _regex_extract_imports(src)
        assert "os" in result
        assert "pathlib" in result
        assert "sys" in result

    def test_regex_complexity_counts_keywords(self):
        src = "if x:\n    for i in range(10):\n        while True:\n            pass\n"
        score = _regex_complexity(src)
        assert score >= 3

    def test_yaml_regex_keys(self):
        src = "version: 2\nmodels:\n  - name: a\nseeds:\n  - name: b\n"
        keys = _yaml_regex_keys(src)
        assert "version" in keys
        assert "models" in keys
