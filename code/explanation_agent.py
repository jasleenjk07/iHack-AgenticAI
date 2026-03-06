from __future__ import annotations

from typing import Any, Dict, Optional

try:
    import google.generativeai as genai  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    genai = None  # type: ignore


class ExplanationAgent:
    """
    Use Gemini to generate a clear bug explanation from all context.

    This agent is intentionally self-contained so it can be owned and
    developed independently by a teammate. It expects:

    - sample_id: ID of the bug sample from the dataset
    - parsed: a ParsedCode-like object with a 'lines' attribute (list of strings)
    - bug_line: 1-based line number of the primary bug
    - variable_issues: mapping from variable name to human-readable issue description
    - retrieved_docs: free-form text with any relevant documentation
    - original_explanation: original short explanation from the dataset (optional)
    - context: additional natural-language context for the bug (optional)
    """

    def __init__(self, api_key: Optional[str]) -> None:
        self.enabled = bool(api_key and genai is not None)
        if self.enabled:
            genai.configure(api_key=api_key)  # type: ignore[union-attr]
            self._model = genai.GenerativeModel("gemini-1.5-flash")  # type: ignore[union-attr]
        else:
            self._model = None

    def explain(
        self,
        sample_id: str,
        parsed: Any,
        bug_line: int,
        variable_issues: Dict[str, str],
        retrieved_docs: str,
        original_explanation: str,
        context: str,
    ) -> str:
        """
        Produce a short, clear explanation of the bug.

        The 'parsed' object is treated generically; it only needs to expose
        a 'lines' attribute that is an iterable of strings representing the
        code lines with line numbers.
        """
        # Fallback path when Gemini is not available.
        if not self.enabled:
            parts = []
            if original_explanation:
                parts.append(original_explanation.strip())
            if variable_issues:
                parts.append("Variable issues: " + "; ".join(variable_issues.values()))
            if retrieved_docs:
                doc_snippet = retrieved_docs[:500].replace("\n", " ").strip()
                if doc_snippet:
                    parts.append("Relevant context: " + doc_snippet)
            if not parts:
                parts.append(f"Bug is likely at line {bug_line}.")
            return " ".join(parts)

        code_lines = getattr(parsed, "lines", [])
        issues_text = "\n".join(variable_issues.values()) if variable_issues else "None detected."

        prompt = (
            "You are a precise bug explanation agent.\n"
            "Given C++ code lines, a bug line number, any variable issues, and relevant documentation, "
            "write a complete, clear explanation of the bug (2–4 sentences). Explain what is wrong, why it occurs, "
            "and the root cause. Do not truncate or abbreviate. Do not propose a full fix; just explain the bug.\n\n"
            f"Sample ID: {sample_id}\n"
            f"Context: {context}\n\n"
            "Code lines:\n" + "\n".join(code_lines) + "\n\n"
            f"Bug line (1-based): {bug_line}\n\n"
            f"Variable issues:\n{issues_text}\n\n"
            f"Relevant documentation:\n{retrieved_docs}\n\n"
            f"Original explanation (if any): {original_explanation}\n"
        )

        try:
            try:
                from google.generativeai.types import GenerationConfig
                config = GenerationConfig(max_output_tokens=512, temperature=0.2)
            except ImportError:
                config = {"max_output_tokens": 512, "temperature": 0.2}
            resp = self._model.generate_content(prompt, generation_config=config)  # type: ignore[union-attr]
            text = resp.text.strip()
            return text or original_explanation or f"Bug likely at line {bug_line}."
        except Exception:
            return original_explanation or f"Bug likely at line {bug_line}."

