from typing import List, Dict, Any
from . import llm_client

# Grade -> Lexile bands used for the fallback clause if the LLM omits it
# Common Core "stretch" Lexile bands (3rd–6th grade only shown here)
GRADE_LEX = {
    3: (520, 820),
    4: (740, 940),
    5: (830, 1010),
    6: (925, 1070),
}

# Stronger SYSTEM prompt:
# - JSON only (```json fenced)
# - Pitch = ONE sentence, concrete hook
# - Why  = ONE short clause that MUST mention interests AND Lexile fit vs. the student's grade band
SYSTEM = (
    "You are a school reading guide. Use ONLY provided fields (title, subjects, summary, lexile, shelf) "
    "and optional librarian notes. Respond with ONLY JSON in ```json fences with shape "
    "{\"items\":[{\"catalog_id\":str,\"pitch\":str,\"why\":str,\"shelf\":str}]}. "
    "Pitch: ONE sentence with a concrete hook and age-appropriate tone. "
    "Why: ONE short clause that mentions the student's interests AND explicitly cites Lexile fit vs. their grade band, "
    "e.g., 'Lexile 800 fits Grade 5 range'. "
    "Do not invent shelf or Lexile; if missing, write 'Lexile not provided'. "
    "Return at most 5 items. No extra text."
)

def _render_user(req: Dict[str, Any]) -> str:
    s = req.get("student", {}) or {}
    lines = [
        "Student:",
        f"- grade: {s.get('grade')}",
        f"- interests: {', '.join(s.get('interests', [])) or '(none)'}",
        f"- progress_bucket: {s.get('progress_bucket', 'starter')}",
        f"Librarian notes: {req.get('notes','(none)')}",
        "",
        "Candidates (catalog_id | title | subjects | summary | lexile | shelf):",
    ]
    for c in (req.get("candidates") or [])[:10]:
        p = c.get("payload", {}) or {}
        summary = (p.get("summary") or "")[:220].replace("\n", " ").strip()
        lines.append(
            f"- {c.get('catalog_id')} | {p.get('title')} | {p.get('subjects')} | "
            f"{summary} | {p.get('lexile')} | {p.get('shelf_location') or p.get('shelf') or ''}"
        )
    lines.append("")
    lines.append("Return at most 5 items.")
    return "\n".join(lines)

def _lexile_clause(lex: Any, grade: Any) -> str:
    """Construct a concise Lexile clause to append if the model omitted it."""
    try:
        g = int(grade)
    except Exception:
        g = None
    try:
        l = int(lex) if lex is not None else None
    except Exception:
        l = None
    if l is None:
        return "Lexile not provided."
    if g in GRADE_LEX:
        lo, hi = GRADE_LEX[g]
        if l < lo:
            return f"Lexile {l} is slightly below Grade {g} range."
        if l > hi:
            return f"Lexile {l} is slightly above Grade {g} range."
        return f"Lexile {l} fits Grade {g} range."
    return f"Lexile {l} noted."

def justify(req: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Takes the request dict with candidates + student, calls Hermes-3, and
    returns a list: [{catalog_id, pitch, why, shelf}] (max 5).
    Enforces a Lexile clause in 'why' if the model omits it.
    """
    user = _render_user(req)
    resp = llm_client.call_llm_json(SYSTEM, user)
    raw_items = resp.get("items", []) if isinstance(resp, dict) else []
    raw_items = raw_items[:5]

    # Build a quick lookup for candidate payloads to enrich/repair fields
    payload_by_id: Dict[str, Dict[str, Any]] = {}
    for c in (req.get("candidates") or []):
        payload_by_id[str(c.get("catalog_id"))] = c.get("payload", {}) or {}

    grade = (req.get("student", {}) or {}).get("grade")

    out: List[Dict[str, Any]] = []
    for it in raw_items:
        cid = (it.get("catalog_id") or "").strip()
        p   = payload_by_id.get(cid, {})
        shelf_in = (it.get("shelf") or "").strip()
        lex = p.get("lexile")

        pitch = (it.get("pitch") or "").strip()
        why   = (it.get("why") or "").strip()

        # Guarantee a Lexile clause if the model forgot it
        if "lexile" not in why.lower():
            clause = _lexile_clause(lex, grade)
            if why:
                # keep it short; join with a separator
                why = f"{why} {clause}"
            else:
                why = clause

        out.append({
            "catalog_id": cid,
            "pitch": pitch,
            "why": why,
            "shelf": shelf_in or (p.get("shelf_location") or p.get("shelf") or "").strip(),
        })
    return out