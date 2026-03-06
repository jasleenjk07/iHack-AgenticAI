# Agentic Bug Hunter — Implementation Techniques

This document describes the **techniques, technologies, and approaches** we will follow to build the Agentic Bug Hunter (ABH) project. It is derived from the codebase (`server/`, `requirements.txt`, `samples.csv`) and the architecture plan. It does not prescribe step-by-step implementation; it defines the methodologies to use when implementing.

**Note:** The file `Agentic Bug Hunter.pptm` was not found in the workspace. Techniques below are inferred from the existing project. If the deck specifies additional techniques, they can be appended here.

---

## 1. Dependency and Stack Techniques

- **Locked core versions:** Use the versions specified in `requirements.txt` (`llama-index==0.14.13`, `fastmcp==2.14.5`) so that embedding, retrieval, and MCP behavior remain consistent.
- **LlamaIndex for retrieval:** Use LlamaIndex for document loading, chunking, embedding, index building, and retrieval (e.g. `StorageContext`, `load_index_from_storage`, `VectorIndexRetriever`). Do not replace with a different retrieval stack without updating this doc.
- **HuggingFace embeddings via LlamaIndex:** Use `llama-index-embeddings-huggingface` and `HuggingFaceEmbedding` so the same pipeline works with local or HuggingFace Hub models.
- **FastMCP for the server:** Expose all agent-facing capabilities as FastMCP tools; use `@mcp.tool()` with typed parameters and docstrings so clients get a clear tool contract.
- **Optional HuggingFace Hub:** Use `huggingface-hub` only when downloading the embedding model (e.g. `snapshot_download`); when a local `embedding_model` directory exists, prefer loading from disk to avoid network and version drift.

---

## 2. Embedding and Vector Retrieval Techniques

- **Model:** Use **BAAI/bge-base-en-v1.5** (or its local copy under `server/embedding_model/`) for all text embeddings. It is a BERT-based sentence embedding model (768 dimensions, 512 max position embeddings).
- **Single embed model for index and queries:** Set `Settings.embed_model` to the same `HuggingFaceEmbedding` instance used when building the index and when running the retriever, so query and document embeddings are comparable.
- **Similarity:** Rely on the retriever’s similarity scores (e.g. cosine) as returned by LlamaIndex; use `similarity_top_k` (e.g. 20) to control how many chunks are returned per query.
- **Persisted index:** Use LlamaIndex `StorageContext.from_defaults(persist_dir=...)` and `load_index_from_storage` so the vector index, docstore, and related structures are loaded from disk at server startup; no need to recompute embeddings on each run.
- **Path handling:** Resolve paths for `embedding_model` and `storage` relative to both “run from project root” and “run from `server/`” so the same code works in both cases (e.g. `os.path.basename(current_directory) == "server"`).

---

## 3. MCP Server and Tool Design Techniques

- **One FastMCP app:** A single FastMCP application (e.g. `FastMCP("ABH_Server", port=8003)`) should host all tools.
- **Tool semantics:** Each tool should have a clear, single purpose; docstrings must describe parameters and return shape (e.g. “Returns list of dicts with keys: text, score”).
- **Document search tool:** Expose a `search_documents(query: str)` tool that returns a list of `{text, score}` from the vector retriever. Keep the query string as the only input to avoid scope creep.
- **Bug-related tools (to add):** Introduce tools such as:
  - **Lookup by ID:** Return a single bug sample (Explanation, Context, Code, Correct Code) from the CSV by `id`.
  - **Suggest/analyze:** Accept code (and optionally context) and use `search_documents` (and optionally similar samples) to return documentation snippets and/or fix suggestions. The implementation may combine retrieval + optional LLM or rule-based formatting; the technique is “retrieval-first, then present or post-process.”
- **Demo tools:** Decide explicitly whether to keep or remove demo tools (add, multiply, sine, list_files_and_folders); if kept, document them as non-core so they are not confused with bug-hunting features.
- **Transport:** Support at least one transport (e.g. SSE) for the server; document how to run with stdio if needed for Cursor or other MCP clients.

---

## 4. Configuration Techniques

- **Externalize paths and port:** Do not hardcode port, storage path, embedding model path, or path to `samples.csv`. Use environment variables or a small config module (e.g. `config.py`) so the server can run in different environments (local, CI, different OS) without code edits.
- **Defaults:** Provide sensible defaults (e.g. port 8003, `./server/storage`, `./server/embedding_model`, `./samples.csv`) so the project runs out-of-the-box when paths are not overridden.
- **No secrets in config:** Do not put API keys or secrets in config; use env vars and document which ones are required only when using optional features (e.g. model download).

---

## 5. Data and Samples Techniques

- **CSV format:** The bug dataset is `samples.csv` with columns: **ID**, **Explanation**, **Context**, **Code**, **Correct Code**. All fields may contain multi-line and quoted content; use a CSV parser that handles quoted newlines and commas (e.g. Python `csv` module with appropriate dialect).
- **Encoding:** Assume UTF-8 for `samples.csv`; normalize or document if other encodings are ever introduced.
- **Loading strategy:** Load the CSV once at server startup (or on first use) and keep it in memory (e.g. dict keyed by ID) for fast lookup by ID; validate that required columns exist and that IDs are unique.
- **Domain:** Rows describe RDI/SmartRDI API bugs (wrong usage vs correct usage). Techniques for “suggest fix” or “analyze” should leverage this structure: use Explanation and Context for semantics and Code/Correct Code for concrete edits.
- **Optional indexing of samples:** If we add semantic search over samples, treat each row (or concatenation of Explanation + Context + Code) as a document, embed with the same embed model, and either add to the same index with a type tag or maintain a separate index/retriever for “similar bug” retrieval.

---

## 6. Index Build Pipeline Techniques

- **Reproducibility:** Provide a script (e.g. `server/build_index.py`) that builds the vector index from source documents so the project does not depend on pre-built storage from another machine.
- **Input documents:** Support at least PDFs (e.g. “DC Scale cards.pdf” and other RDI/API docs); use LlamaIndex readers that support PDF (e.g. `SimpleDirectoryReader` with appropriate file filters or a dedicated PDF reader).
- **Chunking:** Use LlamaIndex’s default or configured text splitter so chunk size and overlap are explicit and consistent with the embed model’s max length (512 tokens for bge-base-en-v1.5).
- **Embedding and persistence:** Use the same `HuggingFaceEmbedding` and `StorageContext`/persist directory as the server; after building, the server should be able to `load_index_from_storage` without further steps.
- **Documentation:** Document where to place source PDFs and how to run the build script (e.g. from project root or from `server/`), and that the script overwrites or updates the existing storage directory.

---

## 7. Client and Agent Integration Techniques

- **Server as capability provider:** The ABH server exposes capabilities (search docs, get bug sample, suggest/analyze); the “agent” is the client (e.g. Cursor with MCP, or a custom script) that calls these tools and possibly uses an LLM to interpret results.
- **Documentation over custom client code:** Prefer documenting how to connect a client (e.g. Cursor MCP config, SSE URL or stdio command) and example flows (e.g. “Given this code, call search_documents and get_bug_sample, then suggest a fix”) over implementing a full in-repo agent unless required.
- **Example flows:** Describe at least one end-to-end flow: user provides code → client calls search + optional get_bug_sample → client (or LLM) formats documentation and sample into a fix suggestion.

---

## 8. Evaluation Techniques (Optional)

- **Ground truth:** Use `samples.csv` as ground truth: each row has a known Correct Code for the given Code and Context.
- **Metric design:** Compare suggested fixes to Correct Code (e.g. normalized diff, or embedding similarity between suggested vs correct snippet). Document the metric and whether it is automated or manual.
- **Scope:** Evaluation can be a separate script (e.g. `server/eval_suggestions.py`) that loads samples, invokes the suggest/analyze path (via tool calls or in-process), and aggregates accuracy or similarity; it is optional and can be run offline.
- **No training:** The project does not require training the embed model or any LLM; evaluation is for retrieval quality and fix-suggestion quality only.

---

## 9. Code and Project Structure Techniques

- **Server entrypoint:** Keep the main MCP server in a single module (e.g. `server/mcp_server.py`) for clarity; if it grows, split configuration, CSV loading, and tool implementations into separate modules and import them.
- **No edits to plan file:** Do not modify the plan file (e.g. `.cursor/plans/...plan.md`) as part of implementation; treat it as read-only reference.
- **README:** Maintain a project README that explains: goal, architecture (or link to plan), prerequisites, install, how to build the index, how to run the server, where to put docs and `samples.csv`, and how to connect a client. This is the single entry point for humans.
- **Techniques doc:** Keep this file (`IMPLEMENTATION_TECHNIQUES.md`) as the authoritative list of techniques; when adding a new approach (e.g. reranking, new tool), add a short subsection here before or after implementing.

---

## 10. Summary Table

| Area | Technique |
|------|-----------|
| Dependencies | LlamaIndex 0.14.x, FastMCP 2.14.x, HuggingFace embeddings via LlamaIndex; optional huggingface-hub for model download. |
| Embedding | BAAI/bge-base-en-v1.5 (768d, 512 max len); single model for index and queries; persist index to disk. |
| Retrieval | VectorIndexRetriever, similarity_top_k; return list of {text, score}. |
| MCP | FastMCP with typed, documented tools; search_documents + get_bug_sample + suggest/analyze-style tools. |
| Config | Env or config module for port, storage path, embed path, samples path; sensible defaults. |
| Data | CSV with ID, Explanation, Context, Code, Correct Code; UTF-8; robust parsing; load once, lookup by ID. |
| Index build | Script to load PDFs (and optional CSV), chunk, embed, persist; same embed model and storage as server. |
| Client | Document connection and example flows; server as capability provider. |
| Evaluation | Optional script; use samples.csv as ground truth; compare suggestions to Correct Code. |
| Structure | Single server module preferred; README as entry point; this doc as techniques reference. |

---

*Last updated from: server/mcp_server.py, requirements.txt, samples.csv, server/storage and embedding_model layout, and the Agentic Bug Hunter implementation plan.*
