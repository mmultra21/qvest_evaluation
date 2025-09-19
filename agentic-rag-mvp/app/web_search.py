# app/web_search.py
import os
from typing import List, Dict, Any
from serpapi import GoogleSearch

SERP_API_KEY = os.getenv("SERPAPI_KEY", "")

def serpapi_search(q: str, num: int = 5) -> List[Dict[str, Any]]:
    if not SERP_API_KEY:
        return []
    params = {"engine": "google", "q": q, "api_key": SERP_API_KEY, "num": num}
    search = GoogleSearch(params)
    results = search.get_dict()
    organic = results.get("organic_results", [])[:num]
    # standardize
    out = []
    for r in organic:
        out.append({
            "title": r.get("title"),
            "link": r.get("link"),
            "snippet": r.get("snippet"),
            "source": "google",
        })
    return out