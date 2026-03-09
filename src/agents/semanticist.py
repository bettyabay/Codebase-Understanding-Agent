from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from src.graph.knowledge_graph import KnowledgeGraph
from src.models.nodes import ModuleNode

logger = logging.getLogger(__name__)
console = Console()

FIVE_QUESTIONS = [
    "What is the primary data ingestion path?",
    "What are the 3–5 most critical output datasets or endpoints?",
    "What is the blast radius if the most critical module fails?",
    "Where is the business logic concentrated vs. distributed?",
    "What has changed most frequently in the last 90 days (high-velocity files)?",
]


class ContextWindowBudget:
    """Tracks token usage and routes LLM calls to appropriate models."""

    COST_PER_1K = {"gemini-flash": 0.000075, "gpt-4o-mini": 0.00015, "gpt-4o": 0.005}

    def __init__(self, budget_usd: float = 2.0) -> None:
        self.budget_usd = budget_usd
        self.spent_usd = 0.0
        self.total_tokens = 0

    def estimate_tokens(self, text: str) -> int:
        return len(text) // 4

    def track_spend(self, tokens: int, model: str) -> None:
        self.total_tokens += tokens
        rate = self.COST_PER_1K.get(model, 0.001)
        self.spent_usd += (tokens / 1000) * rate

    def select_model(self, token_count: int, synthesis: bool = False) -> str:
        if synthesis:
            return "gpt-4o-mini"
        return "gemini-flash" if token_count < 8000 else "gpt-4o-mini"

    def budget_remaining(self) -> float:
        return self.budget_usd - self.spent_usd


class Semanticist:
    """Agent 3: LLM-Powered Purpose Analyst.

    Generates purpose statements for modules, detects documentation drift,
    clusters modules into business domains, and answers the Five FDE Day-One Questions.
    """

    def __init__(self) -> None:
        self.budget = ContextWindowBudget()
        self._llm_client = None

    def analyze(self, kg: KnowledgeGraph, repo_path: Optional[Path] = None) -> dict:
        console.print("[bold cyan]Semanticist[/bold cyan] — running LLM analysis…")

        client = self._get_llm_client()
        if client is None:
            console.print("  [yellow]⚠[/yellow]  No LLM API key configured — skipping semantic analysis")
            return {}

        modules = kg.all_modules()
        console.print(f"  Generating purpose statements for {len(modules)} modules…")

        with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as prog:
            t = prog.add_task("Analyzing modules…", total=len(modules))
            for module in modules:
                if repo_path:
                    source = self._read_source(repo_path, module.path)
                    if source:
                        self.generate_purpose_statement(module, source)
                prog.advance(t)

        if len(modules) >= 3:
            self.cluster_into_domains(modules)

        day_one = self.answer_day_one_questions(kg)

        console.print(
            f"  [green]✓[/green] Semanticist complete — "
            f"${self.budget.spent_usd:.4f} spent, {self.budget.total_tokens} tokens"
        )
        return day_one

    def generate_purpose_statement(self, module: ModuleNode, source_code: str) -> str:
        client = self._get_llm_client()
        if client is None:
            return ""

        token_count = self.budget.estimate_tokens(source_code)
        model = self.budget.select_model(token_count)

        # Truncate very large files to stay within context
        if token_count > 6000:
            source_code = source_code[: 6000 * 4]

        prompt = (
            "Given the following Python source code, write a 2–3 sentence description "
            "of what this module does in terms of BUSINESS FUNCTION, not implementation detail. "
            "Do NOT reference the docstring — derive your answer entirely from the code itself.\n\n"
            f"```python\n{source_code}\n```\n\n"
            "Respond with only the description, no preamble."
        )

        try:
            purpose = self._call_llm(prompt, model)
            self.budget.track_spend(token_count + self.budget.estimate_tokens(purpose), model)

            existing_docstring = self._extract_docstring(source_code)
            if existing_docstring and not self._semantically_similar(purpose, existing_docstring):
                module.documentation_drift = True
                logger.info("Documentation drift detected in %s", module.path)

            module.purpose_statement = purpose
            return purpose
        except Exception as exc:
            logger.warning("LLM call failed for %s: %s", module.path, exc)
            module.purpose_statement = ""
            return ""

    def cluster_into_domains(self, modules: list[ModuleNode]) -> dict[str, str]:
        """Embed purpose statements and k-means cluster into business domains."""
        statements = [m.purpose_statement for m in modules if m.purpose_statement]
        if len(statements) < 3:
            return {}

        try:
            from sklearn.cluster import KMeans
            from sklearn.preprocessing import normalize
            import numpy as np

            embeddings = self._embed_texts(statements)
            if embeddings is None:
                return {}

            k = min(6, len(statements))
            kmeans = KMeans(n_clusters=k, random_state=42, n_init=10)
            labels = kmeans.fit_predict(embeddings)

            # Label each cluster by asking the LLM about its centroid members
            cluster_labels: dict[int, str] = {}
            for cluster_id in range(k):
                members = [statements[i] for i, lbl in enumerate(labels) if lbl == cluster_id][:5]
                label = self._infer_domain_label(members)
                cluster_labels[cluster_id] = label

            stmt_idx = 0
            for module in modules:
                if module.purpose_statement:
                    module.domain_cluster = cluster_labels.get(labels[stmt_idx], "general")
                    stmt_idx += 1

            return cluster_labels
        except Exception as exc:
            logger.warning("Domain clustering failed: %s", exc)
            return {}

    def answer_day_one_questions(self, kg: KnowledgeGraph) -> dict[str, str]:
        """Synthesize the Five FDE Day-One Answers from the knowledge graph."""
        client = self._get_llm_client()
        if client is None:
            return {q: "LLM not configured" for q in FIVE_QUESTIONS}

        from src.agents.surveyor import Surveyor
        from src.agents.hydrologist import Hydrologist

        surveyor = Surveyor()
        hydro = Hydrologist()

        top_modules = surveyor.top_modules_by_pagerank(kg, n=10)
        sources = hydro.find_sources(kg)
        sinks = hydro.find_sinks(kg)

        high_vel = sorted(kg.all_modules(), key=lambda m: m.change_velocity_30d, reverse=True)[:10]
        cycles = [m.path for m in kg.all_modules() if m.in_cycle]

        context = (
            f"## Top Modules by Importance (PageRank)\n"
            + "\n".join(f"- {m.path}: {m.purpose_statement or '(no statement)'}" for m in top_modules)
            + f"\n\n## Data Sources (entry points)\n"
            + "\n".join(f"- {s.name} ({s.storage_type})" for s in sources[:10])
            + f"\n\n## Data Sinks (final outputs)\n"
            + "\n".join(f"- {s.name} ({s.storage_type})" for s in sinks[:10])
            + f"\n\n## High-Velocity Files (frequent changes)\n"
            + "\n".join(f"- {m.path}: {m.change_velocity_30d} commits/30d" for m in high_vel)
            + f"\n\n## Circular Dependencies\n"
            + (", ".join(cycles[:10]) if cycles else "None detected")
        )

        questions_str = "\n".join(f"{i+1}. {q}" for i, q in enumerate(FIVE_QUESTIONS))
        prompt = (
            f"You are an expert data engineer analyzing an unfamiliar production codebase.\n\n"
            f"## Architectural Context\n{context}\n\n"
            f"## Questions\nAnswer each of the following five questions with specific evidence. "
            f"For each answer, cite specific file paths and line numbers where possible.\n\n"
            f"{questions_str}\n\n"
            f"Format your response as a JSON object with question numbers as keys (q1..q5)."
        )

        try:
            model = self.budget.select_model(self.budget.estimate_tokens(prompt), synthesis=True)
            response = self._call_llm(prompt, model)
            self.budget.track_spend(self.budget.estimate_tokens(prompt + response), model)

            # Try to parse JSON response
            try:
                start = response.find("{")
                end = response.rfind("}") + 1
                if start >= 0 and end > start:
                    parsed = json.loads(response[start:end])
                    return {FIVE_QUESTIONS[i]: parsed.get(f"q{i+1}", "") for i in range(5)}
            except json.JSONDecodeError:
                pass

            # Fallback: split by question numbers
            answers = {}
            for i, question in enumerate(FIVE_QUESTIONS):
                answers[question] = f"See LLM response (question {i+1}):\n{response}"
            return answers

        except Exception as exc:
            logger.error("Day-one synthesis failed: %s", exc)
            return {q: f"Analysis failed: {exc}" for q in FIVE_QUESTIONS}

    # ── Private helpers ────────────────────────────────────────────────────────

    def _get_llm_client(self):
        if self._llm_client is not None:
            return self._llm_client

        if os.getenv("OPENAI_API_KEY"):
            try:
                from openai import OpenAI
                self._llm_client = OpenAI()
                return self._llm_client
            except ImportError:
                pass

        if os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"):
            try:
                import google.generativeai as genai
                api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
                genai.configure(api_key=api_key)
                self._llm_client = genai
                return self._llm_client
            except ImportError:
                pass

        return None

    def _call_llm(self, prompt: str, model: str) -> str:
        client = self._get_llm_client()
        if client is None:
            return ""

        openai_models = {"gpt-4o", "gpt-4o-mini", "gpt-4", "gpt-3.5-turbo"}

        if model in openai_models or hasattr(client, "chat"):
            actual_model = "gpt-4o-mini" if model == "gemini-flash" else model
            response = client.chat.completions.create(
                model=actual_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1024,
                temperature=0.2,
            )
            return response.choices[0].message.content or ""
        else:
            # Google Generative AI
            try:
                flash_model = client.GenerativeModel("gemini-1.5-flash")
                response = flash_model.generate_content(prompt)
                return response.text or ""
            except Exception as exc:
                logger.warning("Gemini call failed: %s", exc)
                return ""

    def _embed_texts(self, texts: list[str]):
        try:
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer("all-MiniLM-L6-v2")
            return model.encode(texts)
        except Exception as exc:
            logger.warning("Embedding failed: %s", exc)
            return None

    def _infer_domain_label(self, member_descriptions: list[str]) -> str:
        members_str = "\n".join(f"- {d}" for d in member_descriptions)
        prompt = (
            f"Given these module descriptions from the same code cluster:\n{members_str}\n\n"
            f"What is the ONE-WORD or SHORT-PHRASE business domain label for this cluster? "
            f"Examples: ingestion, transformation, serving, monitoring, testing, configuration. "
            f"Respond with only the label."
        )
        try:
            return self._call_llm(prompt, "gemini-flash").strip().lower() or "general"
        except Exception:
            return "general"

    def _semantically_similar(self, text_a: str, text_b: str) -> bool:
        """Rough check: if word overlap > 30%, consider similar enough."""
        words_a = set(text_a.lower().split())
        words_b = set(text_b.lower().split())
        if not words_a or not words_b:
            return True
        overlap = len(words_a & words_b) / min(len(words_a), len(words_b))
        return overlap > 0.3

    def _extract_docstring(self, source: str) -> str:
        lines = source.strip().splitlines()
        in_docstring = False
        docstring_lines = []
        for line in lines[:20]:
            stripped = line.strip()
            if stripped.startswith('"""') or stripped.startswith("'''"):
                if in_docstring:
                    break
                in_docstring = True
                content = stripped.strip('"""').strip("'''").strip()
                if content:
                    docstring_lines.append(content)
                continue
            if in_docstring:
                docstring_lines.append(stripped)
        return " ".join(docstring_lines)

    def _read_source(self, repo_path: Path, module_path: str) -> str:
        candidates = [
            repo_path / (module_path.replace("/", os.sep) + ".py"),
            repo_path / module_path,
        ]
        for candidate in candidates:
            if candidate.exists():
                try:
                    return candidate.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    pass
        return ""
