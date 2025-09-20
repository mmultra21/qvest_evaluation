# app/web_search.py
from __future__ import annotations
import os
import requests
from typing import List, Dict, Any, Optional


def _coerce_text(val) -> str:
    if val is None:
        return ""
    if isinstance(val, list):
        return " ".join(str(x) for x in val if x)
    return str(val)


def _take(items, limit: int) -> List[Dict[str, Any]]:
    return items[: max(1, int(limit))]


def _extract_results(data: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
    """
    Merge multiple SerpAPI surfaces into a single evidence list, capped at `limit`.
    Each item has: title, snippet, link, source (answer_box|knowledge_graph|organic|news|top_stories).
    """
    out: List[Dict[str, Any]] = []

    # 1) Answer box (direct answers / featured snippets)
    ab = data.get("answer_box") or {}
    if isinstance(ab, dict):
        title = _coerce_text(ab.get("title") or ab.get("answer"))
        snippet = _coerce_text(
            ab.get("snippet") or ab.get("snippet_highlighted_words")
        )
        link = _coerce_text(ab.get("link"))
        if title or snippet or link:
            out.append(
                {"title": title, "snippet": snippet, "link": link, "source": "answer_box"}
            )

    # 2) Knowledge graph (entity panel on the right)
    kg = data.get("knowledge_graph") or {}
    if isinstance(kg, dict):
        title = _coerce_text(kg.get("title") or kg.get("type"))
        snippet = _coerce_text(
            kg.get("description")
            or kg.get("summary")
            or kg.get("snippet")
        )
        # Knowledge graph often lacks a canonical link; leave empty or fill with "about" if present
        link = _coerce_text(kg.get("website") or "")
        if title or snippet:
            out.append(
                {"title": title, "snippet": snippet, "link": link, "source": "knowledge_graph"}
            )

    # 3) Organic results (standard web links)
    organic = data.get("organic_results") or []
    for item in _take(organic, limit):
        out.append(
            {
                "title": _coerce_text(item.get("title")),
                "snippet": _coerce_text(item.get("snippet") or item.get("snippet_highlighted_words")),
                "link": _coerce_text(item.get("link")),
                "source": "organic",
            }
        )

    # 4) News results (sometimes present on the general engine)
    news = data.get("news_results") or []
    for item in _take(news, max(0, limit - len(out))):
        out.append(
            {
                "title": _coerce_text(item.get("title")),
                "snippet": _coerce_text(item.get("snippet")),
                "link": _coerce_text(item.get("link")),
                "source": "news",
            }
        )

    # 5) Top stories (another surface for timely queries)
    top = data.get("top_stories") or []
    for item in _take(top, max(0, limit - len(out))):
        out.append(
            {
                "title": _coerce_text(item.get("title")),
                "snippet": _coerce_text(item.get("snippet")),
                "link": _coerce_text(item.get("link")),
                "source": "top_stories",
            }
        )

    # Keep only up to limit
    return out[:limit]


def _serpapi(params: Dict[str, Any]) -> Dict[str, Any]:
    r = requests.get("https://serpapi.com/search.json", params=params, timeout=25)
    r.raise_for_status()
    return r.json()


def serpapi_search(query: str, num: int = 5, site: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Robust SerpAPI Google search with knowledge graph + answer box parsing.
    Returns a list of {title, snippet, link, source}.

    Env:
      SERPAPI_KEY=<your key>
    """
    key = os.getenv("SERPAPI_KEY")
    if not key:
        raise RuntimeError("SERPAPI_KEY is missing. Add it to .env or export it in your shell.")

    limit = max(1, min(int(num), 10))
    base_params = {
        "api_key": key,
        "hl": "en",
        "gl": "us",
        "safe": "active",
        "num": limit,
    }

    # --- Attempt 1: Google (optionally scoped to a site) ---
    q = query.strip()
    params = {
        **base_params,
        "engine": "google",
        "q": f"site:{site} {q}" if site else q,
    }
    try:
        data = _serpapi(params)
        results = _extract_results(data, limit)
        if results:
            return results
    except Exception as e:
        # Bubble up HTTP/Quota issues to the caller for clarity
        raise RuntimeError(f"SerpAPI request failed (google{', site:'+site if site else ''}): {e}")

    # --- Attempt 2: Retry without site filter (if we tried with site) ---
    if site:
        try:
            params2 = {**params, "q": q}  # remove site filter
            data2 = _serpapi(params2)
            results2 = _extract_results(data2, limit)
            if results2:
                return results2
        except Exception as e:
            raise RuntimeError(f"SerpAPI request failed (google, general): {e}")

    # --- Attempt 3: Google News engine for fresh queries ---
    try:
        params_news = {**base_params, "engine": "google_news", "q": q}
        data_news = _serpapi(params_news)
        news_results = data_news.get("news_results") or []
        if news_results:
            return _take(
                [
                    {
                        "title": _coerce_text(n.get("title")),
                        "snippet": _coerce_text(n.get("snippet")),
                        "link": _coerce_text(n.get("link")),
                        "source": "news",
                    }
                    for n in news_results
                ],
                limit,
            )
    except Exception:
        # Silently ignore here—no need to fail if news engine is empty
        pass

    # No results
    return []


def format_results_bullets(results: List[Dict[str, Any]]) -> str:
    """
    Helper: turn results into bullet lines suitable for prompts.
    """
    if not results:
        return ""
    lines = []
    for r in results:
        title = r.get("title", "").strip()
        snippet = r.get("snippet", "").strip()
        link = r.get("link", "").strip()
        src = r.get("source", "web")
        line = f"- {title}: {snippet} ({link}) [{src}]"
        lines.append(line)
    return "\n".join(lines)