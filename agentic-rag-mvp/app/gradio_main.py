# app/gradio_main.py
from __future__ import annotations

import os
import json
from typing import List, Dict, Any, Optional, Tuple

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from dotenv import load_dotenv

import gradio as gr

# Router + Web + Vector imports
from app.router import route
from app.web_search import serpapi_search
from app.vector_store import search as vs_search, upsert_chunks

# --- Server-side modules from your project ---
from api.tools.recommender import rank_candidates
from api.tools import rag
from api.models_llm import JustifyResponse
from api.routes import llm as llm_routes

# Optional: local Hermes-3 client (native llama.cpp endpoints)
try:
    from app.llm_client import client as llm
except Exception:
    llm = None

load_dotenv()

# -----------------------
# FastAPI app + routes
# -----------------------
app = FastAPI(title="Agentic RAG MVP API")
app.include_router(llm_routes.router)

# -----------------------
# In-memory demo stores (replace with DB later)
# -----------------------
CAMPAIGN: Dict[str, Any] = {
    "title": "Reading Week Spotlight",
    "prize_rules": "Prize for most books read in the week by grade.",
    "seed_list": ["bk2", "bk6"],
    "categories": ["fiction", "non-fiction", "sports", "mystery", "science", "history", "fantasy", "animals"],
    "start_date": None,
    "end_date": None,
}

# READ_LOGS[grade] = { student_name: {"count": int, "books": [catalog_id, ...]} }
READ_LOGS: Dict[int, Dict[str, Dict[str, Any]]] = {}
# LAST_WEEK_WINNERS[grade] = {"student": str, "count": int}
LAST_WEEK_WINNERS: Dict[int, Dict[str, Any]] = {}

# BOOK_PREFS[grade] = {category: count}
BOOK_PREFS: Dict[int, Dict[str, int]] = {}

# Minimal demo catalog for lookups (replace with real catalog / RAG retrieval)
BOOK_DB: Dict[str, Dict[str, Any]] = {
    "bk1": {"title": "Trail Adventures", "author": "K. Jay", "category": "adventure", "lexile": 750},
    "bk2": {"title": "Oceans Explained", "author": "R. Lee", "category": "science", "lexile": 820},
    "bk3": {"title": "Legends of the Field", "author": "M. Soto", "category": "sports", "lexile": 680},
    "bk4": {"title": "Time Detectives", "author": "N. Chen", "category": "mystery", "lexile": 700},
    "bk5": {"title": "Wild History", "author": "A. Diaz", "category": "history", "lexile": 790},
    "bk6": {"title": "Forest Tales", "author": "S. Wilde", "category": "fantasy", "lexile": 720},
}

# Simple RAG data bucket (filenames -> text)
RAG_CORPUS: Dict[str, str] = {}

# -----------------------
# Pydantic models (from your main.py)
# -----------------------
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
    notes: Optional[str] = None

# -----------------------
# API endpoints
# -----------------------
@app.get("/campaign/current")
def campaign_current():
    return CAMPAIGN

@app.post("/recommend")
def recommend(req: RecommendRequest):
    seed_ids = set(CAMPAIGN.get("seed_list", []))
    ranked = rank_candidates(
        grade=req.grade,
        interests=req.interests or [],
        progress_bucket=req.progress_bucket or "normal",
        top_k=req.top_k or 5,
        campaign_seed_ids=seed_ids,
    )
    return {"candidates": ranked}

@app.post("/justify", response_model=JustifyResponse)
def justify(req: JustifyRequest):
    items = rag.justify(req.model_dump())
    try:
        return JustifyResponse(items=items)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

# -----------------------
# Guardrails
# -----------------------
SAFE_BOOK_CHAT_RULES = (
    "Use age-appropriate language. Avoid spoilers unless asked. "
    "Never provide personal contact links. For external info, cite general sources and suggest checking with a librarian. "
    "Do not invent facts; if unsure, say so."
)

STUDENT_SYSTEM_PROMPT = f"""
You are Hermes-3 helping a student learn about books safely.
Rules: {SAFE_BOOK_CHAT_RULES}
When asked about a book ID like 'bk2', look up the provided BOOK_INFO context.
""".strip()

LIBRARIAN_SYSTEM_PROMPT = f"""
You are Hermes-3 assisting a librarian with reading campaigns, book summaries, and safe recommendations.
Rules: {SAFE_BOOK_CHAT_RULES}
Prefer concise, factual answers. When the user uploads documents, use them as context.
If 'Allow web search' is on, you may suggest checking reputable sources; otherwise avoid web claims.
""".strip()

BLOCKED_KEYWORDS = [
    "adult content", "explicit", "contact me", "social media DMs", "nsfw",
]

import re
BLOCKED_PATTERNS = {
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "phone": re.compile(r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})\b"),
    "url":   re.compile(r"https?://\S+|www\.\S+"),
}

def is_prompt_safe(text: str) -> Tuple[bool, str]:
    lower = (text or "").lower()
    for kw in BLOCKED_KEYWORDS:
        if kw in lower:
            return False, (
                f"Your prompt contains a restricted topic ('{kw}'). "
                "Try asking about age-appropriate summaries, themes, characters, or Lexile info."
            )
    if BLOCKED_PATTERNS["email"].search(text or "") or BLOCKED_PATTERNS["phone"].search(text or ""):
        return False, "Please don't include personal contact details. Ask about the book's content or reading level instead."
    if BLOCKED_PATTERNS["url"].search(text or ""):
        return False, "External links are not allowed here. Ask the librarian to review sources if needed."
    if len((text or "").strip()) < 3:
        return False, "Please enter a more specific question about the book (e.g., theme, characters, reading level)."
    return True, "ok"

# -----------------------
# Leaderboard utilities
# -----------------------
def record_reading(grade: int, student_name: str, catalog_id: str):
    grade = int(grade)
    READ_LOGS.setdefault(grade, {})
    student = READ_LOGS[grade].setdefault(student_name, {"count": 0, "books": []})
    student["count"] += 1
    student["books"].append(catalog_id)

    BOOK_PREFS.setdefault(grade, {})
    cat = BOOK_DB.get(catalog_id, {}).get("category", "other")
    BOOK_PREFS[grade][cat] = BOOK_PREFS[grade].get(cat, 0) + 1

def top_readers_by_grade(grade: int, k: int = 5):
    entries = READ_LOGS.get(grade, {})
    ranked = sorted(entries.items(), key=lambda kv: kv[1]["count"], reverse=True)
    return [(name, data["count"], data["books"]) for name, data in ranked[:k]]

def top_categories_for_grade(grade: int, k: int = 5):
    prefs = BOOK_PREFS.get(grade, {})
    ranked = sorted(prefs.items(), key=lambda kv: kv[1], reverse=True)
    return ranked[:k]

# -----------------------
# Gradio callbacks
# -----------------------
def ui_student_get_overview(grade: int):
    cats = top_categories_for_grade(grade, 5)
    winner = LAST_WEEK_WINNERS.get(grade)
    cats_table = [[c, n] for c, n in cats] or [["(no data)", 0]]
    winner_text = json.dumps(winner or {"message": "No winner recorded yet."}, indent=2)
    return cats_table, winner_text

def ui_student_learn_book(book_id: str, question: str):
    ok, msg = is_prompt_safe(question)
    if not ok:
        return msg

    info = BOOK_DB.get(book_id)
    if not info:
        return f"Unknown book id: {book_id}. Try one of: {', '.join(BOOK_DB.keys())}"

    context = json.dumps({"BOOK_INFO": info}, ensure_ascii=False)
    plain_prompt = (
        f"{STUDENT_SYSTEM_PROMPT}\n\n"
        f"Context: {context}\n\n"
        f"Question: {question}"
    )

    if llm is None:
        return (
            f"(Local LLM not configured) Here's what I can share about '{info['title']}' by {info['author']} "
            f"in {info['category']} (Lexile {info['lexile']}): Try asking about themes, characters, or difficulty."
        )

    try:
        messages = [
            {"role": "system", "content": STUDENT_SYSTEM_PROMPT},
            {"role": "user", "content": f"Context: {context}\n\nQuestion: {question}"},
        ]
        return llm.chat(messages, max_tokens=400, temperature=0.3)
    except Exception as e:
        if "404" in str(e) or "Not Found" in str(e):
            try:
                return llm.completion(plain_prompt, max_tokens=400, temperature=0.3)
            except Exception as e2:
                return f"[LLM error] {e2}"
        return f"[LLM error] {e}"

def ui_student_log_read(grade: int, student_name: str, book_id: str):
    if not student_name.strip():
        return "Please enter your name to log a book.", []
    if book_id not in BOOK_DB:
        return f"Unknown book id: {book_id}", []
    record_reading(grade, student_name.strip(), book_id)
    top5 = top_readers_by_grade(grade, 5)
    table = [[name, count, ", ".join(books)] for name, count, books in top5] or [["(no data)", 0, ""]]
    return f"Logged '{BOOK_DB[book_id]['title']}' for {student_name}!", table

def ui_librarian_set_campaign(title: str, prize_rules: str, categories: List[str], start: str, end: str, seed_list: List[str]):
    CAMPAIGN.update({
        "title": title or CAMPAIGN["title"],
        "prize_rules": prize_rules or CAMPAIGN["prize_rules"],
        "categories": categories or CAMPAIGN["categories"],
        "start_date": start or None,
        "end_date": end or None,
        "seed_list": seed_list or CAMPAIGN["seed_list"],
    })
    return json.dumps(CAMPAIGN, indent=2)

def ui_librarian_leaderboard(grade: int):
    top5 = top_readers_by_grade(grade, 5)
    table = [[name, count, ", ".join(books)] for name, count, books in top5] or [["(no data)", 0, ""]]
    return table

def ui_librarian_pick_winner(grade: int):
    top5 = top_readers_by_grade(grade, 1)
    if not top5:
        return json.dumps({"message": "No readers yet."}, indent=2)
    name, count, books = top5[0]
    LAST_WEEK_WINNERS[grade] = {"student": name, "count": count, "books": books}
    return json.dumps({"winner": LAST_WEEK_WINNERS[grade]}, indent=2)

# ---- Router-aware synthesis ----
def synthesize_from_hits(question: str, hits):
    ctx = []
    for h in hits[:5]:
        payload = getattr(h, "payload", {}) or {}
        ctx.append((payload.get("text") or "")[:800])
    return "\n\n".join(ctx)

def ui_librarian_book_prompt(book_id: str, question: str, allow_web: bool):
    ok, msg = is_prompt_safe(question)
    if not ok:
        return msg

    plan = route(question, vs_threshold=0.40)

    # VECTOR path
    if plan["route"] == "vector":
        hits = plan["hits"]
        context_text = synthesize_from_hits(question, hits)
        system = LIBRARIAN_SYSTEM_PROMPT + "\nRouting: VectorStore"
        prompt = (
            f"{system}\n\nContext:\n{context_text}\n\n"
            f"Question: {question}\n"
            "Answer concisely. Cite snippets from the context if relevant."
        )
        if llm is None:
            return "(LLM not configured) Vector hits available."
        try:
            return llm.completion(prompt, max_tokens=600, temperature=0.2)
        except Exception as e:
            return f"[LLM error] {e}"

    # WEB path
    if plan["route"] == "web" and allow_web:
        results = serpapi_search(question, num=5)
        if not results:
            return "Web search not available. Set SERPAPI_KEY or disable web routing."
        snippets = "\n".join([f"- {r['title']}: {r.get('snippet','')} ({r.get('link','')})" for r in results])
        system = LIBRARIAN_SYSTEM_PROMPT + "\nRouting: Web"
        prompt = (
            f"{system}\n\nWeb snippets:\n{snippets}\n\n"
            f"Question: {question}\n"
            "Synthesize a short, cautious answer from these snippets; if uncertain, say so and suggest verifying sources."
        )
        if llm is None:
            # fallback: return the snippets for human review
            return "Web snippets:\n" + snippets
        try:
            return llm.completion(prompt, max_tokens=600, temperature=0.3)
        except Exception as e:
            return f"[LLM error] {e}"

    # LLM default path
    system = LIBRARIAN_SYSTEM_PROMPT + "\nRouting: Direct LLM"
    prompt = f"{system}\n\nQuestion: {question}\nBe concise; if unsure, say so."
    if llm is None:
        return "(LLM not configured) Direct LLM path."
    try:
        return llm.completion(prompt, max_tokens=500, temperature=0.3)
    except Exception as e:
        return f"[LLM error] {e}"

# ---- RAG upload + Qdrant indexing ----
def chunk_text(name: str, text: str, max_len: int = 800, overlap: int = 100):
    chunks = []
    i = 0
    idx = 0
    while i < len(text):
        chunk = text[i:i+max_len]
        chunks.append({
            "id": f"{name}-{idx}",
            "text": chunk,
            "meta": {"source": name}
        })
        i += max_len - overlap
        idx += 1
    return chunks

def ui_rag_upload(files: list[gr.File]) -> str:
    if not files:
        return json.dumps({"message": "No files provided."}, indent=2)
    added = []
    for f in files:
        try:
            raw = f.read()
            text = raw.decode("utf-8", errors="ignore")
        except Exception:
            text = ""
        # keep for simple fallback
        RAG_CORPUS[f.name] = text

        # NEW: chunk & index into Qdrant
        chunks = chunk_text(f.name, text)
        upsert_chunks(chunks)

        added.append({"file": f.name, "bytes": len(text), "chunks": len(chunks)})
    return json.dumps({"ingested": added}, indent=2)

# -----------------------
# Build Gradio UI
# -----------------------
with gr.Blocks(title="Agentic RAG MVP — Student & Librarian") as demo:
    gr.Markdown(
        """
        ## 📚 Reading Campaign — Student & Librarian
        - **Student tab**: check popular categories by grade, last week's winner, ask safe questions about books, and log your reading.
        - **Librarian tab**: set the weekly campaign, see top readers by grade, auto-pick winners, ask research questions (with optional web routing), and ingest RAG sources.
        """
    )

    with gr.Tab("Student"):
        gr.Markdown("### Student Dashboard")
        with gr.Row():
            s_grade = gr.Slider(1, 12, value=5, step=1, label="Your Grade")
            refresh_btn = gr.Button("Refresh Overview")
        with gr.Row():
            s_topcats = gr.Dataframe(headers=["Category", "Count"], row_count=5, interactive=False, label="Top 5 Categories in Your Grade")
            s_winner = gr.Code(label="Last Week's Winner (your grade)", language="json")
        refresh_btn.click(ui_student_get_overview, inputs=[s_grade], outputs=[s_topcats, s_winner])

        gr.Markdown("#### Learn more about a book (safe chat)")
        with gr.Row():
            s_book = gr.Dropdown(choices=list(BOOK_DB.keys()), value="bk2", label="Book ID")
            s_q = gr.Textbox(label="Your question", placeholder="e.g., What is the main theme? Is this age-appropriate for grade 5?", lines=2)
        s_ask = gr.Button("Ask")
        s_answer = gr.Textbox(label="Answer", lines=6)
        gr.Markdown(
            "**Safety & tips:** Keep questions specific (themes, characters, reading level). Avoid personal info, external links, or spoilers unless you ask for them."
        )
        gr.Markdown(
            "**Prohibited use:** Do not share personal contact info (emails, phone numbers), do not request or post links, avoid NSFW topics, and do not ask the model to contact you outside this app."
        )
        # Button click and Enter-to-submit
        s_ask.click(ui_student_learn_book, inputs=[s_book, s_q], outputs=[s_answer])
        s_q.submit(ui_student_learn_book, inputs=[s_book, s_q], outputs=[s_answer])

        gr.Markdown("#### Log a finished book (counts toward weekly prize)")
        with gr.Row():
            s_name = gr.Textbox(label="Your Name", placeholder="First name & last initial (e.g., Sam T.)")
            s_book_log = gr.Dropdown(choices=list(BOOK_DB.keys()), value="bk2", label="Book ID")
            log_btn = gr.Button("Log Book")
        s_log_msg = gr.Textbox(label="Log Status", interactive=False)
        s_leader = gr.Dataframe(headers=["Student", "Count", "Books"], row_count=5, interactive=False, label="Top 5 Readers (your grade)")
        log_btn.click(ui_student_log_read, inputs=[s_grade, s_name, s_book_log], outputs=[s_log_msg, s_leader])

    with gr.Tab("Librarian"):
        gr.Markdown("### Librarian Console")

        with gr.Accordion("Campaign Setup", open=True):
            l_title = gr.Textbox(label="Campaign Title", value=CAMPAIGN["title"])
            l_prize = gr.Textbox(label="Prize Rules", value=CAMPAIGN["prize_rules"])
            l_categories = gr.CheckboxGroup(choices=list({*CAMPAIGN["categories"], *[b.get("category", "other") for b in BOOK_DB.values()]}),
                                            value=CAMPAIGN["categories"], label="Categories")
            with gr.Row():
                l_start = gr.Textbox(label="Start Date (YYYY-MM-DD)")
                l_end = gr.Textbox(label="End Date (YYYY-MM-DD)")
            l_seed = gr.CheckboxGroup(choices=list(BOOK_DB.keys()), value=CAMPAIGN["seed_list"], label="Featured Seed Books")
            apply_btn = gr.Button("Apply Campaign Settings")
            l_campaign_json = gr.Code(label="Current Campaign JSON", language="json")
            apply_btn.click(ui_librarian_set_campaign, inputs=[l_title, l_prize, l_categories, l_start, l_end, l_seed], outputs=[l_campaign_json])

        with gr.Accordion("Leaderboards & Winners", open=True):
            l_grade = gr.Slider(1, 12, value=5, step=1, label="Grade")
            l_refresh = gr.Button("Refresh Leaderboard")
            l_table = gr.Dataframe(headers=["Student", "Count", "Books"], row_count=5, interactive=False)
            l_refresh.click(ui_librarian_leaderboard, inputs=[l_grade], outputs=[l_table])

            pick_btn = gr.Button("Pick Weekly Winner (by grade)")
            l_winner = gr.Code(label="Winner JSON", language="json")
            pick_btn.click(ui_librarian_pick_winner, inputs=[l_grade], outputs=[l_winner])

        with gr.Accordion("Research Assistant (Prompt)", open=False):
            with gr.Row():
                l_book = gr.Dropdown(choices=list(BOOK_DB.keys()), value="bk2", label="(Optional) Book ID")
                l_allow_web = gr.Checkbox(label="Allow web routing (suggest web sources)", value=False)
            l_q = gr.Textbox(label="Your question", placeholder="e.g., Provide a 3-sentence summary and reading level guidance.", lines=2)
            l_ask = gr.Button("Ask")
            l_ans = gr.Textbox(label="Answer", lines=10)
            l_ask.click(ui_librarian_book_prompt, inputs=[l_book, l_q, l_allow_web], outputs=[l_ans])

        with gr.Accordion("Agentic RAG — Upload Sources", open=False):
            rag_files = gr.Files(label="Upload text/CSV/JSON files from other schools, publications, etc.")
            ingest_btn = gr.Button("Ingest to RAG (demo)")
            rag_status = gr.Code(label="Ingestion Status", language="json")
            ingest_btn.click(ui_rag_upload, inputs=[rag_files], outputs=[rag_status])

# Mount Gradio into FastAPI so UI and API live together
from gradio.routes import mount_gradio_app
app = mount_gradio_app(app, demo, path="/")

if __name__ == "__main__":
    # Run the combined FastAPI + Gradio app
    import uvicorn
    uvicorn.run(app, host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")))