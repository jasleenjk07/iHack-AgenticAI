# iHack-AgenticAI — Agentic Bug Hunter (ABH)

Agentic Bug Hunter is an MCP-based, **multi-agent** project that uses:

- A **bug-samples dataset** (`samples.csv`)
- Lightweight **document retrieval** over CSV text
- Multiple specialized **agents** (parser, bug detector, validator, retrieval, explainer)

to detect bugs in RDI/SmartRDI API code and generate human-readable explanations.

The system can be used in two ways:

- As a **batch bug-detection pipeline** that writes `output.csv`
- As an **MCP server** exposing tools to external clients (e.g. Cursor)

---

## Goals

- **MCP server**
  - Expose tools like `search_documents`, `get_bug_sample`, `list_bug_ids` so MCP clients can:
    - Search documentation snippets
    - Look up known-bug samples by ID
    - List available bug IDs

- **Multi-agent bug-detection pipeline**
  - Run across `samples.csv` and produce `output.csv` with, for each sample:
    - **Bug Line** (1-based)
    - **Explanation** (LLM-enhanced, or fallback if LLMs are unavailable)

---

## Quick start

### 1. Install dependencies

From the project root:

```bash
pip install -r requirements.txt
```

### 2. Set environment variables (recommended)

- **Groq (bug line prediction)**
  - `GROQ_API_KEY` – your Groq key, used via the OpenAI-compatible client.

- **Gemini (explanations)**
  - `GEMINI_API_KEY` – your Gemini key, used by `ExplanationAgent`.

- **Optional paths**
  - `ABH_SAMPLES_CSV` – path to `samples.csv` (default: project root).
  - `ABH_OUTPUT_CSV` – path to `output.csv` (default: project root).
  - `ABH_DOCS_CSV` – CSV for retrieval text (default: `samples.csv`).
  - `ABH_PORT`, `ABH_TRANSPORT` – MCP server port/transport.
  - `TS_CPP_LIB` – path to compiled tree-sitter C++ grammar (optional).

### 3. Ensure required files exist

- `samples.csv` — bug dataset at project root with columns:
  - `ID, Explanation, Context, Code, Correct Code`

Other paths such as `server/embedding_model` and `server/storage` are only required for the **legacy** agent and LlamaIndex-based retrieval.

### 4. Run

From the project root:

- **MCP server (default, also refreshes `output.csv` first)**

  ```bash
  python code/main.py
  # or
  python code/main.py server
  ```

- **Multi-agent pipeline only → `output.csv`**

  ```bash
  python code/main.py modular
  ```

- **Legacy single-agent pipeline (LlamaIndex-based, optional)**

  ```bash
  python code/main.py agent
  ```

If you use `make`, the `Makefile` provides shortcuts:

```bash
make install   # pip install -r requirements.txt
make server    # python code/main.py server
make agent     # python code/main.py agent
make check     # basic sanity checks for Python and data paths
```

---

## Architecture overview

The main entrypoint is `code/main.py`. In **modular** mode it orchestrates five agents:

1. **CodeParserAgent** (`code/parse_agent.py`)
   - Tries to use **tree-sitter** for C++ AST parsing (if available).
   - Falls back to a simple heuristic parser otherwise.
   - Extracts lines, variable declarations, function calls, and control-flow hints.

2. **GroqBugDetectionAgent** (`code/bug_detection.py`)
   - Uses Groq’s OpenAI-compatible API (via the `openai` Python client) and `GROQ_API_KEY`.
   - Given parsed code, context, and a baseline diff line, predicts the **primary bug line**.
   - Falls back to the first differing line if the API is unavailable or errors.

3. **VariableValidationAgent** (`code/variable_validation_agent.py`)
   - Uses **regex (`re`) + `collections.defaultdict`** to compare buggy and correct code.
   - Detects variable-value mismatches and suspicious declarations.

4. **DocumentationRetrievalAgent** (`code/retrieval_agent.py`)
   - Uses **pandas only** (no embeddings).
   - Loads a CSV (default `samples.csv`), builds a `text` column from `Explanation + Context`.
   - Scores rows by keyword overlap with the query and returns top snippets.
   - Also registers retrieval tools into the MCP server (`search_documents`, `get_reference_snippet`).

5. **ExplanationAgent** (`code/explanation_agent.py`)
   - Uses **Gemini** (`GEMINI_API_KEY`) to generate a 2–4 sentence explanation per bug.
   - Includes context from parsed code, variable issues, and retrieved docs.
   - Falls back to a deterministic, non-LLM explanation when Gemini is unavailable.

The pipeline writes **`output.csv`** with columns:

- `ID`
- `Bug Line`
- `Explanation` (with newlines removed so each row is a single CSV line)

---

## Project layout

| Path | Description |
|------|-------------|
| `code/main.py` | Main entrypoint (server / modular / legacy) |
| `code/parse_agent.py` | Code parsing agent (tree-sitter + heuristic) |
| `code/bug_detection.py` | Groq-based bug line prediction agent |
| `code/variable_validation_agent.py` | Regex + collections-based variable validator |
| `code/retrieval_agent.py` | Pandas-based document retrieval + MCP registration |
| `code/explanation_agent.py` | Gemini-based explanation agent with fallback |
| `samples.csv` | Bug dataset (ID, Explanation, Context, Code, Correct Code) |
| `output.csv` | Multi-agent pipeline output (ID, Bug Line, Explanation) |
| `server/` | Optional: embedding model + vector index for legacy agent |
| `requirements.txt` | Python dependencies |
| `Makefile` | Helper commands (`make install`, `make server`, `make agent`, `make check`) |
| `WORKFLOW.md` | Detailed step-by-step workflow and configuration |
| `IMPLEMENTATION_TECHNIQUES.md` | Implementation notes and design decisions |

---

## More details

- **[WORKFLOW.md](WORKFLOW.md)**  
  Detailed setup, configuration, and end-to-end run instructions.

- **[IMPLEMENTATION_TECHNIQUES.md](IMPLEMENTATION_TECHNIQUES.md)**  
  Implementation notes, design trade-offs, and how retrieval and MCP tooling are wired together.
