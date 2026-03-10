from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Annotated, Any, Optional, TypedDict

from rich.console import Console

from src.agents.hydrologist import Hydrologist
from src.agents.semanticist import Semanticist
from src.graph.knowledge_graph import KnowledgeGraph

logger = logging.getLogger(__name__)
console = Console()
_hydro = Hydrologist()
_semanticist = Semanticist()


# ── Tool implementations ──────────────────────────────────────────────────────

def find_implementation(concept: str, kg: KnowledgeGraph, index_dir: Optional[Path] = None) -> str:
    """Semantic search: find modules implementing a business concept."""
    results: list[str] = []

    if index_dir and (index_dir / "semantic_index").exists():
        try:
            import chromadb
            client = chromadb.PersistentClient(path=str(index_dir / "semantic_index"))
            collection = client.get_collection("modules")
            response = collection.query(query_texts=[concept], n_results=5)
            for doc, meta, dist in zip(
                response["documents"][0],
                response["metadatas"][0],
                response["distances"][0],
            ):
                results.append(
                    f"- `{meta['path']}` (domain: {meta.get('domain', '?')}, "
                    f"similarity: {1 - dist:.2f})\n  {doc[:200]}"
                )
            if results:
                return (
                    f"[semantic search]\n\nTop matches for **{concept}**:\n\n"
                    + "\n\n".join(results)
                )
        except Exception as exc:
            logger.warning("ChromaDB query failed: %s", exc)

    # Fallback: keyword search over purpose statements
    concept_lower = concept.lower()
    for module in sorted(kg.all_modules(), key=lambda m: m.pagerank_score, reverse=True):
        text = (module.purpose_statement + " " + module.path).lower()
        if any(word in text for word in concept_lower.split()):
            results.append(f"- `{module.path}` - {module.purpose_statement[:200]}")
        if len(results) >= 5:
            break

    if not results:
        return f"No matches found for '{concept}'."
    return f"[keyword search fallback]\n\nMatches for **{concept}**:\n\n" + "\n".join(results)


def trace_lineage(dataset: str, direction: str, kg: KnowledgeGraph) -> str:
    """Graph traversal: trace upstream or downstream lineage for a dataset."""
    direction = direction.lower().strip()
    if direction not in ("upstream", "downstream"):
        direction = "upstream"

    results = _hydro.trace_lineage(kg, dataset, direction)
    if not results:
        return f"Dataset `{dataset}` not found in lineage graph, or no {direction} dependencies."

    lines = [f"[graph traversal]\n\n**{direction.title()} lineage** for `{dataset}`:\n"]
    for item in results:
        indent = "  " * item["depth"]
        lines.append(f"{indent}-> `{item['node']}` (depth {item['depth']})")
    return "\n".join(lines)


def blast_radius(module_path: str, kg: KnowledgeGraph) -> str:
    """Graph traversal: find everything downstream of a module or dataset."""
    results = _hydro.blast_radius(kg, module_path)
    if not results:
        # Also try in module graph
        if module_path in kg.module_graph:
            dependents = list(kg.module_graph.successors(module_path))
            if dependents:
                return (
                    f"[graph traversal]\n\n**Module dependents** of `{module_path}`:\n\n"
                    + "\n".join(f"- `{d}`" for d in dependents)
                )
        return f"No downstream dependencies found for `{module_path}`."

    lines = [f"[graph traversal]\n\n**Blast radius** of `{module_path}` "
             f"({len(results)} downstream nodes):\n"]
    for item in results:
        indent = "  " * item["depth"]
        source = f" - `{item['source_file']}`" if item.get("source_file") else ""
        lines.append(f"{indent}-> `{item['node']}` (depth {item['depth']}){source}")
    return "\n".join(lines)


def explain_module(module_path: str, kg: KnowledgeGraph, repo_path: Optional[Path] = None) -> str:
    """LLM inference: explain what a module does based on its source code."""
    module = kg.get_module(module_path)
    base_info = ""
    if module:
        base_info = (
            f"**Stored purpose statement**: {module.purpose_statement or '(none)'}\n"
            f"**Domain**: {module.domain_cluster or '?'}\n"
            f"**Complexity**: {module.complexity_score}\n"
            f"**Change velocity (30d)**: {module.change_velocity_30d}\n"
        )

    source_code = ""
    if repo_path:
        candidates = [
            repo_path / (module_path.replace("/", os.sep) + ".py"),
            repo_path / module_path,
            Path(module_path),
        ]
        for c in candidates:
            if c.exists():
                try:
                    source_code = c.read_text(encoding="utf-8", errors="replace")[:8000]
                except OSError:
                    pass
                break

    if source_code:
        prompt = (
            f"Explain what this module does in detail, covering its business purpose, "
            f"key functions, and how it fits into the larger system.\n\n"
            f"```python\n{source_code}\n```"
        )
        model = _semanticist.budget.select_model(
            _semanticist.budget.estimate_tokens(source_code), synthesis=True
        )
        explanation = _semanticist._call_llm(prompt, model)
        return f"[LLM inference from source]\n\n{base_info}\n**Explanation**:\n{explanation}"

    return f"[static analysis only]\n\n{base_info}\nSource code not available for deep explanation."


# ── LangGraph Navigator agent ─────────────────────────────────────────────────

class NavigatorState(TypedDict):
    messages: list[dict]
    kg: Any
    repo_path: Optional[str]
    cartography_dir: Optional[str]


def build_navigator_graph(kg: KnowledgeGraph, repo_path: Optional[Path] = None, cartography_dir: Optional[Path] = None):
    """Build a LangGraph ReAct agent with four codebase tools."""
    try:
        from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
        from langchain_core.tools import tool
        from langgraph.prebuilt import create_react_agent
    except ImportError:
        logger.error("langgraph/langchain-core not installed")
        return None

    @tool
    def tool_find_implementation(concept: str) -> str:
        """Find where a business concept is implemented in the codebase."""
        return find_implementation(concept, kg, cartography_dir)

    @tool
    def tool_trace_lineage(dataset: str, direction: str = "upstream") -> str:
        """Trace data lineage for a dataset upstream or downstream."""
        return trace_lineage(dataset, direction, kg)

    @tool
    def tool_blast_radius(module_path: str) -> str:
        """Find all downstream dependencies that would break if this module/dataset changes."""
        return blast_radius(module_path, kg)

    @tool
    def tool_explain_module(path: str) -> str:
        """Explain what a specific module file does."""
        return explain_module(path, kg, repo_path)

    tools = [tool_find_implementation, tool_trace_lineage, tool_blast_radius, tool_explain_module]

    llm = _get_llm_for_navigator()
    if llm is None:
        return None

    try:
        agent = create_react_agent(llm, tools)
        return agent
    except Exception as exc:
        logger.error("Failed to build navigator graph: %s", exc)
        return None


_NAVIGATOR_MODEL = "gemini-2.5-flash"
# Respects GROQ_MODEL env var; also accepts the common GROK_API_KEY typo
_GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")


def _get_llm_for_navigator():
    """Build the Navigator LLM with automatic fallbacks: Gemini → Groq → OpenAI.

    Uses LangChain's .with_fallbacks() so rate-limit errors on Gemini transparently
    retry the next provider without restarting the agent.
    """
    candidates = []

    # 1. Gemini 2.5 Flash (primary, free tier)
    if os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"):
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
            api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
            candidates.append(
                ChatGoogleGenerativeAI(model=_NAVIGATOR_MODEL, google_api_key=api_key, temperature=0)
            )
        except ImportError:
            pass

    # 2. Groq Llama (rate-limit fallback) — accept GROQ_API_KEY or the common GROK_API_KEY typo
    groq_key = os.getenv("GROQ_API_KEY") or os.getenv("GROK_API_KEY")
    if groq_key:
        try:
            from langchain_groq import ChatGroq
            candidates.append(ChatGroq(model=_GROQ_MODEL, api_key=groq_key, temperature=0))
        except ImportError:
            pass

    # 3. OpenAI (last resort)
    if os.getenv("OPENAI_API_KEY"):
        try:
            from langchain_openai import ChatOpenAI
            candidates.append(ChatOpenAI(model="gpt-4o-mini", temperature=0))
        except ImportError:
            pass

    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    # Wire all fallbacks; exceptions_to_handle covers 429 / quota errors
    primary = candidates[0]
    return primary.with_fallbacks(candidates[1:])


class Navigator:
    """Interactive query agent over the knowledge graph."""

    def __init__(self, kg: KnowledgeGraph, repo_path: Optional[Path] = None, cartography_dir: Optional[Path] = None):
        self.kg = kg
        self.repo_path = repo_path
        self.cartography_dir = cartography_dir
        self._agent = None

    def _ensure_agent(self):
        if self._agent is None:
            self._agent = build_navigator_graph(self.kg, self.repo_path, self.cartography_dir)

    def query(self, question: str) -> str:
        """Route a natural language question to the appropriate tool."""
        question_lower = question.lower()

        # Direct tool routing for common patterns (no LLM needed)
        if any(w in question_lower for w in ["upstream", "downstream", "lineage", "produces", "feeds"]):
            # Try to extract dataset name
            words = question.split()
            for i, w in enumerate(words):
                if w.lower() in ("table", "dataset", "model") and i + 1 < len(words):
                    return trace_lineage(words[i + 1], "upstream", self.kg)
            return trace_lineage(words[-1] if words else "", "upstream", self.kg)

        if any(w in question_lower for w in ["blast radius", "breaks", "depends on", "impact"]):
            words = question.split()
            target = next((w for w in reversed(words) if "/" in w or "." in w), words[-1] if words else "")
            return blast_radius(target, self.kg)

        if any(w in question_lower for w in ["explain", "what does", "what is"]):
            words = question.split()
            target = next((w for w in words if "/" in w or ".py" in w), "")
            if target:
                return explain_module(target, self.kg, self.repo_path)

        # Use LangGraph agent for complex queries
        self._ensure_agent()
        if self._agent:
            try:
                from langchain_core.messages import HumanMessage
                result = self._agent.invoke({"messages": [HumanMessage(content=question)]})
                messages = result.get("messages", [])
                if messages:
                    last = messages[-1]
                    return getattr(last, "content", str(last))
            except Exception as exc:
                logger.warning("Agent invocation failed: %s", exc)

        # Final fallback: semantic search
        return find_implementation(question, self.kg, self.cartography_dir)

    def repl(self) -> None:
        """Start an interactive REPL session."""
        console.print("\n[bold green]Navigator[/bold green] - Codebase Query Interface")
        console.print("Type your question, or 'exit' to quit.\n")

        while True:
            try:
                question = input("cartographer> ").strip()
            except (EOFError, KeyboardInterrupt):
                break

            if not question:
                continue
            if question.lower() in ("exit", "quit", "q"):
                break

            response = self.query(question)
            console.print(f"\n[cyan]{response}[/cyan]\n")
