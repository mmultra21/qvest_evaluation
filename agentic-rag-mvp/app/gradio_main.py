# app/gradio_main.py
from __future__ import annotations

import os
import io
import json
import re
from typing import List, Dict, Any, Optional, Tuple

from dotenv import load_dotenv
load_dotenv()  # load .env from project root early

# --- FastAPI base app (API + Gradio mounted) ---
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

import gradio as gr

# --- Project modules ---
from api.routes import llm as llm_routes
from api.tools.recommender import rank_candidates
from api.tools import rag
from api.models_llm import JustifyResponse

# Vector store & web
from app.vector_store import upsert_chunks, stats as vs_stats, search as vs_search
from app.web_search import serpapi_search
from app.web_search import format_results_bullets  # result -> bullet list formatter

# ---------- LLM (Hermes-3 via llama.cpp) ----------
import requests
import json as _json

LLM_URL = os.getenv("LLM_URL", "http://127.0.0.1:11434").rstrip("/")

class _FallbackLLM:
    """Minimal llama.cpp client: prefers /chat; falls back to /completion with Assistant cue."""
    def __init__(self, base_url: str):
        self.base = base_url

    def completion(self, prompt: str, max_tokens: int = 512, temperature: float = 0.2):
        # Ensure clear assistant turn and sensible stop sequences
        prompt = prompt.rstrip() + "\nAssistant:"
        payload = {
            "prompt": prompt,
            "n_predict": max_tokens,
            "temperature": temperature,
            "cache_prompt": True,
            "stop": ["\nUser:", "User:", "</s>", "<|eot_id|>", "<|end|>"],
        }
        r = requests.post(f"{self.base}/completion", json=payload, timeout=120)
        r.raise_for_status()
        data = r.json()
        return data.get("content") or data.get("response") or _json.dumps(data)

    def chat(self, messages, max_tokens: int = 512, temperature: float = 0.2):
        payload = {
            "messages": messages,
            "temperature": temperature,
            "n_predict": max_tokens,
        }
        r = requests.post(f"{self.base}/chat", json=payload, timeout=120)
        if r.status_code == 404:
            # Synthesize a completion-style prompt
            sys = "\n".join(m["content"] for m in messages if m["role"] == "system")
            usr = "\n".join(m["content"] for m in messages if m["role"] == "user")
            fused = (sys + "\n\nUser:\n" + usr + "\nAssistant:").strip()
            return self.completion(fused, max_tokens=max_tokens, temperature=temperature)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict) and isinstance(data.get("message"), dict):
            return data["message"].get("content") or _json.dumps(data)
        return data.get("content") or data.get("response") or _json.dumps(data)

# Prefer project client if available
try:
    from api.models_llm import LLMClient as _ProjectLLM
    llm = _ProjectLLM(base_url=LLM_URL)
except Exception:
    llm = _FallbackLLM(LLM_URL)

# ---------- FastAPI app ----------
app = FastAPI(title="Agentic RAG MVP API")
app.include_router(llm_routes.router)

# ---------- In-memory demo data ----------
CAMPAIGN: Dict[str, Any] = {
    "title": "Reading Week Spotlight",
    "prize_rules": "Prize for most books read in the week by grade.",
    "seed_list": ["bk2", "bk6"],
    "categories": ["fiction", "non-fiction", "sports", "mystery", "science", "history", "fantasy", "animals"],
    "start_date": None,
    "end_date": None,
}

READ_LOGS: Dict[int, Dict[str, Dict[str, Any]]] = {}       # per-grade reading logs
LAST_WEEK_WINNERS: Dict[int, Dict[str, Any]] = {}          # per-grade winners
BOOK_PREFS: Dict[int, Dict[str, int]] = {}                 # per-grade category counts

BOOK_DB: Dict[str, Dict[str, Any]] = {
    "bk1": {"title": "Trail Adventures", "author": "K. Jay", "category": "adventure", "lexile": 750},
    "bk2": {"title": "Oceans Explained", "author": "R. Lee", "category": "science", "lexile": 820},
    "bk3": {"title": "Legends of the Field", "author": "M. Soto", "category": "sports", "lexile": 680},
    "bk4": {"title": "Time Detectives", "author": "N. Chen", "category": "mystery", "lexile": 700},
    "bk5": {"title": "Wild History", "author": "A. Diaz", "category": "history", "lexile": 790},
    "bk6": {"title": "Forest Tales", "author": "S. Wilde", "category": "fantasy", "lexile": 720},
}

# Keep raw text for inspect/debug (filename -> text)
RAG_CORPUS: Dict[str, str] = {}

# ---------- Pydantic models for API ----------
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

# ---------- API endpoints ----------
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

# ---------- Guardrails ----------
SAFE_BOOK_CHAT_RULES = (
    "Use age-appropriate language. Avoid spoilers unless asked. "
    "Never provide personal contact links. Do not invent facts; if unsure, say so."
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
Always answer as a single concise paragraph unless the user asks for a list or multiple items.
""".strip()

BLOCKED_KEYWORDS = [
    "adult content", "explicit", "contact me", "social media dms", "nsfw",
]

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

# ---------- Leaderboard utils ----------
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

# ---------- Student UI callbacks ----------
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
    try:
        messages = [
            {"role": "system", "content": STUDENT_SYSTEM_PROMPT},
            {"role": "user", "content": f"Context: {context}\n\nQuestion: {question}"},
        ]
        return llm.chat(messages, max_tokens=400, temperature=0.3)
    except Exception as e:
        # fallback to completion
        plain_prompt = f"{STUDENT_SYSTEM_PROMPT}\n\nContext: {context}\n\nQuestion: {question}"
        try:
            return llm.completion(plain_prompt, max_tokens=400, temperature=0.3)
        except Exception as e2:
            return f"[LLM error] {e2}"

def ui_student_log_read(grade: int, student_name: str, book_id: str):
    if not student_name.strip():
        return "Please enter your name to log a book.", []
    if book_id not in BOOK_DB:
        return f"Unknown book id: {book_id}", []
    record_reading(grade, student_name.strip(), book_id)
    top5 = top_readers_by_grade(grade, 5)
    table = [[name, count, ", ".join(books)] for name, count, books in top5] or [["(no data)", 0, ""]]
    return f"Logged '{BOOK_DB[book_id]['title']}' for {student_name}!", table

# ---------- Librarian research helpers ----------
def synthesize_from_hits(question: str, hits):
    ctx = []
    for h in hits[:5]:
        payload = getattr(h, "payload", {}) or {}
        ctx.append((payload.get("text") or "")[:800])
    return "\n\n".join(ctx)

def _format_snippets(hits, k: int = 3, char_limit: int = 260) -> str:
    lines = []
    for h in (hits or [])[:k]:
        payload = getattr(h, "payload", {}) or {}
        src = payload.get("source") or payload.get("meta", {}).get("source") or "unknown"
        txt_full = (payload.get("text") or "")
        txt = txt_full[:char_limit].replace("\n", " ").strip()
        tail = "…" if len(txt_full) > char_limit else ""
        lines.append(f"- [{h.score:.3f}] {src}: {txt}{tail}")
    return "\n".join(lines) if lines else "(no snippets)"

# --- Recency-aware routing ---
RECENCY_TRIGGERS = {
    "as of today", "today", "right now", "currently", "current", "latest",
    "who is", "who’s", "who's", "in charge of", "ceo", "director", "register of copyrights",
    "head of", "chair", "president", "governor", "mayor", "this week", "this month", "2024", "2025",
}

def wants_freshness(q: str) -> bool:
    ql = (q or "").lower()
    return any(t in ql for t in RECENCY_TRIGGERS)

def route_recency_aware(question: str, allow_web: bool, vs_threshold: float = 0.40):
    """
    Minimal router:
    - If allow_web and the question looks time-sensitive -> web
    - Else vector if best score >= threshold
    - Else web if allowed
    - Else direct llm
    """
    hits = vs_search(question, top_k=5)
    best_score = hits[0].score if hits else 0.0

    if allow_web and wants_freshness(question):
        return {"route": "web", "hits": hits, "best_score": best_score}

    if best_score >= vs_threshold:
        return {"route": "vector", "hits": hits, "best_score": best_score}

    if allow_web:
        return {"route": "web", "hits": hits, "best_score": best_score}

    return {"route": "llm", "hits": hits, "best_score": best_score}

# ---------- Librarian main prompt (router-aware, narrative + snippets) ----------
def ui_librarian_book_prompt(book_id: str, question: str, allow_web: bool, show_snippets: bool = True, debug: bool = False):
    ok, msg = is_prompt_safe(question)
    if not ok:
        return msg

    plan = route_recency_aware(question, allow_web=allow_web, vs_threshold=0.40)
    route_used = plan["route"]
    hits = plan["hits"]

    style = (
        "Answer in a concise narrative paragraph (3–6 sentences). "
        "Avoid Q&A headings. If the question is time-sensitive, include specific dates. "
        "If uncertain, say so briefly."
    )

    # VECTOR path
    if route_used == "vector":
        context_text = synthesize_from_hits(question, hits)
        system = LIBRARIAN_SYSTEM_PROMPT + "\nRouting: VectorStore"
        prompt = (
            f"{system}\n\n{style}\n\n"
            f"Context:\n{context_text}\n\n"
            f"Question: {question}\n"
            "Write a single concise paragraph grounded in the context."
        )
        try:
            answer = llm.completion(prompt, max_tokens=600, temperature=0.2)
        except Exception as e:
            return f"[LLM error] {e}"

        if show_snippets:
            answer += "\n\n---\nTop context snippets:\n" + _format_snippets(hits, k=3, char_limit=260)
        if debug:
            try:
                best = float(plan.get('best_score') or 0.0)
            except Exception:
                best = 0.0
            answer += f"\n\n---\n[debug] route=vector best_score={best:.3f}"
        return answer

    # WEB path
    if route_used == "web":
        try:
            # Try targeted official site first for leadership/role queries
            ql = (question or "").lower()
            prefer_site = None
            if any(t in ql for t in ["copyright office", "register of copyrights", "copyright.gov"]):
                prefer_site = "copyright.gov"

            results = []
            if prefer_site:
                results = serpapi_search(question, num=5, site=prefer_site)
            if not results:
                results = serpapi_search(question, num=5)
        except Exception as e:
            return f"Web search error: {e}"

        if not results:
            if hits:
                snippet = (hits[0].payload or {}).get("text", "")[:200].replace("\n", " ")
                return ("(Web search returned no results; showing local context instead) "
                        f"{snippet}…")
            return "Web search returned no results."

        web_snips = "\n".join([f"- {r['title']}: {r.get('snippet','')} ({r.get('link','')}) [{r.get('source','web')}]" for r in results])
        system = (
            LIBRARIAN_SYSTEM_PROMPT
            + "\nRouting: Web\n"
            + "Web access is explicitly authorized for this question. "
              "Use the provided web snippets as evidence. Do not refuse web use."
        )
        prompt = (
            f"{system}\n\n{style}\n\n"
            f"Web snippets:\n{web_snips}\n\n"
            f"Question: {question}\n"
            "Synthesize a short, cautious paragraph from these snippets; include specific names/dates when relevant. "
            "If uncertain, say so briefly and suggest verifying sources."
        )
        try:
            answer = llm.completion(prompt, max_tokens=600, temperature=0.3)
        except Exception as e:
            return f"[LLM error] {e}"

        if debug:
            try:
                best = float(plan.get('best_score') or 0.0)
            except Exception:
                best = 0.0
            sources = [r.get('source', 'web') for r in results]
            bullets = ""
            try:
                bullets = format_results_bullets(results)
            except Exception:
                bullets = web_snips
            answer += (
                f"\n\n---\n[debug] route=web best_score={best:.3f} "
                f"web_hits={len(results)} surfaces={sorted(set(sources))}\n\n{bullets}"
            )
        return answer

    # LLM default path
    system = LIBRARIAN_SYSTEM_PROMPT + "\nRouting: Direct LLM"
    prompt = f"{system}\n\n{style}\n\nQuestion: {question}\nWrite one concise paragraph."
    try:
        answer = llm.completion(prompt, max_tokens=500, temperature=0.3)
    except Exception as e:
        return f"[LLM error] {e}"
    if debug:
        try:
            best = float(plan.get('best_score') or 0.0)
        except Exception:
            best = 0.0
        answer += f"\n\n---\n[debug] route=llm best_score={best:.3f}"
    return answer

# ---------- RAG upload handlers ----------
TEXT_EXTS = {".txt", ".md", ".csv", ".json"}
DOCX_EXT = ".docx"
PDF_EXT = ".pdf"

def is_texty(name: str) -> bool:
    _, ext = os.path.splitext(name.lower())
    return ext in TEXT_EXTS

def _read_file_by_path(path: str) -> Tuple[str, str]:
    """Return (name, text) for supported file types."""
    name = os.path.basename(path)
    ext = os.path.splitext(name.lower())[1]
    if ext in TEXT_EXTS:
        with open(path, "rb") as f:
            raw = f.read()
        return name, raw.decode("utf-8", errors="ignore")
    if ext == DOCX_EXT:
        try:
            import docx2txt
        except Exception as e:
            raise RuntimeError("docx2txt is required for .docx ingestion (pip install docx2txt)") from e
        text = docx2txt.process(path) or ""
        return name, text
    if ext == PDF_EXT:
        try:
            import pdfplumber
        except Exception as e:
            raise RuntimeError("pdfplumber is required for .pdf ingestion (pip install pdfplumber)") from e
        text_parts = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                txt = page.extract_text() or ""
                if txt.strip():
                    text_parts.append(txt)
        return name, "\n\n".join(text_parts)
    raise RuntimeError("unsupported extension (use .txt/.md/.csv/.json/.docx/.pdf)")

def chunk_text(name: str, text: str, max_len: int = 800, overlap: int = 100, min_len: int = 40):
    chunks = []
    i = 0
    idx = 0
    while i < len(text):
        piece = text[i:i+max_len]
        if len(piece.strip()) >= min_len:
            chunks.append({
                "id": f"{name}-{idx}",
                "text": piece,
                "meta": {"source": name}
            })
            idx += 1
        i += max_len - overlap
    return chunks

def ui_rag_upload(filepaths: list[str] | None) -> str:
    if not filepaths:
        return json.dumps({"message": "No files provided."}, indent=2)

    files = filepaths if isinstance(filepaths, list) else [filepaths]
    report = {"ingested": [], "skipped": []}

    for path in files:
        try:
            name, text = _read_file_by_path(path)
        except Exception as e:
            report["skipped"].append({"file": os.path.basename(str(path)), "reason": str(e)})
            continue

        if not text.strip():
            report["skipped"].append({"file": name, "reason": "empty content"})
            continue

        # keep raw text for fallback inspect
        RAG_CORPUS[name] = text

        chunks = chunk_text(name, text)
        try:
            n = upsert_chunks(chunks)
            if n > 0:
                report["ingested"].append({"file": name, "bytes": len(text.encode("utf-8", errors="ignore")), "chunks": n})
            else:
                report["skipped"].append({"file": name, "reason": "no valid chunks"})
        except Exception as e:
            report["skipped"].append({"file": name, "reason": f"qdrant error: {e}"})

    return json.dumps(report, indent=2)

# ---------- Admin helpers ----------
def web_status() -> str:
    """Return JSON showing whether SERPAPI_KEY is set and if a quick ping works."""
    key = os.getenv("SERPAPI_KEY")
    if not key:
        return json.dumps({
            "serpapi": "missing",
            "hint": "Add SERPAPI_KEY to .env or export it in your shell; restart the app."
        }, indent=2)

    masked = (key[:4] + "..." + key[-4:]) if len(key) >= 8 else "***"
    try:
        rs = serpapi_search("site:copyright.gov Register of Copyrights", num=1)
        ok = bool(rs)
        return json.dumps({
            "serpapi": "present",
            "key": masked,
            "ping": "ok" if ok else "no-results"
        }, indent=2)
    except Exception as e:
        return json.dumps({
            "serpapi": "present",
            "key": masked,
            "ping": "error",
            "error": str(e)
        }, indent=2)

# ---------- Build Gradio UI ----------
with gr.Blocks(title="Agentic RAG MVP — Student & Librarian") as demo:
    gr.Markdown(
        """
        ## 📚 Reading Campaign — Student & Librarian
        - **Student tab**: check popular categories by grade, last week's winner, ask safe questions about books, and log your reading.
        - **Librarian tab**: set the weekly campaign, see top readers by grade, auto-pick winners, router-aware research (with optional web routing), ingest RAG sources, and view Qdrant stats.
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

            # NEW: Clear button to reset question and answer fields
            s_clear = gr.Button("Clear")
            s_clear.click(lambda: ("", ""), inputs=None, outputs=[s_q, s_answer])

        gr.Markdown("**Safety & tips:** Keep questions specific (themes, characters, reading level). Avoid personal info, external links, or spoilers unless you ask for them.")
        gr.Markdown("**Prohibited use:** Do not share personal contact info (emails, phone numbers), do not request or post links, avoid NSFW topics, and do not ask the model to contact you outside this app.")
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
            l_categories = gr.CheckboxGroup(
                choices=list({*CAMPAIGN["categories"], *[b.get("category", "other") for b in BOOK_DB.values()]}),
                value=CAMPAIGN["categories"],
                label="Categories"
            )
            with gr.Row():
                l_start = gr.Textbox(label="Start Date (YYYY-MM-DD)")
                l_end = gr.Textbox(label="End Date (YYYY-MM-DD)")
            l_seed = gr.CheckboxGroup(choices=list(BOOK_DB.keys()), value=CAMPAIGN["seed_list"], label="Featured Seed Books")
            apply_btn = gr.Button("Apply Campaign Settings")
            l_campaign_json = gr.Code(label="Current Campaign JSON", language="json")
            def _ui_librarian_set_campaign(title: str, prize_rules: str, categories: List[str], start: str, end: str, seed_list: List[str]):
                CAMPAIGN.update({
                    "title": title or CAMPAIGN["title"],
                    "prize_rules": prize_rules or CAMPAIGN["prize_rules"],
                    "categories": categories or CAMPAIGN["categories"],
                    "start_date": start or None,
                    "end_date": end or None,
                    "seed_list": seed_list or CAMPAIGN["seed_list"],
                })
                return json.dumps(CAMPAIGN, indent=2)
            apply_btn.click(_ui_librarian_set_campaign, inputs=[l_title, l_prize, l_categories, l_start, l_end, l_seed], outputs=[l_campaign_json])

        with gr.Accordion("Leaderboards & Winners", open=True):
            l_grade = gr.Slider(1, 12, value=5, step=1, label="Grade")
            l_refresh = gr.Button("Refresh Leaderboard")
            l_table = gr.Dataframe(headers=["Student", "Count", "Books"], row_count=5, interactive=False)
            l_refresh.click(lambda g: [[n, c, ", ".join(b)] for n, c, b in top_readers_by_grade(g, 5)] or [["(no data)", 0, ""]], inputs=[l_grade], outputs=[l_table])

            pick_btn = gr.Button("Pick Weekly Winner (by grade)")
            l_winner = gr.Code(label="Winner JSON", language="json")
            def _ui_librarian_pick_winner(grade: int):
                top5 = top_readers_by_grade(grade, 1)
                if not top5:
                    return json.dumps({"message": "No readers yet."}, indent=2)
                name, count, books = top5[0]
                LAST_WEEK_WINNERS[grade] = {"student": name, "count": count, "books": books}
                return json.dumps({"winner": LAST_WEEK_WINNERS[grade]}, indent=2)
            pick_btn.click(_ui_librarian_pick_winner, inputs=[l_grade], outputs=[l_winner])

        with gr.Accordion("Research Assistant (Prompt)", open=False):
            with gr.Row():
                l_book = gr.Dropdown(choices=list(BOOK_DB.keys()), value="bk2", label="(Optional) Book ID")
                l_allow_web = gr.Checkbox(label="Allow web routing (suggest web sources)", value=True)
                l_show_snips = gr.Checkbox(label="Show context snippets", value=True)
                l_debug = gr.Checkbox(label="Show routing debug", value=False)
            l_q = gr.Textbox(label="Your question", placeholder="e.g., As of today, who is the Register of Copyrights?", lines=2)
            l_ask = gr.Button("Ask")
            l_ans = gr.Textbox(label="Answer", lines=12)
            l_ask.click(ui_librarian_book_prompt, inputs=[l_book, l_q, l_allow_web, l_show_snips, l_debug], outputs=[l_ans])

            # NEW: Clear button for Research Assistant
            l_clear = gr.Button("Clear")
            l_clear.click(lambda: ("", ""), inputs=None, outputs=[l_q, l_ans])

        with gr.Accordion("Agentic RAG — Upload Sources", open=False):
            rag_files = gr.Files(label="Upload text/CSV/JSON/DOCX/PDF files", type="filepath")
            ingest_btn = gr.Button("Ingest to RAG (demo)")
            rag_status = gr.Code(label="Ingestion Status", language="json")
            ingest_btn.click(ui_rag_upload, inputs=[rag_files], outputs=[rag_status])

            # NEW: Clear ingestion status
            rag_clear = gr.Button("Clear Ingestion Status")
            rag_clear.click(lambda: "", inputs=None, outputs=[rag_status])

        with gr.Accordion("Admin — Vector Store Stats", open=False):
            stats_btn = gr.Button("Refresh Stats")
            stats_box = gr.Code(label="Qdrant / Embedding Stats", language="json")
            stats_btn.click(lambda: json.dumps(vs_stats(), indent=2), inputs=[], outputs=[stats_box])

            web_btn = gr.Button("Check Web (SerpAPI)")
            web_box = gr.Code(label="Web Status", language="json")
            web_btn.click(lambda: web_status(), outputs=[web_box])

# Mount Gradio into FastAPI so UI and API live together
from gradio.routes import mount_gradio_app
app = mount_gradio_app(app, demo, path="/")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")))