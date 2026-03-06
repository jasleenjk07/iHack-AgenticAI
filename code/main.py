"""
Agentic Bug Hunter - Modular multi-agent pipeline.

Modes:
  - server:     Run MCP server (ABH_Server)
  - agent:      Legacy local bug detector → output.csv
  - modular:    Multi-agent pipeline (parser → Groq bug detector → validator
                → retrieval → Gemini explainer) → output.csv
"""
from __future__ import annotations

import csv
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from bug_detection import GroqBugDetectionAgent, first_differing_line
from explanation_agent import ExplanationAgent
from parse_agent import CodeParserAgent
from retrieval_agent import DocumentationRetrievalAgent, register_mcp_tools as register_retrieval_mcp_tools
from variable_validation_agent import VariableValidationAgent


# -----------------------------------------------------------------------------
# Paths & configuration
# -----------------------------------------------------------------------------

# Project root (where server/, samples.csv, output.csv live)
CODE_DIR = Path(__file__).resolve().parent
BASE_DIR = CODE_DIR.parent

PORT = int(os.getenv("ABH_PORT", "8003"))
EMBEDDING_MODEL_PATH = os.getenv("ABH_EMBEDDING_MODEL", str(BASE_DIR / "server" / "embedding_model"))
STORAGE_PATH = os.getenv("ABH_STORAGE", str(BASE_DIR / "server" / "storage"))
SAMPLES_CSV_PATH = os.getenv("ABH_SAMPLES_CSV", str(BASE_DIR / "samples.csv"))
OUTPUT_CSV_PATH = os.getenv("ABH_OUTPUT_CSV", str(BASE_DIR / "output.csv"))

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


_embed_model = None
_index = None
_retriever = None
_samples_by_id: dict[str, dict] = {}
_samples_list: list[dict] = []


def _ensure_paths():
    """Validate that required dirs/files exist for retrieval and samples."""
    if not Path(SAMPLES_CSV_PATH).is_file():
        raise FileNotFoundError(f"Samples CSV not found: {SAMPLES_CSV_PATH}")
    # Retrieval is optional for the modular agent; warn instead of raising.
    missing = []
    if not Path(EMBEDDING_MODEL_PATH).is_dir():
        missing.append(f"Embedding model not found: {EMBEDDING_MODEL_PATH}")
    if not Path(STORAGE_PATH).is_dir():
        missing.append(f"Storage not found: {STORAGE_PATH}")
    if missing:
        import warnings

        for msg in missing:
            warnings.warn(msg)


def load_embedding_and_index():
    """Load HuggingFace embed model and LlamaIndex vector index from storage. Returns None if unavailable."""
    global _embed_model, _index, _retriever
    if _retriever is not None:
        return _retriever
    try:
        from llama_index.embeddings.huggingface import HuggingFaceEmbedding
        from llama_index.core import StorageContext, load_index_from_storage, Settings
        from llama_index.core.retrievers import VectorIndexRetriever

        _embed_model = HuggingFaceEmbedding(model_name=EMBEDDING_MODEL_PATH)
        Settings.embed_model = _embed_model
        storage_context = StorageContext.from_defaults(persist_dir=STORAGE_PATH)
        _index = load_index_from_storage(storage_context=storage_context)
        _retriever = VectorIndexRetriever(index=_index, similarity_top_k=20)
        return _retriever
    except Exception as e:  # pragma: no cover - retrieval is optional
        import warnings

        warnings.warn(f"Vector index not loaded ({e}). Doc retrieval disabled.")
        return None


def load_samples():
    """Load samples.csv into memory. Columns: ID, Explanation, Context, Code, Correct Code."""
    global _samples_by_id, _samples_list
    if _samples_list:
        return _samples_list, _samples_by_id

    with open(SAMPLES_CSV_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        required = {"ID", "Explanation", "Context", "Code", "Correct Code"}
        if reader.fieldnames and required.issubset(set(reader.fieldnames or [])):
            _samples_list = list(reader)
        else:
            raise ValueError(f"samples.csv must have columns: {required}; got {reader.fieldnames}")

    _samples_by_id = {str(row["ID"]).strip(): row for row in _samples_list}
    return _samples_list, _samples_by_id


# -----------------------------------------------------------------------------
# MCP Server
# -----------------------------------------------------------------------------

def _create_mcp_app():
    from fastmcp import FastMCP

    load_embedding_and_index()
    load_samples()

    mcp = FastMCP("ABH_Server")

    # Retrieval tools (pandas-based) from retrieval_agent — MCP server uses them here
    register_retrieval_mcp_tools(mcp)

    @mcp.tool()
    def get_bug_sample(id: str) -> dict | None:
        """
        Get one bug sample by ID from the known-bugs dataset.
        Returns dict with keys: ID, Explanation, Context, Code, Correct Code; or None if not found.
        """
        _, by_id = load_samples()
        return by_id.get(str(id).strip())

    @mcp.tool()
    def list_bug_ids() -> list[str]:
        """List all bug sample IDs available for get_bug_sample."""
        _, by_id = load_samples()
        return list(by_id.keys())

    return mcp


# -----------------------------------------------------------------------------
# Legacy single-agent bug detector (kept for compatibility)
# -----------------------------------------------------------------------------

def run_agent(limit: int | None = None) -> str:
    """
    Legacy bug detection agent over the samples dataset.
    Uses in-process retrieval to enrich explanations.
    Writes output.csv with columns: ID, Bug Line, Explanation.
    """
    load_embedding_and_index()
    samples_list, _ = load_samples()

    rows_to_process = samples_list[:limit] if limit else samples_list
    output_rows = []

    for row in rows_to_process:
        sample_id = row.get("ID", "")
        code = row.get("Code", "")
        correct_code = row.get("Correct Code", "")
        explanation = row.get("Explanation", "").strip()
        context = row.get("Context", "").strip()

        bug_line = first_differing_line(code, correct_code) or 1

        retriever = load_embedding_and_index()
        if retriever:
            try:
                query = f"{explanation} {context}" if context else explanation
                if query.strip():
                    nodes = retriever.retrieve(query[:500])
                    if nodes:
                        doc_ref = nodes[0].get_text()[:200].replace("\n", " ")
                        explanation = f"{explanation} [Ref: {doc_ref}...]"
            except Exception:
                pass

        output_rows.append(
            {
                "ID": sample_id,
                "Bug Line": bug_line,
                # Ensure CSV stays 1 row per line (no embedded newlines)
                "Explanation": " ".join((explanation or "(no explanation)").splitlines()),
            }
        )

    with open(OUTPUT_CSV_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["ID", "Bug Line", "Explanation"])
        writer.writeheader()
        writer.writerows(output_rows)

    return OUTPUT_CSV_PATH


# -----------------------------------------------------------------------------
# Modular multi-agent pipeline (uses parse_agent, bug_detection, variable_validation_agent, retrieval_agent, explanation_agent)
# -----------------------------------------------------------------------------

def _parsed_to_pipeline(parsed_dict: Dict[str, Any]) -> Any:
    """Convert parse_agent dict output to a pipeline object with .lines, .raw_lines, .function_calls."""
    lines_raw = parsed_dict.get("lines", [])
    lines_numbered = [f"Line {i+1}: {l}" for i, l in enumerate(lines_raw)]
    functions = parsed_dict.get("functions", [])
    function_calls = [t for _, t in functions] if functions and isinstance(functions[0], (list, tuple)) else list(functions)
    return type("Parsed", (), {"lines": lines_numbered, "raw_lines": lines_raw, "function_calls": function_calls})()


def run_modular_agent(limit: Optional[int] = None) -> str:
    """
    Modular multi-agent pipeline over samples.csv.

    Agents:
      1. Code Parser Agent (Python, tree-sitter optional)
      2. Bug Detection Agent (Groq)
      3. Variable Validation Agent (regex/heuristics)
      4. Documentation Retrieval Agent (existing vector index)
      5. Explanation Agent (Gemini)

    Output: output.csv with columns:
      ID, Bug Line, Explanation
    """
    _ensure_paths()
    samples_list, _ = load_samples()
    rows_to_process = samples_list[:limit] if limit else samples_list

    parser_agent = CodeParserAgent()
    groq_agent = GroqBugDetectionAgent(GROQ_API_KEY)
    validator_agent = VariableValidationAgent()
    retrieval_agent = DocumentationRetrievalAgent()
    explanation_agent = ExplanationAgent(GEMINI_API_KEY)

    output_rows: List[Dict[str, Any]] = []

    for row in rows_to_process:
        sample_id = str(row.get("ID", "")).strip()
        code = row.get("Code", "") or ""
        correct_code = row.get("Correct Code", "") or ""
        original_explanation = (row.get("Explanation", "") or "").strip()
        context = (row.get("Context", "") or "").strip()

        parsed_dict = parser_agent.parse(code)
        parsed = _parsed_to_pipeline(parsed_dict)

        baseline_bug_line = first_differing_line(code, correct_code) or 1
        bug_line = groq_agent.detect_bug_line(parsed, context, baseline_bug_line, original_explanation)

        variable_issues = validator_agent.validate(code, correct_code)

        retrieval_query_parts = [
            original_explanation,
            context,
            " ".join(parsed.function_calls),
        ]
        retrieval_query = " ".join(p for p in retrieval_query_parts if p).strip()
        retrieved_docs = retrieval_agent.retrieve(retrieval_query)

        explanation = explanation_agent.explain(
            sample_id=sample_id,
            parsed=parsed,
            bug_line=bug_line,
            variable_issues=variable_issues,
            retrieved_docs=retrieved_docs,
            original_explanation=original_explanation,
            context=context,
        )

        explanation_clean = " ".join((explanation or "(no explanation)").splitlines())

        output_rows.append(
            {
                "ID": sample_id,
                "Bug Line": bug_line,
                # Ensure CSV stays 1 row per line (no embedded newlines)
                "Explanation": explanation_clean,
            }
        )

    # Write output.csv (generated every time the pipeline runs)
    df = pd.DataFrame(output_rows, columns=["ID", "Bug Line", "Explanation"])
    df.to_csv(OUTPUT_CSV_PATH, index=False, encoding="utf-8")
    return OUTPUT_CSV_PATH


# -----------------------------------------------------------------------------
# Entrypoint
# -----------------------------------------------------------------------------

def main():
    _ensure_paths()

    mode = (sys.argv[1] if len(sys.argv) > 1 else "server").lower()

    if mode == "agent":
        out_path = run_agent()
        print(f"Legacy agent finished. Output written to: {out_path}")
        return

    if mode == "modular":
        out_path = run_modular_agent()
        print(f"Modular multi-agent pipeline finished. Output written to: {out_path}")
        return

    # Default / "server": before starting MCP server, run modular pipeline once
    if mode == "server":
        out_path = run_modular_agent()
        print(f"Modular multi-agent pipeline finished. Output written to: {out_path}")

    # Run MCP server (port via FASTMCP_PORT or pass to run)
    from fastmcp import FastMCP  # ensure dependency is available when running server

    os.environ.setdefault("FASTMCP_PORT", str(PORT))
    mcp_app = _create_mcp_app()
    transport = os.getenv("ABH_TRANSPORT", "sse").lower()
    print(f"Starting ABH MCP Server on port {PORT} (transport={transport})...")
    mcp_app.run(transport=transport)


if __name__ == "__main__":
    main()
