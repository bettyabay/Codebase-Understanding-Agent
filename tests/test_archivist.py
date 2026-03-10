"""Unit tests for the Archivist agent."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agents.archivist import Archivist, FIVE_QUESTIONS
from src.graph.knowledge_graph import KnowledgeGraph
from src.models.nodes import DatasetNode, ModuleNode, StorageType, TransformationNode


archivist = Archivist()


# ── Shared fixtures ───────────────────────────────────────────────────────────

@pytest.fixture()
def populated_kg() -> KnowledgeGraph:
    """KG with modules, datasets, and transformations for document generation tests."""
    kg = KnowledgeGraph()

    m1 = ModuleNode(
        path="src/ingestion",
        purpose_statement="Ingests raw data from S3",
        domain_cluster="ingestion",
        pagerank_score=0.8,
        lines_of_code=120,
        change_velocity_30d=5,
    )
    m2 = ModuleNode(
        path="src/transform",
        purpose_statement="Applies business logic transformations",
        domain_cluster="transform",
        pagerank_score=0.4,
        lines_of_code=80,
        in_cycle=True,
        documentation_drift=True,
    )
    kg.add_module(m1)
    kg.add_module(m2)

    kg.add_dataset(DatasetNode(name="raw_events", storage_type=StorageType.FILE, source_file="s3://bucket/events"))
    kg.add_dataset(DatasetNode(name="clean_events", storage_type=StorageType.TABLE))

    kg.add_transformation(TransformationNode(
        name="clean_step",
        source_datasets=["raw_events"],
        target_datasets=["clean_events"],
        transformation_type="python",
        source_file="src/transform.py",
    ))
    return kg


# ── generate_CODEBASE_md ──────────────────────────────────────────────────────

class TestGenerateCodebaseMd:
    def test_returns_string(self, populated_kg):
        result = archivist.generate_CODEBASE_md(populated_kg, {})
        assert isinstance(result, str)

    def test_contains_main_sections(self, populated_kg):
        result = archivist.generate_CODEBASE_md(populated_kg, {})
        assert "Architecture Overview" in result
        assert "Critical Path" in result
        assert "Data Sources" in result

    def test_module_paths_appear_in_output(self, populated_kg):
        result = archivist.generate_CODEBASE_md(populated_kg, {})
        assert "src/ingestion" in result
        assert "src/transform" in result

    def test_cycle_section_present_when_cycles_exist(self, populated_kg):
        result = archivist.generate_CODEBASE_md(populated_kg, {})
        assert "Circular Dependencies" in result

    def test_drift_section_present_when_drift_exists(self, populated_kg):
        result = archivist.generate_CODEBASE_md(populated_kg, {})
        assert "Documentation Drift" in result

    def test_high_velocity_section_present(self, populated_kg):
        result = archivist.generate_CODEBASE_md(populated_kg, {})
        assert "High-Velocity Files" in result

    def test_domain_map_section_present(self, populated_kg):
        result = archivist.generate_CODEBASE_md(populated_kg, {})
        assert "Domain Architecture Map" in result

    def test_empty_kg_does_not_crash(self):
        result = archivist.generate_CODEBASE_md(KnowledgeGraph(), {})
        assert "No modules analyzed yet" in result

    def test_purpose_index_contains_module_purpose(self, populated_kg):
        result = archivist.generate_CODEBASE_md(populated_kg, {})
        assert "Ingests raw data" in result


# ── generate_onboarding_brief ─────────────────────────────────────────────────

class TestGenerateOnboardingBrief:
    def test_returns_string(self, populated_kg):
        result = archivist.generate_onboarding_brief({}, populated_kg)
        assert isinstance(result, str)

    def test_all_five_questions_present(self, populated_kg):
        result = archivist.generate_onboarding_brief({}, populated_kg)
        for q in FIVE_QUESTIONS:
            assert q in result

    def test_answers_included_when_provided(self, populated_kg):
        answers = {FIVE_QUESTIONS[0]: "The data comes from S3 via Kinesis."}
        result = archivist.generate_onboarding_brief(answers, populated_kg)
        assert "Kinesis" in result

    def test_not_yet_answered_placeholder_used(self, populated_kg):
        result = archivist.generate_onboarding_brief({}, populated_kg)
        assert "_Not yet answered_" in result

    def test_quick_reference_section_present(self, populated_kg):
        result = archivist.generate_onboarding_brief({}, populated_kg)
        assert "Quick Reference" in result

    def test_critical_modules_section_present(self, populated_kg):
        result = archivist.generate_onboarding_brief({}, populated_kg)
        assert "Critical Modules" in result


# ── log_trace ─────────────────────────────────────────────────────────────────

class TestLogTrace:
    def test_creates_jsonl_file(self, tmp_path):
        archivist.log_trace(
            action="test_action",
            agent="test_agent",
            evidence_source="unit_test",
            confidence=0.9,
            output_dir=tmp_path,
        )
        trace_file = tmp_path / "cartography_trace.jsonl"
        assert trace_file.exists()

    def test_trace_entry_is_valid_json(self, tmp_path):
        archivist.log_trace(
            action="parse_module",
            agent="surveyor",
            evidence_source="tree_sitter",
            confidence=1.0,
            output_dir=tmp_path,
        )
        lines = (tmp_path / "cartography_trace.jsonl").read_text().strip().splitlines()
        entry = json.loads(lines[0])
        assert entry["action"] == "parse_module"
        assert entry["agent"] == "surveyor"

    def test_extra_fields_merged_into_entry(self, tmp_path):
        archivist.log_trace(
            action="custom",
            agent="archivist",
            evidence_source="archivist",
            confidence=0.5,
            output_dir=tmp_path,
            extra={"repo_commit": "abc123", "files_processed": 42},
        )
        line = (tmp_path / "cartography_trace.jsonl").read_text().strip()
        entry = json.loads(line)
        assert entry["repo_commit"] == "abc123"
        assert entry["files_processed"] == 42

    def test_multiple_traces_appended(self, tmp_path):
        for i in range(3):
            archivist.log_trace(
                action=f"action_{i}",
                agent="a",
                evidence_source="s",
                confidence=1.0,
                output_dir=tmp_path,
            )
        lines = (tmp_path / "cartography_trace.jsonl").read_text().strip().splitlines()
        assert len(lines) == 3

    def test_none_output_dir_is_noop(self):
        archivist.log_trace(
            action="noop",
            agent="test",
            evidence_source="test",
            confidence=1.0,
            output_dir=None,
        )  # Should not raise

    def test_timestamp_field_present(self, tmp_path):
        archivist.log_trace(
            action="check_ts",
            agent="a",
            evidence_source="s",
            confidence=1.0,
            output_dir=tmp_path,
        )
        entry = json.loads((tmp_path / "cartography_trace.jsonl").read_text().strip())
        assert "timestamp" in entry

    def test_confidence_level_stored(self, tmp_path):
        archivist.log_trace(
            action="check_conf",
            agent="a",
            evidence_source="s",
            confidence=0.75,
            output_dir=tmp_path,
        )
        entry = json.loads((tmp_path / "cartography_trace.jsonl").read_text().strip())
        assert entry["confidence_level"] == pytest.approx(0.75)


# ── produce_artifacts ─────────────────────────────────────────────────────────

class TestProduceArtifacts:
    def test_creates_expected_files(self, populated_kg, tmp_path):
        archivist.produce_artifacts(populated_kg, tmp_path)
        assert (tmp_path / "CODEBASE.md").exists()
        assert (tmp_path / "onboarding_brief.md").exists()
        assert (tmp_path / "module_graph.json").exists()
        assert (tmp_path / "lineage_graph.json").exists()
        assert (tmp_path / "cartography_trace.jsonl").exists()

    def test_codebase_md_is_non_empty(self, populated_kg, tmp_path):
        archivist.produce_artifacts(populated_kg, tmp_path)
        assert (tmp_path / "CODEBASE.md").stat().st_size > 0

    def test_trace_log_contains_full_analysis_entry(self, populated_kg, tmp_path):
        archivist.produce_artifacts(populated_kg, tmp_path)
        lines = (tmp_path / "cartography_trace.jsonl").read_text().strip().splitlines()
        actions = [json.loads(l)["action"] for l in lines]
        assert "full_analysis_complete" in actions

    def test_creates_output_dir_if_missing(self, populated_kg, tmp_path):
        out = tmp_path / "new" / "output"
        archivist.produce_artifacts(populated_kg, out)
        assert out.exists()
