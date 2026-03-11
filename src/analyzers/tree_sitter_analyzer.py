from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from src.models.nodes import FunctionNode, Language

logger = logging.getLogger(__name__)

# ── Language router ───────────────────────────────────────────────────────────

class LanguageRouter:
    """Caches and provides tree-sitter parsers per language."""

    def __init__(self) -> None:
        self._parsers: dict[str, object] = {}
        self._available = self._check_availability()

    def _check_availability(self) -> bool:
        try:
            from tree_sitter_languages import get_parser as _gp  # noqa: F401
            return True
        except ImportError:
            logger.warning("tree-sitter-languages not installed; falling back to regex analysis")
            return False

    def get_parser(self, language: str):
        if not self._available:
            return None
        if language in self._parsers:
            return self._parsers[language]
        try:
            from tree_sitter_languages import get_parser
            parser = get_parser(language)
            self._parsers[language] = parser
            return parser
        except Exception as exc:
            logger.warning("Could not load parser for %s: %s", language, exc)
            return None

    @property
    def is_available(self) -> bool:
        return self._available


_router = LanguageRouter()


def _parse_source(source: str, language: str):
    """Parse source code and return a tree-sitter tree, or None on failure."""
    parser = _router.get_parser(language)
    if parser is None:
        return None
    try:
        return parser.parse(bytes(source, "utf-8"))
    except Exception as exc:
        logger.debug("Parse error (%s): %s", language, exc)
        return None


def _iter_nodes(node):
    """Depth-first iterator over all nodes in a tree-sitter tree."""
    yield node
    for child in node.children:
        yield from _iter_nodes(child)


# ── Python AST analyzer ───────────────────────────────────────────────────────

class PythonASTAnalyzer:
    """Extracts structural information from Python source using tree-sitter."""

    def extract_imports(self, source: str) -> list[str]:
        tree = _parse_source(source, "python")
        if tree is None:
            return _regex_extract_imports(source)

        imports: list[str] = []
        for node in _iter_nodes(tree.root_node):
            if node.type == "import_statement":
                for child in node.children:
                    if child.type == "dotted_name":
                        imports.append(child.text.decode("utf-8"))
            elif node.type == "import_from_statement":
                module = ""
                for child in node.children:
                    if child.type in ("dotted_name", "relative_import"):
                        module = child.text.decode("utf-8")
                        break
                if module:
                    imports.append(module)
        return list(set(imports))

    def extract_functions(self, source: str, module_path: str = "") -> list[FunctionNode]:
        tree = _parse_source(source, "python")
        if tree is None:
            return []

        functions: list[FunctionNode] = []
        lines = source.splitlines()

        for node in _iter_nodes(tree.root_node):
            if node.type != "function_definition":
                continue

            name_node = next(
                (c for c in node.children if c.type == "identifier"), None
            )
            if name_node is None:
                continue

            name = name_node.text.decode("utf-8")
            is_public = not name.startswith("_")

            params_node = next(
                (c for c in node.children if c.type == "parameters"), None
            )
            signature = name + (params_node.text.decode("utf-8") if params_node else "()")

            functions.append(
                FunctionNode(
                    qualified_name=f"{module_path}::{name}" if module_path else name,
                    parent_module=module_path,
                    signature=signature,
                    is_public_api=is_public,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                )
            )
        return functions

    def extract_classes(self, source: str) -> list[dict]:
        """Return list of {name, bases, line_start} dicts for each class definition."""
        tree = _parse_source(source, "python")
        if tree is None:
            return _regex_extract_classes(source)

        classes: list[dict] = []
        for node in _iter_nodes(tree.root_node):
            if node.type != "class_definition":
                continue

            name_node = next(
                (c for c in node.children if c.type == "identifier"), None
            )
            if name_node is None:
                continue

            name = name_node.text.decode("utf-8")

            # argument_list holds superclasses: class Foo(Bar, Baz):
            arg_node = next(
                (c for c in node.children if c.type == "argument_list"), None
            )
            bases: list[str] = []
            if arg_node:
                for arg in arg_node.children:
                    if arg.type in ("identifier", "attribute"):
                        bases.append(arg.text.decode("utf-8"))

            classes.append({
                "name": name,
                "bases": bases,
                "line_start": node.start_point[0] + 1,
            })
        return classes

    def compute_complexity(self, source: str) -> int:
        """Approximate cyclomatic complexity by counting branch nodes."""
        tree = _parse_source(source, "python")
        if tree is None:
            return _regex_complexity(source)

        branch_types = {
            "if_statement", "for_statement", "while_statement",
            "except_clause", "with_statement", "conditional_expression",
            "boolean_operator",
        }
        return sum(1 for n in _iter_nodes(tree.root_node) if n.type in branch_types)

    def count_lines(self, source: str) -> int:
        return len([ln for ln in source.splitlines() if ln.strip()])

    def extract_docstring(self, source: str) -> str:
        """Extract the module-level docstring, if present."""
        tree = _parse_source(source, "python")
        if tree is None:
            return ""

        for node in tree.root_node.children:
            if node.type == "expression_statement":
                for child in node.children:
                    if child.type == "string":
                        raw = child.text.decode("utf-8")
                        return raw.strip("\"'").strip()
        return ""


# ── Python data-flow analyzer (Step 8) ────────────────────────────────────────

class DataFlowCall:
    def __init__(self, call_type: str, dataset_name: str, source_file: str, line_number: int):
        self.call_type = call_type
        self.dataset_name = dataset_name
        self.source_file = source_file
        self.line_number = line_number

    def __repr__(self) -> str:
        return f"DataFlowCall({self.call_type}, {self.dataset_name}, {self.source_file}:{self.line_number})"


_READ_PATTERNS = {
    "read_csv", "read_sql", "read_parquet", "read_json", "read_excel",
    "read_table", "read_feather", "read_orc",
}
_WRITE_PATTERNS = {
    "to_csv", "to_sql", "to_parquet", "to_json", "to_excel",
    "to_feather", "to_orc",
}
_SPARK_READ = {"csv", "parquet", "json", "orc", "text", "format"}
_SPARK_WRITE = {"save", "saveAsTable", "insertInto"}


class PythonDataFlowAnalyzer:
    """Detects pandas / SQLAlchemy / PySpark data read-write calls via AST."""

    def analyze(self, source: str, file_path: str) -> list[DataFlowCall]:
        tree = _parse_source(source, "python")
        if tree is None:
            return []

        calls: list[DataFlowCall] = []
        for node in _iter_nodes(tree.root_node):
            if node.type != "call":
                continue

            fn = node.child_by_field_name("function")
            if fn is None:
                continue

            fn_text = fn.text.decode("utf-8")
            line = node.start_point[0] + 1

            # pandas read/write
            for pattern in _READ_PATTERNS:
                if fn_text.endswith(f".{pattern}") or fn_text == pattern:
                    dataset = self._first_string_arg(node) or f"dynamic:{fn_text}"
                    calls.append(DataFlowCall("read", dataset, file_path, line))
                    break
            for pattern in _WRITE_PATTERNS:
                if fn_text.endswith(f".{pattern}"):
                    dataset = self._first_string_arg(node) or f"dynamic:{fn_text}"
                    calls.append(DataFlowCall("write", dataset, file_path, line))
                    break

            # SQLAlchemy execute / session.query
            if "execute" in fn_text or "session.query" in fn_text:
                dataset = self._first_string_arg(node) or "dynamic:sql_query"
                calls.append(DataFlowCall("read", dataset, file_path, line))

            # PySpark spark.read / df.write
            if "spark.read" in fn_text or ".read." in fn_text:
                dataset = self._first_string_arg(node) or "dynamic:spark_read"
                calls.append(DataFlowCall("read", dataset, file_path, line))
            if ".write." in fn_text or "saveAsTable" in fn_text:
                dataset = self._first_string_arg(node) or "dynamic:spark_write"
                calls.append(DataFlowCall("write", dataset, file_path, line))

        return calls

    def _first_string_arg(self, call_node) -> Optional[str]:
        args_node = call_node.child_by_field_name("arguments")
        if args_node is None:
            return None
        for child in args_node.children:
            if child.type == "string":
                raw = child.text.decode("utf-8")
                return raw.strip("\"'")
            if child.type == "concatenated_string":
                return "dynamic:concatenated_string"
            if child.type.endswith("string"):
                raw = child.text.decode("utf-8")
                return f"dynamic:{raw[:50]}"
        return None


# ── JavaScript / TypeScript analyzer ─────────────────────────────────────────

class JSASTAnalyzer:
    """Extracts structural information from JavaScript / TypeScript using tree-sitter."""

    # Map TS/JS export patterns to their tree-sitter node types
    _FUNCTION_TYPES = {
        "function_declaration",
        "function_expression",
        "arrow_function",
        "method_definition",
    }
    _CLASS_TYPES = {"class_declaration", "class_expression"}

    def _parse(self, source: str, language: str = "javascript"):
        """Try TypeScript first, fall back to JavaScript parser."""
        tree = _parse_source(source, language)
        return tree

    def extract_imports(self, source: str, language: str = "javascript") -> list[str]:
        """Return module specifiers from import/require statements."""
        tree = self._parse(source, language)
        if tree is None:
            return _js_regex_imports(source)

        imports: list[str] = []
        for node in _iter_nodes(tree.root_node):
            # ES module: import ... from 'specifier'
            if node.type == "import_statement":
                for child in node.children:
                    if child.type == "string":
                        imports.append(child.text.decode("utf-8").strip("\"'"))
            # CommonJS: require('specifier')
            elif node.type == "call_expression":
                fn = node.child_by_field_name("function")
                if fn and fn.text.decode("utf-8") == "require":
                    args = node.child_by_field_name("arguments")
                    if args:
                        for arg in args.children:
                            if arg.type == "string":
                                imports.append(arg.text.decode("utf-8").strip("\"'"))
        return list(set(imports))

    def extract_functions(self, source: str, module_path: str = "",
                          language: str = "javascript") -> list[FunctionNode]:
        """Return top-level and exported function definitions."""
        tree = self._parse(source, language)
        if tree is None:
            return []

        functions: list[FunctionNode] = []
        for node in _iter_nodes(tree.root_node):
            if node.type not in self._FUNCTION_TYPES:
                continue

            name_node = node.child_by_field_name("name")
            if name_node is None:
                # arrow function assigned to a variable: const foo = () => {}
                continue
            name = name_node.text.decode("utf-8")
            is_public = not name.startswith("_")

            params_node = node.child_by_field_name("parameters") or node.child_by_field_name("formal_parameters")
            sig = name + (params_node.text.decode("utf-8") if params_node else "()")

            functions.append(FunctionNode(
                qualified_name=f"{module_path}::{name}" if module_path else name,
                parent_module=module_path,
                signature=sig,
                is_public_api=is_public,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
            ))
        return functions

    def extract_classes(self, source: str, language: str = "javascript") -> list[dict]:
        """Return class definitions with their superclass (extends) if present."""
        tree = self._parse(source, language)
        if tree is None:
            return []

        classes: list[dict] = []
        for node in _iter_nodes(tree.root_node):
            if node.type not in self._CLASS_TYPES:
                continue

            name_node = node.child_by_field_name("name")
            name = name_node.text.decode("utf-8") if name_node else "<anonymous>"

            # "extends X" clause — tree-sitter JS uses class_heritage with direct
            # identifier children; TypeScript wraps it in an extends_clause node.
            bases: list[str] = []
            for child in node.children:
                if child.type == "class_heritage":
                    for h in _iter_nodes(child):
                        if h.type in ("identifier", "member_expression", "type_identifier"):
                            text = h.text.decode("utf-8")
                            if text != "extends" and text not in bases:
                                bases.append(text)
                    break

            classes.append({
                "name": name,
                "bases": bases,
                "line_start": node.start_point[0] + 1,
            })
        return classes

    def compute_complexity(self, source: str, language: str = "javascript") -> int:
        """Approximate cyclomatic complexity by counting branch nodes."""
        tree = self._parse(source, language)
        if tree is None:
            return 0
        branch_types = {
            "if_statement", "for_statement", "for_in_statement",
            "while_statement", "switch_case", "catch_clause",
            "ternary_expression", "logical_expression",
        }
        return sum(1 for n in _iter_nodes(tree.root_node) if n.type in branch_types)

    def count_lines(self, source: str) -> int:
        return len([ln for ln in source.splitlines() if ln.strip()])


# ── YAML analyzer ─────────────────────────────────────────────────────────────

class YAMLASTAnalyzer:
    """Extracts top-level keys from YAML files."""

    def extract_keys(self, source: str) -> list[str]:
        tree = _parse_source(source, "yaml")
        if tree is None:
            return _yaml_regex_keys(source)

        keys: list[str] = []
        # The tree-sitter YAML grammar nests the top-level mapping under
        # stream → document → block_node → block_mapping, so we search the
        # full tree for the first block_mapping rather than only root children.
        for node in _iter_nodes(tree.root_node):
            if node.type == "block_mapping":
                for child in node.children:
                    if child.type == "block_mapping_pair":
                        key_node = child.child_by_field_name("key")
                        if key_node:
                            keys.append(key_node.text.decode("utf-8").strip('"\''))
                break  # only the top-level mapping

        # Fall back to regex if tree-sitter found nothing
        return keys if keys else _yaml_regex_keys(source)


# ── Regex fallbacks (when tree-sitter is unavailable) ─────────────────────────

def _regex_extract_imports(source: str) -> list[str]:
    import re
    imports = []
    for line in source.splitlines():
        line = line.strip()
        m = re.match(r"^import\s+([\w.]+)", line)
        if m:
            imports.append(m.group(1))
        m = re.match(r"^from\s+([\w.]+)\s+import", line)
        if m:
            imports.append(m.group(1))
    return list(set(imports))


def _regex_complexity(source: str) -> int:
    import re
    keywords = ["if ", "elif ", "for ", "while ", "except ", "with "]
    return sum(len(re.findall(rf"\b{kw.strip()}\b", source)) for kw in keywords)


def _yaml_regex_keys(source: str) -> list[str]:
    import re
    return re.findall(r"^(\w[\w-]*):", source, re.MULTILINE)


def _js_regex_imports(source: str) -> list[str]:
    import re
    imports = []
    for m in re.finditer(r"""(?:import\s+.*?from|require\s*\()\s*['"]([^'"]+)['"]""", source):
        imports.append(m.group(1))
    return list(set(imports))


def _regex_extract_classes(source: str) -> list[dict]:
    import re
    classes = []
    for m in re.finditer(r"^class\s+(\w+)\s*(?:\(([^)]*)\))?", source, re.MULTILINE):
        name = m.group(1)
        bases_raw = m.group(2) or ""
        bases = [b.strip() for b in bases_raw.split(",") if b.strip()]
        line = source[: m.start()].count("\n") + 1
        classes.append({"name": name, "bases": bases, "line_start": line})
    return classes
