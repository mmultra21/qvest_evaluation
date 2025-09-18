from typing import List, Dict, Any, Optional, Iterable

CATALOG: List[Dict[str, Any]] = [
    {"id":"bk1","title":"Soccer Stars","subjects":["sports","friendship"],"summary":"A new striker joins a team and learns to pass and trust.","lexile":800,"grades":[4,5,6],"shelf_location":"G5-SPO-12"},
    {"id":"bk2","title":"Mystery Bus","subjects":["mystery","adventure"],"summary":"A field trip detours into a small-town riddle to solve.","lexile":750,"grades":[4,5],"shelf_location":"G5-MYS-07"},
    {"id":"bk3","title":"Graphic Goal","subjects":["graphic novels","sports"],"summary":"A comic-style season of wins and losses on the court.","lexile":700,"grades":[3,4,5],"shelf_location":"G4-GRA-03"},
    {"id":"bk4","title":"Animal Allies","subjects":["animals","nonfiction"],"summary":"Short true stories about rescuers and their critter companions.","lexile":680,"grades":[3,4],"shelf_location":"G3-ANI-21"},
    {"id":"bk5","title":"Code Camp Quest","subjects":["technology","friendship"],"summary":"Friends team up to build a small game and face a deadline.","lexile":820,"grades":[5,6],"shelf_location":"G6-TEC-02"},
    {"id":"bk6","title":"River Rescue","subjects":["adventure","nature"],"summary":"Two siblings kayak into a surprise storm and find courage.","lexile":770,"grades":[4,5],"shelf_location":"G5-ADV-10"},
    {"id":"bk7","title":"Court Comics","subjects":["graphic novels","friendship"],"summary":"Panels follow a middle-school squad through ups and downs.","lexile":690,"grades":[3,4,5],"shelf_location":"G4-GRA-04"},
]

GRADE_LEX = {3:(500,820), 4:(650,940), 5:(730,1030), 6:(770,1090)}

def _level_fit(lexile: Optional[int], grade: int) -> float:
    if not lexile:
        return 0.5
    lo, hi = GRADE_LEX.get(grade, (650, 1000))
    if lexile < lo:
        return max(0.0, 1.0 - (lo - lexile)/300.0)
    if lexile > hi:
        return max(0.0, 1.0 - (lexile - hi)/300.0)
    center = (lo + hi)/2.0
    return max(0.1, 1.0 - abs(lexile - center) / ((hi - lo)/2.0 + 1e-6))

def _norm_set(xs: Optional[Iterable[str]]) -> set:
    return {str(x).strip().lower() for x in (xs or []) if str(x).strip()}

def _interest_overlap(subjects: List[str], interests: List[str]) -> float:
    s, i = _norm_set(subjects), _norm_set(interests)
    if not i:
        return 0.3
    overlap = len(s & i)
    return min(1.0, 0.5 + 0.25 * overlap)

def _progress_diversity_bonus(subjects: List[str], interests: List[str], bucket: str) -> float:
    # Encourage exploration for streak readers.
    s, i = _norm_set(subjects), _norm_set(interests)
    if bucket == "streak" and not s <= i:
        return 0.1
    return 0.0

def _popularity_proxy(title: str) -> float:
    # Simple deterministic 0..1; swap later with real cohort popularity
    return (sum(ord(ch) for ch in title) % 100) / 100.0

def rank_candidates(
    grade: int,
    interests: List[str],
    progress_bucket: str,
    top_k: int = 10,
    *,
    catalog: Optional[List[Dict[str, Any]]] = None,
    campaign_seed_ids: Optional[set] = None,
    weights: Dict[str, float] = None,
) -> List[Dict[str, Any]]:
    """
    Returns ranked candidates with scores & payload.
    Set `campaign_seed_ids` (set of catalog_ids) to boost seeded titles.
    Pass `catalog` to override the in-file CATALOG.
    """
    items = catalog if catalog is not None else CATALOG
    w = {"interest": 0.45, "popularity": 0.25, "level": 0.20, "diversity": 0.10, "campaign": 0.10}
    if weights:
        w.update(weights)
    seed_set = set(campaign_seed_ids or [])

    ranked: List[Dict[str, Any]] = []
    # First pass: strict grade match
    pool = [it for it in items if grade in (it.get("grades") or [])]
    # Backoff if empty: allow +/-1 grade
    if not pool:
        pool = [it for it in items if any(abs(g - grade) <= 1 for g in (it.get("grades") or []))]

    for it in pool:
        inter = _interest_overlap(it.get("subjects", []), interests)
        lvl   = _level_fit(it.get("lexile"), grade)
        pop   = _popularity_proxy(it.get("title",""))
        div   = _progress_diversity_bonus(it.get("subjects", []), interests, progress_bucket)
        camp  = 1.0 if it.get("id") in seed_set else 0.0

        score = w["interest"]*inter + w["popularity"]*pop + w["level"]*lvl + w["diversity"]*div + w["campaign"]*camp

        ranked.append({
            "catalog_id": it["id"],
            "payload": {
                "title": it["title"],
                "subjects": it["subjects"],
                "summary": it["summary"],
                "lexile": it["lexile"],
                "shelf_location": it["shelf_location"],
            },
            "scores": {"interest": inter, "popularity": pop, "level": lvl, "diversity": div, "campaign": camp, "final": score},
            "reason_tags": list(_norm_set(it["subjects"]) & _norm_set(interests)),
        })

    # Sort by final score; tie-breaker by title/id for stability
    ranked.sort(key=lambda x: (x["scores"]["final"], x["payload"]["title"], x["catalog_id"]), reverse=True)
    return ranked[:top_k]

# Backward-compatible wrapper
def recommend_for(
    user_id: str,
    catalog: Optional[List[Dict[str, Any]]] = None,
    *,
    grade: Optional[int] = None,
    interests: Optional[List[str]] = None,
    progress_bucket: str = "normal",
    top_k: int = 5,
    campaign_seed_ids: Optional[set] = None,
) -> List[Dict[str, Any]]:
    """
    Backward-compatible convenience API:
    - If `catalog` provided but no signals, return first top_k items.
    - Else score via rank_candidates and return list of payloads only.
    """
    if catalog and (grade is None and not interests):
        return catalog[:top_k]

    g = grade if grade is not None else 4
    intr = interests or []
    ranked = rank_candidates(
        g, intr, progress_bucket, top_k=top_k, catalog=catalog, campaign_seed_ids=campaign_seed_ids
    )
    return [r["payload"] for r in ranked]