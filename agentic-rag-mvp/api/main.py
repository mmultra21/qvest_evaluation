from typing import List, Optional, Dict, Any
from fastapi import FastAPI
from pydantic import BaseModel

from api.tools.recommender import rank_candidates

app = FastAPI(title="Reading Assistant API (MVP)")


# Simple in-memory campaign used by the UI and recommend endpoint
CAMPAIGN = {
    "title": "Reading Week Spotlight",
    "seed_list": ["bk2", "bk6"],
    "prize_rules": "Read one book this week to enter the prize drawing!"
}


class RecommendRequest(BaseModel):
    grade: int
    interests: Optional[List[str]] = []
    progress_bucket: Optional[str] = "normal"
    top_k: Optional[int] = 5


class JustifyStudent(BaseModel):
    grade: int
    interests: Optional[List[str]] = []
    progress_bucket: Optional[str] = "normal"


class JustifyRequest(BaseModel):
    candidates: List[Dict[str, Any]]
    student: JustifyStudent
    notes: Optional[str] = None


@app.get("/campaign/current")
def campaign_current():
    """Return the active campaign metadata (mock)."""
    return CAMPAIGN


@app.post("/recommend")
def recommend(req: RecommendRequest):
    """Score and return ranked candidates. Returns the full candidate objects expected by the UI."""
    # Use campaign seed IDs to slightly boost featured titles
    seed_ids = set(CAMPAIGN.get("seed_list", []))
    ranked = rank_candidates(
        grade=req.grade,
        interests=req.interests or [],
        progress_bucket=req.progress_bucket or "normal",
        top_k=req.top_k or 5,
        campaign_seed_ids=seed_ids,
    )
    return {"candidates": ranked}


@app.post("/justify")
def justify(req: JustifyRequest):
    """Return simple justifications and pitches for each candidate.

    This is a lightweight placeholder justifier used by the Gradio UI.
    """
    items = []
    student_interests = set((req.student.interests or []))

    for c in req.candidates:
        cid = c.get("catalog_id")
        payload = c.get("payload", {})
        title = payload.get("title", cid)
        subjects = payload.get("subjects", [])
        summary = payload.get("summary", "")
        shelf = payload.get("shelf_location") or payload.get("shelf_location", "")

        # Build a short pitch and a 'why' that references student interests if present
        pitch = f"{title}: {summary[:120]}"
        matched = list(set(subjects) & student_interests)
        if matched:
            why = f"Good match: aligns with interests in {', '.join(matched)}."
        else:
            why = "A fun pick to broaden interests and practice grade-level reading."

        items.append({
            "catalog_id": cid,
            "pitch": pitch,
            "why": why,
            "shelf": shelf,
        })

    return {"items": items}
