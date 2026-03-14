from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.progress import Progress, TextColumn

from src.graph.knowledge_graph import KnowledgeGraph
from src.models.nodes import ModuleNode

logger = logging.getLogger(__name__)
console = Console()

_RATE_LIMIT_MARKERS = ("429", "resource_exhausted", "quota", "rate limit", "ratelimit", "too many requests")
_NOT_FOUND_MARKERS = ("404", "not_found", "models/gemini")


def _is_rate_limit(exc: Exception) -> bool:
    """Return True if the exception looks like an API rate-limit / quota error."""
    msg = str(exc).lower()
    return any(marker in msg for marker in _RATE_LIMIT_MARKERS)


def _is_model_not_found(exc: Exception) -> bool:
    """Return True if the exception looks like a missing / invalid model error."""
    msg = str(exc).lower()
    return any(marker in msg for marker in _NOT_FOUND_MARKERS)


def _parse_retry_delay(exc: Exception, default: float = 60.0) -> float:
    """Extract the suggested retry delay in seconds from a 429 error message."""
    import re
    match = re.search(r"retryDelay['\"]?\s*:\s*['\"]?(\d+)s", str(exc))
    if match:
        return float(match.group(1))
    match = re.search(r"retry in\s+([\d.]+)s", str(exc), re.IGNORECASE)
    if match:
        return float(match.group(1))
    return default


FIVE_QUESTIONS = [
    "What is the primary data ingestion path?",
    "What are the 3–5 most critical output datasets or endpoints?",
    "What is the blast radius if the most critical module fails?",
    "Where is the business logic concentrated vs. distributed?",
    "What has changed most frequently in the last 90 days (high-velocity files)?",
]


class ContextWindowBudget:
    """Tracks token usage and routes LLM calls to appropriate models."""

    # gemini-2.0-flash free tier = $0 on Google AI Studio
    # We no longer use OpenAI/GPT models in this project.
    COST_PER_1K = {"gemini-flash": 0.0}

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
        # Single-provider setup: always route budgeting through the Gemini bucket.
        return "gemini-flash"

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
        self._llm_provider: str | None = None  # "gemini" | "openai" | "groq"
        # Separate Gemini client kept alive so we can switch back after cooldown
        self._gemini_client = None
        # Unix timestamp after which Gemini may be tried again (0 = not rate-limited)
        self._gemini_available_at: float = 0.0
        # If we discover during a run that the configured Gemini model is invalid or
        # not available for this account, we mark it disabled to avoid repeated 404s.
        self._gemini_disabled: bool = False

    def analyze(self, kg: KnowledgeGraph, repo_path: Optional[Path] = None) -> dict:
        console.print("[bold cyan]Semanticist[/bold cyan] - running LLM analysis...")

        client = self._get_llm_client()
        if client is None:
            console.print(
                "  [yellow]WARN[/yellow]  No LLM API key found "
                "(GOOGLE_API_KEY / GROQ_API_KEY) — skipping semantic analysis"
            )
            return {}
        console.print(f"  [dim]Using provider: {self._llm_provider}[/dim]")

        modules = kg.all_modules()
        console.print(f"  Generating purpose statements for {len(modules)} modules...")

        with Progress(TextColumn("{task.description}"), console=console) as prog:
            t = prog.add_task("Analyzing modules...", total=len(modules))
            for module in modules:
                source = self._read_source(repo_path, module.path) if repo_path else ""
                if source:
                    self.generate_purpose_statement(module, source)
                prog.advance(t)

        if len(modules) >= 3:
            self.cluster_into_domains(modules)

        day_one = self.answer_day_one_questions(kg)

        console.print(
            f"  [green]OK[/green] Semanticist complete - "
            f"${self.budget.spent_usd:.4f} spent, {self.budget.total_tokens} tokens"
        )
        return day_one

    def generate_purpose_statement(self, module: ModuleNode, source_code: str) -> str:
        if self._get_llm_client() is None:
            return ""

        token_count = self.budget.estimate_tokens(source_code)
        model = self.budget.select_model(token_count)

        # Truncate very large files to stay within context
        if token_count > 6000:
            source_code = source_code[: 6000 * 4]

        lang_str = str(module.language).replace("Language.", "").lower()

        if lang_str == "sql":
            prompt = (
                "Given the following SQL/dbt model, write a 2–3 sentence description "
                "of what this transformation does in terms of BUSINESS FUNCTION. "
                "Mention what input tables it reads from and what output dataset it produces.\n\n"
                f"```sql\n{source_code}\n```\n\n"
                "Respond with only the description, no preamble."
            )
        elif lang_str == "yaml":
            prompt = (
                "Given the following dbt YAML configuration, write a 1–2 sentence description "
                "of what this file configures — e.g. schema definitions, source declarations, "
                "or test coverage — in plain business terms.\n\n"
                f"```yaml\n{source_code}\n```\n\n"
                "Respond with only the description, no preamble."
            )
        elif lang_str == "javascript":
            prompt = (
                "Given the following JavaScript/TypeScript source, write a 2–3 sentence description "
                "of what this module does in terms of BUSINESS FUNCTION, not implementation detail.\n\n"
                f"```javascript\n{source_code}\n```\n\n"
                "Respond with only the description, no preamble."
            )
        else:
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
                logger.info(
                    "Domain clustering disabled: sentence-transformers not available. "
                    "Install `sentence-transformers` to enable the Domain Architecture Map."
                )
                return {}

            # Allow override via env while keeping a sane default range (2–8).
            try:
                k_env = int(os.getenv("SEMANTICIST_NUM_DOMAINS", "6"))
            except ValueError:
                k_env = 6
            k = max(2, min(k_env, 8, len(statements)))
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
            f"Respond with ONLY a valid JSON object. Use exactly these keys: q1, q2, q3, q4, q5. "
            f"Each value must be a string containing the full answer for that question. Example:\n"
            f'{{"q1": "Your answer for question 1...", "q2": "Your answer for question 2...", ...}}'
        )

        try:
            model = self.budget.select_model(self.budget.estimate_tokens(prompt), synthesis=True)
            response = self._call_llm(prompt, model)
            if not response or not response.strip():
                logger.warning("Day-one synthesis: LLM returned empty response")
                return {q: "LLM did not return a response for this question." for q in FIVE_QUESTIONS}
            self.budget.track_spend(self.budget.estimate_tokens(prompt + response), model)

            # Try to parse JSON response (multiple key styles)
            start = response.find("{")
            end = response.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    parsed = json.loads(response[start:end])
                    answers = {}
                    for i in range(5):
                        val = (
                            parsed.get(f"q{i+1}")
                            or parsed.get(str(i + 1))
                            or (parsed.get(str(i + 1)) if isinstance(parsed.get(str(i + 1)), str) else None)
                        )
                        if isinstance(val, str) and val.strip():
                            answers[FIVE_QUESTIONS[i]] = val.strip()
                        else:
                            answers[FIVE_QUESTIONS[i]] = ""
                    if any(answers.values()):
                        return answers
                except json.JSONDecodeError:
                    pass

            # Fallback: show raw response so user at least sees LLM output
            raw = response.strip()
            if len(raw) > 50:
                # Use same raw text for all so the brief isn't repetitive; first question gets the full text
                return {
                    FIVE_QUESTIONS[0]: raw,
                    **{FIVE_QUESTIONS[i]: f"(See consolidated response under question 1.)\n\n{raw[:500]}…" for i in range(1, 5)},
                }
            answers = {}
            for i, question in enumerate(FIVE_QUESTIONS):
                answers[question] = raw if raw else "LLM did not return a response for this question."
            return answers

        except Exception as exc:
            logger.error("Day-one synthesis failed: %s", exc)
            return {q: f"Analysis failed: {exc}" for q in FIVE_QUESTIONS}

    # ── Private helpers ────────────────────────────────────────────────────────

    def _get_llm_client(self):
        if self._llm_client is not None:
            return self._llm_client

        # Priority: Gemini (free tier) > Groq.
        # Uses the new google-genai SDK (from google import genai), not the old google-generativeai.
        if not self._gemini_disabled and (os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")):
            try:
                from google import genai  # new SDK: pip install google-genai
                api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
                gemini_client = genai.Client(api_key=api_key)
                self._gemini_client = gemini_client  # kept for cooldown recovery
                self._llm_client = gemini_client
                self._llm_provider = "gemini"
                return self._llm_client
            except (ImportError, Exception) as exc:
                logger.warning("Gemini client init failed: %s — trying next provider", exc)

        groq_key = os.getenv("GROQ_API_KEY") or os.getenv("GROK_API_KEY")
        if groq_key:
            try:
                from groq import Groq
                self._llm_client = Groq(api_key=groq_key)
                self._llm_provider = "groq"
                return self._llm_client
            except ImportError:
                pass

        return None

    def _call_llm(self, prompt: str, model: str, _retries: int = 1) -> str:
        """Call the configured LLM with retry and Groq cooldown fallback.

        Flow:
          - Tries Gemini first (if available).
          - On 429: routes this call to Groq, records the retry-delay from the error
            response, and switches the active provider to Groq.
          - On every subsequent call: checks whether the cooldown has expired.
            If yes, switches back to Gemini automatically.
          - Groq is therefore used only during the rate-limit window, then Gemini
            resumes — cycling as many times as needed across 21+ modules.
        """
        import time

        # Auto-recover: if we're on Groq due to a cooldown and the window has passed,
        # switch back to Gemini now before routing this call.
        if (
            self._llm_provider == "groq"
            and self._gemini_client is not None
            and time.time() >= self._gemini_available_at
            and self._gemini_available_at > 0  # 0 means Groq was the primary choice
        ):
            self._llm_client = self._gemini_client
            self._llm_provider = "gemini"
            console.print("  [dim]Gemini cooldown expired — resuming Gemini[/dim]")

        client = self._get_llm_client()
        if client is None:
            return ""

        for attempt in range(_retries + 1):
            try:
                if self._llm_provider == "gemini":
                    # New google-genai SDK: client is a genai.Client instance
                    response = client.models.generate_content(
                        model="gemini-2.0-flash",
                        contents=prompt,
                    )
                    return response.text or ""

                elif self._llm_provider == "groq":
                    groq_model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
                    response = client.chat.completions.create(
                        model=groq_model,
                        messages=[{"role": "user", "content": prompt}],
                        max_tokens=1024,
                        temperature=0.2,
                    )
                    return response.choices[0].message.content or ""

            except Exception as exc:
                if self._llm_provider == "gemini" and _is_rate_limit(exc):
                    delay = _parse_retry_delay(exc)
                    self._enter_groq_cooldown(delay)
                    return self._call_groq(prompt)

                if self._llm_provider == "gemini" and _is_model_not_found(exc):
                    # The configured Gemini model is invalid or not available for this API
                    # version/account. Disable Gemini for the rest of this run to avoid
                    # spamming 404s, and fall back to Groq directly.
                    logger.warning("Gemini model not found (%s) — disabling Gemini for this run and using Groq", exc)
                    self._gemini_disabled = True
                    self._gemini_client = None
                    # Switch provider to Groq if possible
                    fallback = self._call_groq(prompt)
                    return fallback

                if self._llm_provider == "gemini" and attempt >= _retries:
                    # Non-rate-limit Gemini error after retries — fall back once
                    logger.warning("Gemini failed (%s) — falling back to Groq", exc)
                    return self._call_groq(prompt)

                if attempt < _retries:
                    wait = 2 ** attempt
                    logger.warning(
                        "LLM call failed (attempt %d/%d): %s — retrying in %ds",
                        attempt + 1, _retries + 1, exc, wait,
                    )
                    time.sleep(wait)
                else:
                    logger.warning("LLM call failed after %d attempts: %s", _retries + 1, exc)
        return ""

    def _call_groq(self, prompt: str) -> str:
        """Call Groq's Llama model as a rate-limit / last-resort fallback."""
        # Accept GROQ_API_KEY or the common GROK_API_KEY typo
        groq_key = os.getenv("GROQ_API_KEY") or os.getenv("GROK_API_KEY")
        if not groq_key:
            return ""
        try:
            from groq import Groq
            client = Groq(api_key=groq_key)
            model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1024,
                temperature=0.2,
            )
            return response.choices[0].message.content or ""
        except Exception as exc:
            logger.warning("Groq fallback failed: %s", exc)
            return ""

    def _enter_groq_cooldown(self, delay_seconds: float) -> None:
        """Switch to Groq and record when Gemini's rate-limit window expires.

        After `delay_seconds` have elapsed, `_call_llm` will automatically
        switch back to Gemini at the start of the next call.
        """
        import time
        groq_key = os.getenv("GROQ_API_KEY") or os.getenv("GROK_API_KEY")
        if not groq_key:
            return
        try:
            from groq import Groq
            self._llm_client = Groq(api_key=groq_key)
            self._llm_provider = "groq"
            self._gemini_available_at = time.time() + delay_seconds
            console.print(
                f"  [yellow]Gemini rate-limited — using Groq for ~{int(delay_seconds)}s, "
                f"then Gemini resumes[/yellow]"
            )
        except ImportError:
            pass

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
        """Check semantic similarity using embeddings, with word-overlap fallback.

        If cosine similarity >= 0.8 we treat the texts as "similar enough".
        """
        # Prefer embedding-based similarity if the optional dependency is available.
        try:
            embs = self._embed_texts([text_a, text_b])
        except Exception:
            embs = None

        if embs is not None:
            try:
                import numpy as np

                a, b = embs[0], embs[1]
                denom = (np.linalg.norm(a) * np.linalg.norm(b)) or 1.0
                sim = float(np.dot(a, b) / denom)
                return sim >= 0.8
            except Exception as exc:
                logger.warning("Embedding similarity check failed, falling back to word overlap: %s", exc)

        # Fallback: simple word-overlap heuristic
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
        """Resolve a module key back to a source file, trying all supported extensions."""
        base = repo_path / module_path.replace("/", os.sep)
        candidates = [
            Path(str(base) + ".py"),
            Path(str(base) + ".sql"),
            Path(str(base) + ".yml"),
            Path(str(base) + ".yaml"),
            Path(str(base) + ".js"),
            Path(str(base) + ".ts"),
            base,  # already has extension (e.g. stored with it)
        ]
        for candidate in candidates:
            if candidate.exists():
                try:
                    return candidate.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    pass
        return ""
