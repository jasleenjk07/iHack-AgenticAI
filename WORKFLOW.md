# Agentic Bug Hunter — Project Workflow

This document describes the **end-to-end workflow** for the Agentic Bug Hunter (ABH) project: setup, running the MCP server, running the bug-detection agent, and optional index building.

---

## 1. Prerequisites

- **Python 3.10+**
- **Project layout:**
  - `main.py` — single entrypoint (server + agent)
  - `samples.csv` — bug dataset (columns: ID, Explanation, Context, Code, Correct Code)
  - `server/embedding_model/` — HuggingFace embedding model (e.g. BAAI/bge-base-en-v1.5 or local copy)
  - `server/storage/` — LlamaIndex vector index (docstore, vector store, etc.)

---

## 2. One-Time Setup

### 2.1 Install dependencies

From the project root:

```bash
pip install -r requirements.txt
```

Or using the Makefile:

```bash
make install
```

### 2.2 Ensure required paths exist

| Path | Purpose |
|------|--------|
| `server/embedding_model/` | Embedding model (must exist; download from HuggingFace or copy locally) |
| `server/storage/` | Pre-built vector index (must exist; see §4 to build from docs) |
| `samples.csv` | Bug samples CSV (must exist at project root or set `ABH_SAMPLES_CSV`) |

If `server/embedding_model/` or `server/storage/` are missing, the server and agent will fail with clear errors.

### 2.3 Optional: Build the vector index

If you have source documents (e.g. PDFs) and need to (re)build the index:

- Place PDFs in a known directory (e.g. `server/documents/`).
- Run the index-build script (when available, e.g. `server/build_index.py`) from project root or from `server/`, so that it writes to `server/storage/` using the same embedding model as the server.
- See **IMPLEMENTATION_TECHNIQUES.md** §6 for techniques (chunking, embed model, persist dir).

Until a build script is added, use the existing `server/storage/` that was built elsewhere.

---

## 3. Daily Workflow: Two Modes

All commands are run **from the project root** unless noted.

### 3.1 Run the MCP server (default)

Exposes tools for document search and bug-sample lookup (e.g. for Cursor or other MCP clients).

```bash
python main.py
# or explicitly:
python main.py server
```

- Server listens on **port 8003** (override with `ABH_PORT`).
- Transport: SSE by default (override with `ABH_TRANSPORT`).
- Tools: `search_documents(query)`, `get_bug_sample(id)`, `list_bug_ids()`.

**Use this when:** You want to use ABH from Cursor or another client that talks MCP.

### 3.2 Run the bug-detection agent (batch)

Runs the agent over `samples.csv` and writes **output.csv** (ID, Bug Line, Explanation).

```bash
python main.py agent
```

- Reads all rows from `samples.csv` (or limit with code change).
- For each sample: computes bug line (first differing line vs Correct Code), optionally enriches explanation with doc retrieval, writes one row per sample.
- Output file: **output.csv** (path set by `ABH_OUTPUT_CSV`, default `./output.csv`).

**Use this when:** You want to generate or refresh the bug-report CSV locally.

---

## 4. Configuration (environment variables)

| Variable | Default | Description |
|----------|---------|-------------|
| `ABH_PORT` | `8003` | MCP server port |
| `ABH_EMBEDDING_MODEL` | `./server/embedding_model` | Path to embedding model directory |
| `ABH_STORAGE` | `./server/storage` | Path to vector index storage directory |
| `ABH_SAMPLES_CSV` | `./samples.csv` | Path to bug samples CSV |
| `ABH_OUTPUT_CSV` | `./output.csv` | Path to agent output CSV |
| `ABH_TRANSPORT` | `sse` | MCP transport (`sse` or `stdio`) |

All paths are resolved relative to the project root when running `main.py` from there.

---

## 5. Workflow Summary

```
┌─────────────────────────────────────────────────────────────────┐
│  ONE-TIME SETUP                                                  │
│  pip install -r requirements.txt                                 │
│  Ensure: server/embedding_model/, server/storage/, samples.csv   │
│  (Optional) Build index from PDFs → server/storage/              │
└─────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────┐
│  CHOOSE MODE                                                     │
│                                                                  │
│  • MCP Server:  python main.py [server]   → port 8003, tools     │
│  • Agent:       python main.py agent      → output.csv           │
└─────────────────────────────────────────────────────────────────┘
```

---

## 6. Quick reference (Makefile)

If you use `make`:

| Target | Command | Description |
|--------|---------|-------------|
| `install` | `make install` | Install dependencies from requirements.txt |
| `server` | `make server` | Start MCP server (default port 8003) |
| `agent` | `make agent` | Run bug-detection agent → output.csv |
| `check` | `make check` | Verify required paths and Python |

See **Makefile** in the project root.

---

## 7. Related docs

- **README.md** — Project overview and quick start.
- **IMPLEMENTATION_TECHNIQUES.md** — Techniques for retrieval, MCP, config, data, and index build (no step-by-step workflow).
- **main.py** — Implementation: `python main.py` (server) and `python main.py agent` (agent).
