# app/router.py
from __future__ import annotations

import os
import re
from typing import Dict, Any
from app.vector_store import search as vs_search

SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")

def looks_webby(q: str) -> bool:
    ql = (q or "").lower()
    if any(k in ql for k in ["latest", "today", "news", "breaking", "2024", "2025"]):
        return True
    if re.search(r"\b(https?://|www\.)", ql):
        return True
    if any(k in ql for k in ["site:", "journal", "publication", "paper", "study", "dataset"]):
        return True
    return False

def route(query: str, vs_threshold: float = 0.40) -> Dict[str, Any]:
    """
    Decide where to send the query: vector store, web, or direct LLM.
    Returns: {"route": "vector"|"web"|"llm", "hits": [...]}
    """
    # 1) Try vector store first
    try:
        hits = vs_search(query, top_k=5)
        top_score = hits[0].score if hits else 0.0
        if hits and top_score >= vs_threshold:
            return {"route": "vector", "hits": hits}
    except Exception:
        # If vector search fails, fall through to web/llm logic
        hits = []

    # 2) Web if query looks time-sensitive / external AND key is present
    if looks_webby(query) and SERPAPI_KEY:
        return {"route": "web", "hits": []}

    # 3) Default to direct LLM
    return {"route": "llm", "hits": []}