"""
Documentation Retrieval Agent — pandas-only, no Hugging Face.

Loads document text from a CSV into a pandas DataFrame and retrieves
by keyword overlap: score = number of query words found in each row's text.
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
# Optional: path to a CSV with a "text" column for docs. If missing, use samples.csv.
DOCS_CSV_PATH = os.getenv("ABH_DOCS_CSV", str(BASE_DIR / "samples.csv"))

_docs_df: pd.DataFrame | None = None


def _ensure_text_column(df: pd.DataFrame) -> pd.DataFrame:
    """If no 'text' column, build it from Explanation + Context when present."""
    if "text" in df.columns:
        return df
    if "Explanation" in df.columns and "Context" in df.columns:
        df = df.copy()
        df["text"] = (df["Explanation"].fillna("").astype(str) + " " + df["Context"].fillna("").astype(str)).str.strip()
        return df
    if "Explanation" in df.columns:
        df = df.copy()
        df["text"] = df["Explanation"].fillna("").astype(str)
        return df
    return df


def load_docs() -> pd.DataFrame:
    """Load document table from CSV using pandas. Cached after first load."""
    global _docs_df
    if _docs_df is not None:
        return _docs_df
    path = Path(DOCS_CSV_PATH)
    if not path.is_file():
        _docs_df = pd.DataFrame(columns=["text"])
        return _docs_df
    _docs_df = pd.read_csv(path, encoding="utf-8")
    _docs_df = _ensure_text_column(_docs_df)
    if "text" not in _docs_df.columns:
        _docs_df["text"] = ""
    return _docs_df


def search_documents(query: str, top_k: int = 20) -> list[dict]:
    """
    Retrieve rows whose text contains query words. Uses only pandas.

    Scores by number of query words (lowercased) found in each row's text.
    Returns list of {"text": ..., "score": ...} sorted by score descending.
    """
    if not (query or query.strip()):
        return []
    df = load_docs()
    if df.empty or "text" not in df.columns:
        return []

    q = query[:500].strip().lower()
    words = [w for w in q.split() if len(w) > 1]

    def score(row: str) -> float:
        if pd.isna(row) or not row:
            return 0.0
        s = str(row).lower()
        return sum(1 for w in words if w in s)

    scored = df["text"].apply(score)
    df = df.assign(score=scored)
    df = df[df["score"] > 0].sort_values("score", ascending=False).head(top_k)

    return [
        {"text": row["text"], "score": float(row["score"])}
        for _, row in df.iterrows()
    ]


def get_reference_snippet(query: str, max_chars: int = 200) -> str:
    """Return top retrieval snippet text for explanation enrichment."""
    if not query.strip():
        return ""
    rows = search_documents(query[:500], top_k=1)
    if not rows:
        return ""
    text = str(rows[0].get("text", "")).replace("\n", " ").strip()
    return text[:max_chars]


# -----------------------------------------------------------------------------
# DocumentationRetrievalAgent — used by main.py pipeline; pandas only
# -----------------------------------------------------------------------------

class DocumentationRetrievalAgent:
    """
    Retrieve bug-related text from a CSV using pandas only.

    No Hugging Face or embeddings. Uses keyword overlap in a pandas DataFrame
    to score and rank rows, then returns combined text for top_k.
    """

    def __init__(self) -> None:
        load_docs()

    def retrieve(self, query: str, top_k: int = 1, max_chars: int = 1500) -> str:
        if not query.strip():
            return ""
        try:
            rows = search_documents(query[:500], top_k=max(top_k, 10))
            if not rows:
                return ""

            df = pd.DataFrame(rows, columns=["text", "score"])
            df = df.sort_values("score", ascending=False).head(top_k)
            texts = df["text"].astype(str).tolist()
            combined = "\n\n".join(texts)
            return combined[:max_chars]
        except Exception:
            return ""


# -----------------------------------------------------------------------------
# MCP server integration — register retrieval tools with the FastMCP app
# -----------------------------------------------------------------------------

def register_mcp_tools(mcp) -> None:
    """
    Register retrieval-related tools on the MCP server (FastMCP instance).
    Call this from main._create_mcp_app() so the server uses pandas-based retrieval.
    """
    # Use module-level functions (avoid UnboundLocalError from inner defs with same names)
    import sys
    _this = sys.modules[__name__]
    _search_documents = _this.search_documents
    _get_reference_snippet = _this.get_reference_snippet

    @mcp.tool()
    def search_documents(query: str, top_k: int = 20) -> list[dict]:
        """
        Search documentation using pandas-based keyword retrieval.
        Returns a list of dicts with keys: text, score.
        """
        return _search_documents(query, top_k=top_k)

    @mcp.tool()
    def get_reference_snippet(query: str, max_chars: int = 200) -> str:
        """Return top retrieval snippet text for explanation enrichment."""
        return _get_reference_snippet(query, max_chars=max_chars)
