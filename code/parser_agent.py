from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

try:
    from tree_sitter import Language, Parser  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    Language = None  # type: ignore
    Parser = None  # type: ignore


class CodeParserAgent:
    """
    Code Parser Agent that *tries* to use tree-sitter for C++.

    If tree-sitter (and the compiled C++ grammar) are available, it will:
      - Parse the code into a syntax tree
      - Extract variable declarations, function calls, and control-flow statements
        using the AST node types.

    If not available, it falls back to a simple regex/heuristic line-based parser,
    so the rest of the pipeline still works.
    """

    def __init__(self) -> None:
        self._parser: Parser | None = None

        if Language is None or Parser is None:
            # tree-sitter library not installed; use heuristic fallback.
            print("tree-sitter not available; CodeParserAgent will use heuristic parsing.")
            return

        try:
            # Expect a compiled C++ language library. Path can be overridden
            # via TS_CPP_LIB env var; otherwise we look for build/my-languages.so
            default_so = Path(__file__).resolve().parent / "build" / "my-languages.so"
            lang_path = os.getenv("TS_CPP_LIB", str(default_so))

            cpp_lang = Language(lang_path, "cpp")  # type: ignore[call-arg]
            parser = Parser()  # type: ignore[call-arg]
            parser.set_language(cpp_lang)
            self._parser = parser
            print(f"tree-sitter initialized with C++ grammar from: {lang_path}")
        except Exception as e:  # pragma: no cover - environment-dependent
            print(f"Failed to initialize tree-sitter C++ parser ({e}); falling back to heuristics.")
            self._parser = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def parse(self, code: str) -> Dict[str, Any]:
        """
        Parse the given C++-like code and return:

        {
          "lines": [<raw code lines>],
          "variables": [(line_no, text), ...],
          "functions": [(line_no, text), ...],   # function calls
          "control_flow": [(line_no, text), ...]
        }

        When tree-sitter is available, this uses the AST. Otherwise it uses a
        simpler line-based heuristic method.
        """
        lines = code.splitlines()

        if not self._parser:
            result = self._heuristic_parse(lines)
        else:
            result = self._treesitter_parse(code, lines)

        return result

    # ------------------------------------------------------------------
    # Heuristic fallback (original behavior, slightly cleaned up)
    # ------------------------------------------------------------------
    def _heuristic_parse(self, lines: List[str]) -> Dict[str, Any]:
        variables: List[Tuple[int, str]] = []
        functions: List[Tuple[int, str]] = []
        control_flow: List[Tuple[int, str]] = []

        for line_number, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped:
                continue

            # Detect variables via simple prefixes.
            if stripped.startswith(("int ", "float ", "double ", "char ", "bool ", "long ", "short ", "auto ")):
                variables.append((line_number, stripped))

            # Detect function calls: NAME(...)
            if "(" in stripped and ")" in stripped:
                functions.append((line_number, stripped))

            # Detect control flow via keywords.
            if any(keyword in stripped for keyword in ("if", "for", "while", "switch", "else")):
                control_flow.append((line_number, stripped))

        return {
            "lines": lines,
            "variables": variables,
            "functions": functions,
            "control_flow": control_flow,
        }

    # ------------------------------------------------------------------
    # tree-sitter-based parsing
    # ------------------------------------------------------------------
    def _treesitter_parse(self, code: str, lines: List[str]) -> Dict[str, Any]:
        assert self._parser is not None

        tree = self._parser.parse(code.encode("utf-8"))  # type: ignore[union-attr]
        root = tree.root_node

        variables: List[Tuple[int, str]] = []
        functions: List[Tuple[int, str]] = []
        control_flow: List[Tuple[int, str]] = []

        # Walk the AST with an explicit stack to avoid recursion limits.
        stack = [root]
        while stack:
            node = stack.pop()
            stack.extend(node.children)

            # tree-sitter-cpp node types we care about:
            # - variable_declaration / init_declarator / field_declaration
            # - call_expression for function calls
            # - if_statement / for_statement / while_statement / switch_statement
            node_type = node.type
            start_row, _ = node.start_point  # (row, column), 0-based
            line_no = start_row + 1
            line_text = lines[start_row] if 0 <= start_row < len(lines) else ""

            if node_type in (
                "variable_declaration",
                "init_declarator",
                "field_declaration",
            ):
                variables.append((line_no, line_text.strip()))

            elif node_type == "call_expression":
                functions.append((line_no, line_text.strip()))

            elif node_type in (
                "if_statement",
                "for_statement",
                "while_statement",
                "switch_statement",
            ):
                control_flow.append((line_no, line_text.strip()))

        return {
            "lines": lines,
            "variables": variables,
            "functions": functions,
            "control_flow": control_flow,
        }
