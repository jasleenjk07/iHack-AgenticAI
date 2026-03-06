#!/usr/bin/env python3
"""
Agentic Bug Hunter - Single-file project.
Run MCP server:  python main.py server   (or  python main.py)
Run bug-detection agent (produces output.csv):  python main.py agent
"""
from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

# Base directory: project root (where main.py and samples.csv live)
BASE_DIR = Path(__file__).resolve().parent

# -----------------------------------------------------------------------------
# Configuration (env vars with defaults)
# -----------------------------------------------------------------------------
PORT = int(os.getenv("ABH_PORT", "8003"))
EMBEDDING_MODEL_PATH = os.getenv("ABH_EMBEDDING_MODEL", str(BASE_DIR / "server" / "embedding_model"))
STORAGE_PATH = os.getenv("ABH_STORAGE", str(BASE_DIR / "server" / "storage"))
SAMPLES_CSV_PATH = os.getenv("ABH_SAMPLES_CSV", str(BASE_DIR / "samples.csv"))
OUTPUT_CSV_PATH = os.getenv("ABH_OUTPUT_CSV", str(BASE_DIR / "output.csv"))

# -----------------------------------------------------------------------------
# Lazy-loaded globals (embed model, index, retriever, samples)
# -----------------------------------------------------------------------------
_embed_model = None
_index = None
_retriever = None
_samples_by_id: dict[str, dict] = {}
_samples_list: list[dict] = []


def _ensure_paths():
    """Validate that required dirs/files exist."""
    if not Path(EMBEDDING_MODEL_PATH).is_dir():
        raise FileNotFoundError(f"Embedding model not found: {EMBEDDING_MODEL_PATH}")
    if not Path(STORAGE_PATH).is_dir():
        raise FileNotFoundError(f"Storage not found: {STORAGE_PATH}")
    if not Path(SAMPLES_CSV_PATH).is_file():
        raise FileNotFoundError(f"Samples CSV not found: {SAMPLES_CSV_PATH}")


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
    except Exception as e:
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
# Bug detection helpers (line-level precision)
# -----------------------------------------------------------------------------
def _first_differing_line(code_a: str, code_b: str) -> int:
    """Return 1-based line number of first differing line; 0 if identical or empty."""
    lines_a = (code_a or "").strip().splitlines()
    lines_b = (code_b or "").strip().splitlines()
    for i, (la, lb) in enumerate(zip(lines_a, lines_b)):
        if la.strip() != lb.strip():
            return i + 1
    if len(lines_a) != len(lines_b):
        return min(len(lines_a), len(lines_b)) + 1
    return 1 if lines_a else 0


# -----------------------------------------------------------------------------
# MCP Server
# -----------------------------------------------------------------------------
def _create_mcp_app():
    from fastmcp import FastMCP

    load_embedding_and_index()
    load_samples()

    mcp = FastMCP("ABH_Server")

    @mcp.tool()
    def search_documents(query: str) -> list[dict]:
        """
        Search documentation using vector similarity retrieval.
        Returns a list of dicts with keys: text, score.
        """
        retriever = load_embedding_and_index()
        if retriever is None:
            return [{"text": "Vector index not available. Install deps and build index.", "score": 0.0}]
        nodes = retriever.retrieve(query)
        return [{"text": n.get_text(), "score": n.get_score()} for n in nodes]

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
# Bug Detection Agent (produces output.csv)
# -----------------------------------------------------------------------------
def run_agent(limit: int | None = None) -> str:
    """
    Run the bug detection agent over the samples dataset.
    Uses MCP tools in-process: search_documents for doc reference, get_bug_sample for known bugs.
    Writes output.csv with columns: ID, Bug Line, Explanation.
    Returns path to output file.
    """
    load_embedding_and_index()
    samples_list, samples_by_id = load_samples()

    rows_to_process = samples_list[:limit] if limit else samples_list
    output_rows = []

    for row in rows_to_process:
        sample_id = row.get("ID", "")
        code = row.get("Code", "")
        correct_code = row.get("Correct Code", "")
        explanation = row.get("Explanation", "").strip()
        context = row.get("Context", "").strip()

        # 1) Pinpoint exact line: first line where Code differs from Correct Code
        bug_line = _first_differing_line(code, correct_code)
        if bug_line == 0:
            bug_line = 1

        # 2) Optional: enrich explanation with doc retrieval (MCP utilization)
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

        output_rows.append({
            "ID": sample_id,
            "Bug Line": bug_line,
            "Explanation": explanation or "(no explanation)",
        })

    with open(OUTPUT_CSV_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["ID", "Bug Line", "Explanation"])
        writer.writeheader()
        writer.writerows(output_rows)

    return OUTPUT_CSV_PATH


# -----------------------------------------------------------------------------
# Entrypoint
# -----------------------------------------------------------------------------
def main():
    _ensure_paths()

    mode = (sys.argv[1] if len(sys.argv) > 1 else "server").lower()

    if mode == "agent":
        out_path = run_agent()
        print(f"Agent finished. Output written to: {out_path}")
        return

    # Default: run MCP server (port via FASTMCP_PORT or pass to run)
    os.environ.setdefault("FASTMCP_PORT", str(PORT))
    mcp = _create_mcp_app()
    transport = os.getenv("ABH_TRANSPORT", "sse").lower()
    print(f"Starting ABH MCP Server on port {PORT} (transport={transport})...")
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
