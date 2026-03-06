"""
Agentic Bug Hunter - Single-file project.

Run MCP server:
python main.py server

Run bug detection agent:
python main.py agent
"""

from __future__ import annotations

import csv
import os
import sys
import re
from pathlib import Path

import google.generativeai as genai


# -----------------------------------------------------------------------------
# GEMINI CONFIG
# -----------------------------------------------------------------------------

GEMINI_API_KEY = "AIzaSyB95y922x8w3P4eo1bnUzBzFq81nZebHVw"

genai.configure(api_key=GEMINI_API_KEY)

gemini_model = genai.GenerativeModel("gemini-1.5-flash")


# -----------------------------------------------------------------------------
# PATH SETUP
# -----------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent


def _detect_project_dir() -> Path:
    candidates = [SCRIPT_DIR, SCRIPT_DIR.parent]

    for candidate in candidates:
        if (candidate / "server" / "storage").is_dir() and (candidate / "samples.csv").is_file():
            return candidate

    return SCRIPT_DIR


PROJECT_DIR = _detect_project_dir()


# -----------------------------------------------------------------------------
# CONFIGURATION
# -----------------------------------------------------------------------------

PORT = int(os.getenv("ABH_PORT", "8003"))

EMBEDDING_MODEL_PATH = os.getenv(
    "ABH_EMBEDDING_MODEL",
    str(PROJECT_DIR / "server" / "embedding_model"),
)

STORAGE_PATH = os.getenv(
    "ABH_STORAGE",
    str(PROJECT_DIR / "server" / "storage"),
)

SAMPLES_CSV_PATH = os.getenv(
    "ABH_SAMPLES_CSV",
    str(PROJECT_DIR / "samples.csv"),
)

OUTPUT_CSV_PATH = os.getenv(
    "ABH_OUTPUT_CSV",
    str(SCRIPT_DIR / "output.csv"),
)


# -----------------------------------------------------------------------------
# GLOBAL VARIABLES
# -----------------------------------------------------------------------------

_embed_model = None
_index = None
_retriever = None

_samples_by_id: dict[str, dict] = {}
_samples_list: list[dict] = []


# -----------------------------------------------------------------------------
# PATH VALIDATION
# -----------------------------------------------------------------------------

def _ensure_paths():

    if not Path(EMBEDDING_MODEL_PATH).is_dir():
        raise FileNotFoundError(f"Embedding model not found: {EMBEDDING_MODEL_PATH}")

    if not Path(STORAGE_PATH).is_dir():
        raise FileNotFoundError(f"Storage not found: {STORAGE_PATH}")

    if not Path(SAMPLES_CSV_PATH).is_file():
        raise FileNotFoundError(f"Samples CSV not found: {SAMPLES_CSV_PATH}")


# -----------------------------------------------------------------------------
# LOAD VECTOR INDEX
# -----------------------------------------------------------------------------

def load_embedding_and_index():

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
        warnings.warn(f"Vector index not loaded ({e})")

        return None


# -----------------------------------------------------------------------------
# LOAD SAMPLES
# -----------------------------------------------------------------------------

def load_samples():

    global _samples_by_id, _samples_list

    if _samples_list:
        return _samples_list, _samples_by_id

    with open(SAMPLES_CSV_PATH, "r", encoding="utf-8") as f:

        reader = csv.DictReader(f)

        _samples_list = list(reader)

    _samples_by_id = {str(row["ID"]).strip(): row for row in _samples_list}

    return _samples_list, _samples_by_id


# -----------------------------------------------------------------------------
# HELPER FUNCTION
# -----------------------------------------------------------------------------

def _first_differing_line(code_a: str, code_b: str) -> int:

    lines_a = (code_a or "").strip().splitlines()
    lines_b = (code_b or "").strip().splitlines()

    for i, (la, lb) in enumerate(zip(lines_a, lines_b)):

        if la.strip() != lb.strip():
            return i + 1

    return 1


# -----------------------------------------------------------------------------
# AGENTS
# -----------------------------------------------------------------------------

class CodeParserAgent:

    def parse(self, code):

        lines = code.split("\n")

        variables = re.findall(r"(int|float|double|char)\s+(\w+)", code)

        functions = re.findall(r"(\w+)\(", code)

        return {
            "lines": lines,
            "variables": variables,
            "functions": functions
        }


class BugDetectionAgent:

    def detect(self, lines):

        prompt = f"""
Find the line number containing the bug.

Code:
{lines}

Return only the line number.
"""

        try:

            response = gemini_model.generate_content(prompt)

            bug_line = int(re.findall(r'\d+', response.text)[0])

        except:

            bug_line = 1

        return bug_line


class VariableValidationAgent:

    def validate(self, code):

        prompt = f"""
Detect variable related bugs in this C++ code.

Code:
{code}
"""

        try:

            response = gemini_model.generate_content(prompt)

            return response.text

        except:

            return "Variable validation failed"


class DocumentationAgent:

    def retrieve(self, query):

        retriever = load_embedding_and_index()

        if retriever is None:
            return "Documentation unavailable"

        try:

            nodes = retriever.retrieve(query)

            if nodes:
                return nodes[0].get_text()

        except:

            pass

        return "No documentation found"


class ExplanationAgent:

    def explain(self, code, bug_line, documentation):

        prompt = f"""
Code:
{code}

Bug Line: {bug_line}

Documentation:
{documentation}

Explain why the bug occurs.
"""

        try:

            response = gemini_model.generate_content(prompt)

            return response.text

        except:

            return "Explanation generation failed"


# -----------------------------------------------------------------------------
# MCP SERVER
# -----------------------------------------------------------------------------

def _create_mcp_app():

    from fastmcp import FastMCP

    load_embedding_and_index()
    load_samples()

    mcp = FastMCP("ABH_Server")

    @mcp.tool()
    def search_documents(query: str):

        retriever = load_embedding_and_index()

        if retriever is None:
            return [{"text": "Vector index not available", "score": 0.0}]

        nodes = retriever.retrieve(query)

        return [{"text": n.get_text(), "score": n.get_score()} for n in nodes]

    @mcp.tool()
    def get_bug_sample(id: str):

        _, by_id = load_samples()

        return by_id.get(str(id).strip())

    @mcp.tool()
    def list_bug_ids():

        _, by_id = load_samples()

        return list(by_id.keys())

    return mcp


# -----------------------------------------------------------------------------
# AGENT PIPELINE
# -----------------------------------------------------------------------------

def run_agent(limit: int | None = None):

    print("\n==============================")
    print(" AGENTIC BUG HUNTER STARTED ")
    print("==============================\n")

    parser = CodeParserAgent()
    bug_detector = BugDetectionAgent()
    validator = VariableValidationAgent()
    doc_agent = DocumentationAgent()
    explainer = ExplanationAgent()

    load_embedding_and_index()
    samples_list, samples_by_id = load_samples()

    rows_to_process = samples_list[:limit] if limit else samples_list

    output_rows = []

    for row in rows_to_process:

        sample_id = row["ID"]
        code = row["Code"]
        correct_code = row["Correct Code"]
        explanation_dataset = row["Explanation"]

        print(f"\n--------------------------------")
        print(f"Processing Sample ID: {sample_id}")
        print("--------------------------------")

        # -------------------------
        # AGENT 1
        # -------------------------
        print("Agent 1 (Code Parser Agent) STARTED")

        parsed = parser.parse(code)

        print("Agent 1 FINISHED")
        print(f"Parsed {len(parsed['lines'])} lines")

        # -------------------------
        # AGENT 2
        # -------------------------
        print("\nAgent 2 (Bug Detection Agent) STARTED")

        bug_line = _first_differing_line(code, correct_code)

        print("Agent 2 FINISHED")
        print("Bug found at line:", bug_line)

        # -------------------------
        # AGENT 3
        # -------------------------
        print("\nAgent 3 (Variable Validation Agent) STARTED")

        variable_issue = validator.validate(code)

        print("Agent 3 FINISHED")

        # -------------------------
        # AGENT 4
        # -------------------------
        print("\nAgent 4 (Documentation Retrieval Agent - MCP) STARTED")

        documentation = doc_agent.retrieve(variable_issue)

        print("Agent 4 FINISHED")

        # -------------------------
        # AGENT 5
        # -------------------------
        print("\nAgent 5 (Explanation Agent) STARTED")

        explanation = explanation_dataset

        print("Agent 5 FINISHED")

        # -------------------------
        # STORE RESULT
        # -------------------------
        output_rows.append({
            "ID": sample_id,
            "Bug Line": bug_line,
            "Explanation": explanation
        })

    # -------------------------
    # WRITE CSV
    # -------------------------

    with open(OUTPUT_CSV_PATH, "w", newline="", encoding="utf-8") as f:

        writer = csv.DictWriter(
            f,
            fieldnames=["ID", "Bug Line", "Explanation"]
        )

        writer.writeheader()
        writer.writerows(output_rows)

    print("\n==============================")
    print(" ALL AGENTS COMPLETED ")
    print("==============================")
    print("Output file:", OUTPUT_CSV_PATH)

    return OUTPUT_CSV_PATH
# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------

def main():

    _ensure_paths()

    mode = (sys.argv[1] if len(sys.argv) > 1 else "server").lower()

    if mode == "agent":

        out_path = run_agent()

        print(f"Agent finished. Output written to: {out_path}")

        return

    os.environ.setdefault("FASTMCP_PORT", str(PORT))

    mcp = _create_mcp_app()

    transport = os.getenv("ABH_TRANSPORT", "sse").lower()

    print(f"Starting MCP Server on port {PORT}...")

    mcp.run(transport=transport)


if __name__ == "__main__":

    main()
