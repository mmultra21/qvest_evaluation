# app/router.py
import os, re
from typing import Dict, Any, List
from app.vector_store import search

SERP_API_KEY = os.getenv("SERPAPI_KEY", "")

def looks_webby(q: str) -> bool:
    ql = q.lower()
    if any(k in ql for k in ["latest", "today", "news", "update", "2024", "2025"]):
        return True
    if re.search(r"\\b(https?://|www\\.)", ql):
        return True
    if any(k in ql for k in ["site:", "paper", "publication", "journal", "dataset"]):
        return True
    return False

def route(query: str, vs_threshold: float = 0.40) -> Dict[str, Any]:
    """Return plan: {'route': 'vector'|'web'|'llm', 'hits': [...]}"""
    # 1) vector search
    hits = search(query, top_k=5)
    top_score = hits[0].score if hits else 0.0
    if hits and top_score >= vs_threshold:
        return {"route": "vector", "hits": hits}

    # 2) web?
    if looks_webby(query) and SERP_API_KEY:
        return {"route": "web", "hits": []}

    # 3) default LLM
    return {"route": "llm", "hits": []}