from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import List, Dict, Any

from api.tools.recommender import rank_candidates
from api.tools import rag
from api.models_llm import JustifyResponse  # <-- NEW

app = FastAPI(title="Reading Assistant API (MVP)")


# Simple in-memory campaign used by the UI and recommend endpoint
CAMPAIGN = {
    "title": "Reading Week Spotlight",
    "seed_list": ["bk2", "bk6"],
    "prize_rules": "Read one book this week to enter the prize drawing!"
}


class RecommendRequest(BaseModel):
    grade: int
    interests: List[str] = Field(default_factory=list)
    progress_bucket: str = "normal"
    top_k: int = 5


class Candidate(BaseModel):
    catalog_id: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    scores: Dict[str, float] = Field(default_factory=dict)
    reason_tags: List[str] = Field(default_factory=list)


class Student(BaseModel):
    grade: int
    interests: List[str] = Field(default_factory=list)
    progress_bucket: str = "starter"


class JustifyRequest(BaseModel):
    candidates: List[Candidate]
    student: Student
    notes: str | None = None


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


@app.post("/justify", response_model=JustifyResponse)  # <-- response_model enforces schema on output
def justify(req: JustifyRequest):
    items = rag.justify(req.model_dump())
    try:
        # Validate LLM output against schema (guarantees JSON shape & Lexile clause, etc.)
        return JustifyResponse(items=items)
    except Exception as e:
        # Turn validation issues into a clear 422 for the UI layer
        raise HTTPException(status_code=422, detail=str(e))
