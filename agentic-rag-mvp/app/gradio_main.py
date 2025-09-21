# app/gradio_main.py
from __future__ import annotations

import os
import io
import json
import datetime
import re
import glob
import hashlib
import unicodedata
from typing import List, Dict, Any, Optional, Tuple, TypedDict

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

# ---- Lightweight read events (for time-based aggregation) ----
class ReadEvent(TypedDict):
    ts: int
    grade: int
    student: str
    book_id: str

READ_EVENTS: list[ReadEvent] = []  # append when a book is approved

import time
import uuid
from datetime import datetime

# Pending approvals store (each item awaits quiz + librarian approval)
# PENDING_LOGS[grade] = [ {id, ts, student, book_id, quiz_passed, status}, ... ]
PENDING_LOGS: Dict[int, List[Dict[str, Any]]] = {}

# --- Book Requests (student-initiated) ---
# Each item: {id, ts, grade, student, book_id, title, lexile, category, date_needed, special, status, availability_date}
BOOK_REQUESTS: list[dict] = []

def _stable_book_id(title: str, author: str) -> str:
    """Stable ID from title+author to avoid reordering collisions."""
    base = f"{title}|{author}".encode("utf-8")
    return "bk" + hashlib.sha1(base).hexdigest()[:8]


def _norm(s: str) -> str:
    return (unicodedata.normalize("NFKC", s or "").strip())


def _validate_iso_date_or_none(s: str | None) -> str | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return s
    except Exception:
        raise gr.Error(f"Invalid date: {s!r}. Use YYYY-MM-DD.")


def _book_label_choices():
    # (label, value) for dropdown
    items = []
    for bid, info in BOOK_DB.items():
        t = info.get("title", bid)
        a = info.get("author", "Unknown")
        lex = info.get("lexile", "—")
        items.append((f"{t} — {a} (Lexile {lex})", bid))
    items.sort(key=lambda x: x[0].lower())
    return items


def _prefill_request_fields(book_id: str):
    info = BOOK_DB.get(book_id, {})
    return info.get("lexile", None), info.get("category", None)


def _student_requests_table(grade: int, name: str):
    name = (name or "").strip()
    rows = []
    for r in BOOK_REQUESTS:
        if int(r["grade"]) == int(grade) and (not name or r["student"] == name):
            ts = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(r["ts"]))
            rows.append([
                ts,
                r["title"],
                r["lexile"] if r["lexile"] is not None else "—",
                r["category"] or "—",
                r["date_needed"] or "—",
                r["status"],
                r.get("availability_date") or "—",
            ])
    if not rows:
        rows = [["(no requests yet)", "", "", "", "", "", ""]]
    return rows


def _librarian_requests_table(only_pending: bool = True):
    rows = []
    for r in BOOK_REQUESTS:
        if only_pending and r["status"] != "pending":
            continue
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(r["ts"]))
        rows.append([
            r["id"],
            ts,
            r["grade"],
            r["student"],
            r["title"],
            r["lexile"] if r["lexile"] is not None else "—",
            r["category"] or "—",
            r["date_needed"] or "—",
            r["status"],
            r.get("availability_date") or "—",
        ])
    if not rows:
        rows = [["(none)", "", "", "", "", "", "", "", "", ""]]
    return rows


def _find_request_by_id(req_id: str) -> dict | None:
    for r in BOOK_REQUESTS:
        if r["id"] == req_id:
            return r
    return None


def _to_date(v):
    if isinstance(v, datetime.date):
        return v
    if isinstance(v, str) and v:
        try:
            return datetime.date.fromisoformat(v)
        except Exception:
            return None
    return None


def _load_books_from_json(paths: list[str]) -> Dict[str, Dict[str, Any]]:
    """
    Load one or more JSON files into a BOOK_DB dict:
    Expected item fields (flexible): title, author, category, grade_range, lexile, id
    If id missing, one is generated from title+author.
    """
    out: Dict[str, Dict[str, Any]] = {}
    for p in paths:
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        # data could be a list or an object with "books"
        items = data if isinstance(data, list) else data.get("books", [])
        for it in items:
            title = _norm(it.get("title", ""))
            author = _norm(it.get("author", ""))
            if not title:
                continue
            bid = _norm(it.get("id", "")) or _stable_book_id(title, author)
            out[bid] = {
                "title": title,
                "author": author or "Unknown",
                "category": _norm(it.get("category", "other")),
                "grade_range": it.get("grade_range"),
                "lexile": it.get("lexile") or it.get("lexile_level") or None,
            }
    return out


def _default_demo_books() -> Dict[str, Dict[str, Any]]:
    return {
        "bk1": {"title": "Trail Adventures", "author": "K. Jay", "category": "adventure", "lexile": 750},
        "bk2": {"title": "Oceans Explained", "author": "R. Lee", "category": "science", "lexile": 820},
        "bk3": {"title": "Legends of the Field", "author": "M. Soto", "category": "sports", "lexile": 680},
        "bk4": {"title": "Time Detectives", "author": "N. Chen", "category": "mystery", "lexile": 700},
        "bk5": {"title": "Wild History", "author": "A. Diaz", "category": "history", "lexile": 790},
        "bk6": {"title": "Forest Tales", "author": "S. Wilde", "category": "fantasy", "lexile": 720},
    }


def _load_books_at_startup() -> Dict[str, Dict[str, Any]]:
    """
    Try to load from env-configured paths first:
      - BOOKS_JSON (single file)
      - BOOKS_GLOB (glob, e.g., data/*books*.json)
    Fallback: data/fiction_childrens_books_curated.json, then demo.
    """
    paths: list[str] = []
    env_one = os.getenv("BOOKS_JSON")
    env_glob = os.getenv("BOOKS_GLOB")
    if env_one:
        paths.append(env_one)
    if env_glob:
        paths.extend(sorted(glob.glob(env_glob)))
    # sensible default
    default_path = os.path.join(os.getcwd(), "data", "fiction_childrens_books_curated.json")
    if not paths and os.path.exists(default_path):
        paths.append(default_path)

    books = _load_books_from_json(paths) if paths else {}
    return books or _default_demo_books()


# --- replace the old BOOK_DB with this:
BOOK_DB: Dict[str, Dict[str, Any]] = _load_books_at_startup()


def book_label(bid: str, info: Dict[str, Any]) -> str:
    """Human-readable label for dropdowns."""
    bits = [info.get("title", "Untitled")]
    if info.get("author"):
        bits.append(f"— {info['author']}")
    if info.get("category"):
        bits.append(f"({info['category']})")
    return " ".join(bits)


def BOOK_CHOICES() -> List[tuple[str, str]]:
    """[(label, value)] for Gradio Dropdown."""
    items = []
    for bid, info in BOOK_DB.items():
        items.append((book_label(bid, info), bid))
    # Keep choices stable in display order (title sort)
    items.sort(key=lambda x: x[0].lower())
    return items


def FIRST_BOOK_ID_DEFAULT() -> Optional[str]:
    try:
        return BOOK_CHOICES()[0][1]
    except Exception:
        return None


def _grade_range_str(gr):
    if not gr:
        return "All grades"
    # Accept forms like "5-8", [5,8], "6", or {"min":6,"max":8}
    try:
        if isinstance(gr, str):
            if "-" in gr:
                a, b = gr.split("-", 1)
                return f"Grades {int(a)}–{int(b)}"
            g = int(gr)
            return f"Grade {g}"
        if isinstance(gr, (list, tuple)) and len(gr) == 2:
            return f"Grades {int(gr[0])}–{int(gr[1])}"
        if isinstance(gr, dict):
            mn = int(gr.get("min")) if gr.get("min") is not None else None
            mx = int(gr.get("max")) if gr.get("max") is not None else None
            if mn and mx:
                return f"Grades {mn}–{mx}"
            if mn and not mx:
                return f"Grades {mn}+"
            if mx and not mn:
                return f"Up to Grade {mx}"
    except Exception:
        pass
    return "All grades"


def _grade_in_range(student_grade: int, gr) -> bool:
    if not gr:
        return True
    try:
        if isinstance(gr, str):
            if "-" in gr:
                a, b = gr.split("-", 1)
                return int(a) <= student_grade <= int(b)
            return int(gr) == student_grade
        if isinstance(gr, (list, tuple)) and len(gr) == 2:
            return int(gr[0]) <= student_grade <= int(gr[1])
        if isinstance(gr, dict):
            mn = gr.get("min"); mx = gr.get("max")
            if mn is not None and student_grade < int(mn): return False
            if mx is not None and student_grade > int(mx): return False
            return True
    except Exception:
        return True
    return True


def SEED_BOOK_CHOICES() -> list[tuple[str, str]]:
    """[(label, value)] for the librarian Featured Seed Books picker."""
    items = []
    for bid, info in BOOK_DB.items():
        title = info.get("title", "Untitled")
        author = info.get("author", "Unknown")
        lex = info.get("lexile", "—")
        grs = _grade_range_str(info.get("grade_range"))
        label = f"{title} — {author} (Lexile {lex}; {grs})"
        items.append((label, bid))
    items.sort(key=lambda x: x[0].lower())
    return items


def render_recommended_for_grade(grade: int) -> str:
    """Markdown list of librarian seed picks filtered by grade_range."""
    bids = CAMPAIGN.get("seed_list") or []
    lines = []
    for bid in bids:
        info = BOOK_DB.get(bid) or {}
        if not info:
            continue
        if not _grade_in_range(int(grade), info.get("grade_range")):
            continue
        title = info.get("title", bid)
        author = info.get("author", "Unknown")
        cat = info.get("category", "other")
        lex = info.get("lexile", "—")
        grs = _grade_range_str(info.get("grade_range"))
        lines.append(f"- *{title}* — {author}  •  `{cat}`  •  **Lexile {lex}**  •  {grs}")
    if not lines:
        return "_No librarian picks for your grade yet._"
    return "\n".join(lines)

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
def record_reading(grade: int, student_name: str, catalog_id: str, *, ts: int | None = None):
    grade = int(grade)
    READ_LOGS.setdefault(grade, {})
    student = READ_LOGS[grade].setdefault(student_name, {"count": 0, "books": []})
    student["count"] += 1
    student["books"].append(catalog_id)

    BOOK_PREFS.setdefault(grade, {})
    cat = BOOK_DB.get(catalog_id, {}).get("category", "other")
    BOOK_PREFS[grade][cat] = BOOK_PREFS[grade].get(cat, 0) + 1

    # NEW: add an event (used for metrics)
    READ_EVENTS.append({
        "ts": ts or int(time.time()),
        "grade": grade,
        "student": student_name,
        "book_id": catalog_id,
    })


def add_pending_log(grade: int, student: str, book_id: str, quiz_passed: bool = False, quiz_answer: str = ""):
    grade = int(grade)
    PENDING_LOGS.setdefault(grade, [])
    PENDING_LOGS[grade].append({
        "id": f"req_{uuid.uuid4().hex[:8]}",
        "ts": int(time.time()),
        "student": student,
        "book_id": book_id,
        "quiz_answer": (quiz_answer or "").strip(),
        "quiz_passed": quiz_passed,
        "status": "pending_approval" if quiz_passed else "pending_quiz",
    })


def pending_label(item: Dict[str, Any]) -> str:
    info = BOOK_DB.get(item["book_id"], {})
    title = info.get("title", item["book_id"])
    lex = info.get("lexile", "—")
    who = item.get("student", "Unknown")
    return f'{item.get("id")} — {who} — {title} (Lexile {lex}) — {item.get("status")}'

def top_readers_by_grade(grade: int, k: int = 5):
    entries = READ_LOGS.get(grade, {})
    ranked = sorted(entries.items(), key=lambda kv: kv[1]["count"], reverse=True)
    return [(name, data["count"], data["books"]) for name, data in ranked[:k]]

def top_categories_for_grade(grade: int, k: int = 5):
    prefs = BOOK_PREFS.get(grade, {})
    ranked = sorted(prefs.items(), key=lambda kv: kv[1], reverse=True)
    return ranked[:k]

def avg_lexile_by_category_for_grade(grade: int):
    """Compute average Lexile per category for books actually logged by this grade."""
    entries = READ_LOGS.get(int(grade), {})
    # collect all book_ids read in this grade
    book_ids = []
    for s in entries.values():
        book_ids.extend(s.get("books", []))

    from collections import defaultdict
    sums = defaultdict(int)
    counts = defaultdict(int)

    for bid in book_ids:
        info = BOOK_DB.get(bid) or {}
        cat = info.get("category", "other")
        lx = info.get("lexile")
        if isinstance(lx, (int, float)):
            sums[cat] += lx
            counts[cat] += 1

    rows = []
    for cat in sorted(set(list(sums.keys()) + list(counts.keys()))):
        c = counts.get(cat, 0)
        avg = round(sums[cat] / c, 1) if c else None
        rows.append([cat, c, avg])
    # sort by count desc, then by category
    rows.sort(key=lambda r: (-r[1], r[0]))
    return rows


# ---- Metrics helpers ----
import pandas as pd
import matplotlib.pyplot as plt
from io import StringIO
import tempfile
import json as _json
import os as _os

def _events_df() -> pd.DataFrame:
    if not READ_EVENTS:
        return pd.DataFrame(columns=["ts","date","year","quarter","grade","student","book_id","title"])
    df = pd.DataFrame(READ_EVENTS)
    df["date"] = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_convert("UTC").dt.date
    df["year"] = pd.to_datetime(df["ts"], unit="s", utc=True).dt.year
    q = pd.to_datetime(df["ts"], unit="s", utc=True).dt.quarter
    df["quarter"] = "Q" + q.astype(str)
    # add human title for readability
    df["title"] = df["book_id"].map(lambda bid: BOOK_DB.get(bid, {}).get("title", bid))
    return df

def _summary_quarter_overall(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["year","quarter","books_read"])
    s = df.groupby(["year","quarter"], as_index=False).size().rename(columns={"size":"books_read"})
    s = s.sort_values(["year","quarter"])
    return s

def _summary_quarter_by_grade(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["year","quarter","grade","books_read"])
    s = df.groupby(["year","quarter","grade"], as_index=False).size().rename(columns={"size":"books_read"})
    s = s.sort_values(["year","quarter","grade"])
    return s

def _summary_year_overall(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["year","books_read"])
    return df.groupby(["year"], as_index=False).size().rename(columns={"size":"books_read"}).sort_values("year")

def _plot_quarter_overall(dfq: pd.DataFrame):
    fig, ax = plt.subplots(figsize=(6,3.2))
    if dfq.empty:
        ax.text(0.5, 0.5, "No data yet", ha="center", va="center", fontsize=12)
        ax.axis("off")
        return fig
    x_labels = dfq["year"].astype(str) + " " + dfq["quarter"]
    ax.bar(x_labels, dfq["books_read"])
    ax.set_title("Books Read per Quarter (Overall)")
    ax.set_xlabel("Quarter")
    ax.set_ylabel("Books")
    ax.tick_params(axis="x", rotation=45)
    fig.tight_layout()
    return fig

def _plot_quarter_by_grade(dfqg: pd.DataFrame):
    fig, ax = plt.subplots(figsize=(6.5,3.6))
    if dfqg.empty:
        ax.text(0.5, 0.5, "No data yet", ha="center", va="center", fontsize=12)
        ax.axis("off")
        return fig
    dfqg = dfqg.copy()
    dfqg["label"] = dfqg["year"].astype(str) + " " + dfqg["quarter"]
    piv = dfqg.pivot_table(index="label", columns="grade", values="books_read", fill_value=0, aggfunc="sum")
    bottom = None
    for grade in sorted(piv.columns):
        vals = piv[grade].values
        if bottom is None:
            ax.bar(piv.index, vals, label=f"Grade {grade}")
            bottom = vals
        else:
            ax.bar(piv.index, vals, bottom=bottom, label=f"Grade {grade}")
            bottom = bottom + vals
    ax.set_title("Books Read per Quarter by Grade (Stacked)")
    ax.set_xlabel("Quarter")
    ax.set_ylabel("Books")
    ax.tick_params(axis="x", rotation=45)
    ax.legend(ncol=4, fontsize=8)
    fig.tight_layout()
    return fig

# Exporters (return file paths for Gradio File components)
def _export_json(data: dict) -> str:
    fd, path = tempfile.mkstemp(suffix=".json", prefix="metrics_")
    _os.close(fd)
    with open(path, "w", encoding="utf-8") as f:
        _json.dump(data, f, ensure_ascii=False, indent=2)
    return path

def _export_csv(df: pd.DataFrame, name: str = "metrics") -> str:
    fd, path = tempfile.mkstemp(suffix=".csv", prefix=f"{name}_")
    _os.close(fd)
    df.to_csv(path, index=False)
    return path

def compute_metrics():
    df = _events_df()
    quarter_overall = _summary_quarter_overall(df)
    quarter_by_grade = _summary_quarter_by_grade(df)
    year_overall = _summary_year_overall(df)
    fig_q = _plot_quarter_overall(quarter_overall)
    fig_qg = _plot_quarter_by_grade(quarter_by_grade)
    table = quarter_by_grade.copy()
    return fig_q, fig_qg, table, quarter_overall, quarter_by_grade, year_overall

def export_metrics_json():
    _, _, _, qo, qg, yo = compute_metrics()
    blob = {
        "generated_utc": int(time.time()),
        "quarter_overall": qo.to_dict(orient="records"),
        "quarter_by_grade": qg.to_dict(orient="records"),
        "year_overall": yo.to_dict(orient="records"),
    }
    return _export_json(blob)

def export_metrics_csv():
    _, _, _, _, qg, _ = compute_metrics()
    return _export_csv(qg, name="metrics_quarter_by_grade")


def winner_text_for_grade(grade: int) -> str:
    w = LAST_WEEK_WINNERS.get(int(grade))
    if not w:
        return f"No winner recorded yet for Grade {grade}."
    name = w.get("student", "Unknown")
    count = w.get("count", 0)
    book_ids = w.get("books") or []
    titles = [BOOK_DB.get(bid, {}).get("title", bid) for bid in book_ids]
    books_str = ", ".join(titles) if titles else "no listed books"
    return f"🏆 Last week’s winner (Grade {grade}): **{name}** — **{count}** book(s). Titles: _{books_str}_."


def _md_list(items: list[str]) -> str:
    if not items:
        return "- (none)"
    return "\n".join(f"- {x}" for x in items)


def campaign_markdown(campaign: dict) -> str:
    def _fmt_date_iso(s: str | None) -> str:
        if not s:
            return "—"
        # s is already "YYYY-MM-DD"; show a nicer label like 'Sep 20, 2025'
        try:
            y, m, d = s.split("-")
            import calendar
            return f"{calendar.month_abbr[int(m)]} {int(d)}, {y}"
        except Exception:
            # fallback to trying to parse via datetime
            try:
                dobj = datetime.date.fromisoformat(s)
                return dobj.strftime("%b %d, %Y")
            except Exception:
                return s

    title = campaign.get("title") or "Untitled Campaign"
    prize = campaign.get("prize_rules") or "—"
    start = _fmt_date_iso(campaign.get("start_date"))
    end = _fmt_date_iso(campaign.get("end_date"))
    cats = campaign.get("categories") or []
    seeds = campaign.get("seed_list") or []

    # Map seed IDs to detailed labels including Lexile and grade range
    seed_labels = []
    for bid in seeds:
        info = BOOK_DB.get(bid) or {}
        if info:
            t = info.get('title', 'Untitled')
            a = info.get('author', 'Unknown')
            lex = info.get('lexile', '—')
            grs = _grade_range_str(info.get('grade_range'))
            seed_labels.append(f"{t} — {a} (Lexile {lex}; {grs})")
        else:
            seed_labels.append(bid)

    return (
        f"### {title}\n\n"
        f"**Prize rules:** {prize}\n\n"
        f"**Dates:** {start} → {end}\n\n"
        f"**Categories:**\n{_md_list(cats)}\n\n"
        f"**Featured (seeds):**\n{_md_list(seed_labels)}"
    )


def campaign_spotlight_markdown(campaign: dict) -> str:
    title = campaign.get("title") or "Reading Week Spotlight"
    seeds = campaign.get("seed_list") or []
    if not seeds:
        return f"### {title}\n\n_No featured books selected yet._"

    lines = []
    for bid in seeds:
        info = BOOK_DB.get(bid, {})
        t = info.get("title", bid)
        a = info.get("author", "Unknown")
        cat = info.get("category", "other")
        lex = info.get("lexile", "—")
        grs = _grade_range_str(info.get("grade_range"))
        lines.append(f"- *{t}* — {a}  •  `{cat}`  •  **Lexile {lex}**  •  {grs}")

    return f"### {title}\n\n" + "\n".join(lines)


def winner_markdown_for_grade(grade: int) -> str:
    w = LAST_WEEK_WINNERS.get(int(grade))
    if not w:
        return f"**Winner (Grade {grade})**\n\n- No winner recorded yet."
    name = w.get("student", "Unknown")
    count = w.get("count", 0)
    book_ids = w.get("books") or []
    titles = [BOOK_DB.get(bid, {}).get("title", bid) for bid in book_ids]
    titles_md = _md_list(titles)
    return (
        f"**Winner (Grade {grade})**\n\n"
        f"- **Student:** {name}\n"
        f"- **Books read:** {count}\n"
        f"- **Titles:**\n{titles_md}"
    )

# ---------- Student UI callbacks ----------
def ui_student_get_overview(grade: int):
    cats = top_categories_for_grade(grade, 5)
    cats_table = [[c, n] for c, n in cats] or [["(no data)", 0]]
    winner_text = winner_text_for_grade(grade)
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

    table = []
    for name, count, books in top5:
        titles = [BOOK_DB.get(bid, {}).get("title", bid) for bid in books]
        table.append([name, count, ", ".join(titles)])
    table = table or [["(no data)", 0, ""]]
    return f"Logged '{BOOK_DB[book_id]['title']}' for {student_name}!", table


def ui_librarian_leaderboard(grade: int):
    top5 = top_readers_by_grade(grade, 5)
    table = []
    for name, count, books in top5:
        titles = [BOOK_DB.get(bid, {}).get("title", bid) for bid in books]
        table.append([name, count, ", ".join(titles)])
    return table or [["(no data)", 0, ""]]

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


# (Reload helper removed)

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

        # ---- How to use (Student) AT TOP ----
        with gr.Accordion("How to use (Student)", open=False):
            gr.Markdown(
                "- Set your **grade** to see the weekly winner and top readers.\n"
                "- **Log a finished book**: submit your name, pick the book, and write 2–3 sentences for a mini-quiz.\n"
                "  Your book will show as **pending** until the librarian approves it. Only approved books count for prizes.\n"
                "- **Digital checkout**: if your school uses digital books, your checkout can auto-create a pending entry; "
                "a physical checkout (with barcode scan) can also earn extra prizes.\n"
                "- **Lexile (reading level)**: a number that estimates difficulty (lower = easier, higher = more challenging). "
                "Aim near your level, and stretch a bit for growth.\n"
                "- **Key terms**: *Pending* = awaiting quiz or approval; *Approved* = counts on the board; *Rejected* = did not meet requirements.\n"
                "- **Be safe**: don’t share personal info (emails/phone numbers), usernames, or links."
            )

        # ---- Grade + Refresh ----
        with gr.Row():
            s_grade = gr.Slider(1, 12, value=5, step=1, label="Your Grade")
            refresh_btn = gr.Button("Refresh")

        # Winner just under grade
        s_winner = gr.Markdown()

        # Recommended books (from librarian seeds) for this grade
        gr.Markdown("#### Librarian Recommended Books")
        s_recs = gr.Markdown()

        # ---- Log a finished book (now above 'Learn more') ----
        gr.Markdown("#### Log a finished book (counts toward weekly prize)")

        with gr.Row():
            s_name = gr.Textbox(label="Your Name", placeholder="First name & last initial (e.g., Sam T.)")
            s_book_log = gr.Dropdown(choices=BOOK_CHOICES(), value=FIRST_BOOK_ID_DEFAULT(), label="Book")
        with gr.Row():
            s_quiz = gr.Textbox(label="Mini-quiz (2–3 sentences about the book)", placeholder="Tell us something about the plot or a character you liked.", lines=3)
            log_btn = gr.Button("Submit for approval")

        # Log Status immediately beneath the log row (includes user, title, Lexile)
        s_log_msg = gr.Markdown()

        # Top 5 Readers (beneath winner & logging)
        s_leader = gr.Dataframe(
            headers=["Student", "Count", "Books"],
            row_count=5,
            interactive=False,
            label="Top 5 Readers (your grade)"
        )

        # Helper to refresh winner + leaderboard together
        def _student_overview(grade: int):
            win_text = winner_text_for_grade(grade)
            top5 = top_readers_by_grade(grade, 5)
            rows = []
            for name, count, books in top5:
                titles = [BOOK_DB.get(bid, {}).get("title", bid) for bid in books]
                rows.append([name, count, ", ".join(titles)])
            if not rows:
                rows = [["(no data)", 0, ""]]
            return win_text, rows

        def _student_recommended(grade: int):
            return render_recommended_for_grade(int(grade))

        refresh_btn.click(lambda g: (_student_overview(g)[0], _student_overview(g)[1], _student_recommended(g)),
                inputs=[s_grade], outputs=[s_winner, s_leader, s_recs])
        s_grade.release(lambda g: (_student_overview(g)[0], _student_overview(g)[1], _student_recommended(g)),
                inputs=[s_grade], outputs=[s_winner, s_leader, s_recs])

        # New: mini-quiz evaluation and submit-for-approval flow (creates pending log only)
        def _evaluate_quiz_answer(answer: str) -> bool:
            # Extremely simple heuristic: length >= ~40 chars (~2–3 short sentences)
            txt = (answer or "").strip()
            return len(txt) >= 40

        def _log_submit_for_approval(grade: int, student_name: str, book_id: str, quiz_answer: str):
            who = (student_name or "").strip()
            if not who:
                return "⚠️ Please enter your name.", "", []

            if book_id not in BOOK_DB:
                return f"⚠️ Unknown book id: {book_id}", "", []

            info = BOOK_DB.get(book_id, {})
            title = info.get("title", book_id)
            lex = info.get("lexile", "—")

            passed = _evaluate_quiz_answer(quiz_answer)
            add_pending_log(grade, who, book_id, quiz_passed=passed, quiz_answer=quiz_answer)

            status_note = "passed mini-quiz" if passed else "needs librarian to review mini-quiz"
            status = (
                f"✅ **{who}** submitted *{title}* (Lexile **{lex}**). "
                "Your entry is now in the approval queue and will appear on the board once approved."
            )

            # DO NOT update leaderboard here (only approved count).
            win_text, rows = _student_overview(grade)
            return status, win_text, rows

        log_btn.click(
            _log_submit_for_approval,
            inputs=[s_grade, s_name, s_book_log, s_quiz],
            outputs=[s_log_msg, s_winner, s_leader]
        )

        # ---- Learn more about a book (safe chat) — moved below logging ----
        # ---- Book Request accordion (student-facing) ----
        with gr.Accordion("Book Request", open=False):
            gr.Markdown(
                "**Ask your librarian to get a book for you.**\n"
                "- Pick a book (Lexile & category auto-fill), choose a date you need it by, and add any special request.\n"
                "- Your request will show as **pending** until the librarian approves or rejects it.\n"
                "- If approved, you’ll see a date when the book will be available."
            )
            with gr.Row():
                r_name = gr.Textbox(label="Your Name", placeholder="First name & last initial (e.g., Sam T.)")
                r_grade = s_grade  # reuse the main grade slider
            with gr.Row():
                r_book = gr.Dropdown(choices=_book_label_choices(), label="Book", allow_custom_value=False)
                r_lexi = gr.Number(label="Lexile", precision=0)
                r_cat  = gr.Dropdown(
                    choices=sorted({b.get("category", "other") for b in BOOK_DB.values()} | set(CAMPAIGN.get("categories", []))),
                    label="Category"
                )
            with gr.Row():
                r_date = gr.Textbox(label="Date Needed By (YYYY-MM-DD)", placeholder="YYYY-MM-DD")
                r_special = gr.Textbox(label="Special Request", placeholder="Format, edition, accessibility, etc.", lines=2)

            with gr.Row():
                r_submit = gr.Button("Submit Request")
                r_clear  = gr.Button("Clear Form")

            r_status = gr.Markdown()
            r_mine   = gr.Dataframe(
                headers=["Submitted (UTC)","Title","Lexile","Category","Needed By","Status","Available Date"],
                interactive=False,
                label="My Requests"
            )

        # Wire student-side behavior
        r_book.change(_prefill_request_fields, inputs=[r_book], outputs=[r_lexi, r_cat])

        def _submit_book_request(grade, name, book_id, lexile, category, date_needed, special):
            name = (name or "").strip()
            if not name:
                return "⚠️ Please enter your name.", _student_requests_table(grade, name)
            # accept chosen book or blank
            info = BOOK_DB.get(book_id or "", {})
            title = info.get("title", "(unspecified)") if book_id else "(unspecified)"
            lex = int(lexile) if isinstance(lexile, (int, float)) else (info.get("lexile", None) if info else None)
            cat = (category or info.get("category") or "other")
            need = _validate_iso_date_or_none(date_needed)

            BOOK_REQUESTS.append({
                "id": f"req_{uuid.uuid4().hex[:8]}",
                "ts": int(time.time()),
                "grade": int(grade),
                "student": name,
                "book_id": book_id or "",
                "title": title,
                "lexile": lex,
                "category": cat,
                "date_needed": need,         # student’s requested date
                "special": (special or "").strip(),
                "status": "pending",         # <-- new
                "availability_date": None,   # <-- set by librarian on approval
            })

            status = f"✅ Request submitted by **{name}** for *{title}* (Lexile **{lex if lex is not None else '—'}**, `{cat}`), needed by **{need or '—'}** — **pending**."
            return status, _student_requests_table(grade, name)

        def _clear_request_form():
            return (gr.update(value=""), gr.update(value=None), gr.update(value=None),
                    gr.update(value=None), gr.update(value=""), gr.update(value=""))

        r_submit.click(
            _submit_book_request,
            inputs=[r_grade, r_name, r_book, r_lexi, r_cat, r_date, r_special],
            outputs=[r_status, r_mine]
        )
        r_clear.click(
            _clear_request_form,
            inputs=[],
            outputs=[r_name, r_book, r_lexi, r_cat, r_date, r_special]
        )
        r_name.change(lambda g, n: _student_requests_table(g, n), inputs=[r_grade, r_name], outputs=[r_mine])
        r_grade.release(lambda g, n: _student_requests_table(g, n), inputs=[r_grade, r_name], outputs=[r_mine])

        # ---- Learn more about a book (safe chat) — moved below logging ----
        gr.Markdown("#### Learn more about a book")
        with gr.Row():
            s_book = gr.Dropdown(choices=BOOK_CHOICES(), value=FIRST_BOOK_ID_DEFAULT(), label="Book")
            s_q = gr.Textbox(label="Your question", placeholder="e.g., What is the main theme? Is this age-appropriate for grade 5?", lines=2)

        s_book_info = gr.Markdown()
        def _student_book_info(bid: str):
            info = BOOK_DB.get(bid) or {}
            title = info.get("title", "Untitled")
            author = info.get("author", "Unknown")
            cat = info.get("category", "other")
            lx = info.get("lexile", "—")
            return f"**Selected:** *{title}* — {author}  •  Category: `{cat}`  •  Lexile: `{lx}`"
        s_book.change(_student_book_info, inputs=[s_book], outputs=[s_book_info])

        s_ask = gr.Button("Ask")
        s_answer = gr.Textbox(label="Answer", lines=6)
        s_ask.click(ui_student_learn_book, inputs=[s_book, s_q], outputs=[s_answer])
        s_q.submit(ui_student_learn_book, inputs=[s_book, s_q], outputs=[s_answer])

        with gr.Accordion("My submissions", open=False):
            my_name = gr.Textbox(label="Your Name")
            my_refresh = gr.Button("Refresh")
            my_table = gr.Dataframe(headers=["ID","Title","Lexile","Status","Submitted (UTC)"], interactive=False)

            def _my_submissions(grade: int, name: str):
                name = (name or "").strip()
                rows = []
                # Pending
                for it in PENDING_LOGS.get(int(grade), []):
                    if it["student"] == name:
                        info = BOOK_DB.get(it["book_id"], {})
                        rows.append([it["id"], info.get("title", it["book_id"]), info.get("lexile","—"),
                                     it.get("status","pending"), time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(it.get("ts",0)))])
                # Approved (in READ_LOGS)
                for s_name, data in READ_LOGS.get(int(grade), {}).items():
                    if s_name == name:
                        for bid in data.get("books", []):
                            info = BOOK_DB.get(bid, {})
                            rows.append(["(approved)", info.get("title", bid), info.get("lexile","—"),
                                         "approved", "—"])
                if not rows:
                    rows = [["(none)","","","",""]]
                return rows

            my_refresh.click(_my_submissions, inputs=[s_grade, my_name], outputs=[my_table])

    with gr.Tab("Librarian"):
        gr.Markdown("### Librarian Console")

        with gr.Accordion("How to use (Librarian)", open=False):
            gr.Markdown(
                "- **Approvals Queue**: review students’ pending submissions. You may approve (counts toward prizes) or reject.\n"
                "- **Campaign Setup**: set title, prize rules, dates, featured books.\n"
                "- **Leaderboards & Winners**: leaders reflect **approved** books only. Use **Pick Weekly Winner** when ready.\n"
                "- **Reading Insights**: top categories and **average Lexile by category** (approved books only).\n"
                "- **Lexile**: numeric reading difficulty (lower = easier, higher = advanced). Use averages to gauge appropriateness and growth.\n"
                "- **Key terms**: *Pending* = awaiting quiz/approval; *Approved* = counted; *Rejected* = not counted.\n"
                "- **Research Assistant**: router-aware (vector/web/LLM); enable web routing for recency; cite snippets.\n"
                "- **Agentic RAG**: upload txt/md/csv/json/docx/pdf; chunk to Qdrant for retrieval."
            )

        with gr.Accordion("Campaign Setup", open=True):
            l_title = gr.Textbox(label="Campaign Title", value=CAMPAIGN["title"])
            l_prize = gr.Textbox(label="Prize Rules", value=CAMPAIGN["prize_rules"])

            l_categories = gr.CheckboxGroup(
                choices=list({*CAMPAIGN["categories"], *[b.get("category", "other") for b in BOOK_DB.values()]}),
                value=CAMPAIGN["categories"],
                label="Categories"
            )

            with gr.Row():
                # Use plain textboxes to accept YYYY-MM-DD strings for broader compatibility
                l_start = gr.Textbox(label="Start Date (YYYY-MM-DD)", value=CAMPAIGN.get("start_date") or "")
                l_end = gr.Textbox(label="End Date (YYYY-MM-DD)",   value=CAMPAIGN.get("end_date") or "")

            # --- Featured Seed Books accordion (stays above campaign details) ---
            with gr.Accordion("Featured Seed Books", open=True):
                l_seed = gr.CheckboxGroup(
                    choices=SEED_BOOK_CHOICES(),
                    value=CAMPAIGN.get("seed_list", []),
                    label="Pick spotlight titles (Title — Author • Lexile • Grade Range)"
                )

            apply_btn = gr.Button("Apply Campaign Settings")

            # --- NEW: Campaign Details accordion (moved under Featured Seeds + Spotlight) ---
            with gr.Accordion("Campaign Details", open=False):
                # this now lives *below* the featured seeds accordion
                l_campaign_md = gr.Markdown(value=campaign_markdown(CAMPAIGN))

            # (Reload Books UI removed)
            from datetime import datetime

            def _validate_iso_date(s: str) -> str | None:
                if not s:
                    return None
                try:
                    # ensure format YYYY-MM-DD
                    datetime.strptime(s, "%Y-%m-%d")
                    return s
                except ValueError:
                    raise gr.Error(f"Invalid date: {s!r}. Use YYYY-MM-DD.")

            def _ui_librarian_set_campaign(title, prize_rules, categories, start_date, end_date, seed_list):
                start_iso = _validate_iso_date((start_date or "").strip())
                end_iso = _validate_iso_date((end_date or "").strip())

                if start_iso and end_iso and end_iso < start_iso:
                    raise gr.Error(f"End Date ({end_iso}) cannot be earlier than Start Date ({start_iso}).")

                CAMPAIGN.update({
                    "title": title or CAMPAIGN["title"],
                    "prize_rules": prize_rules or CAMPAIGN["prize_rules"],
                    "categories": categories or CAMPAIGN["categories"],
                    "start_date": start_iso,
                    "end_date": end_iso,
                    "seed_list": seed_list or [],
                })
                return campaign_markdown(CAMPAIGN)

            # When campaign is applied, refresh both the campaign card and the Spotlight panel
            apply_btn.click(
                _ui_librarian_set_campaign,
                inputs=[l_title, l_prize, l_categories, l_start, l_end, l_seed],
                outputs=[l_campaign_md],
            )

        # (Spotlight display moved into Campaign Setup above)

        with gr.Accordion("Leaderboards & Winners", open=True):
            l_grade = gr.Slider(1, 12, value=5, step=1, label="Grade")
            l_refresh = gr.Button("Refresh Leaderboard")
            l_table = gr.Dataframe(headers=["Student", "Count", "Books"], row_count=5, interactive=False)
            l_refresh.click(ui_librarian_leaderboard, inputs=[l_grade], outputs=[l_table])

            pick_btn = gr.Button("Pick Weekly Winner (by grade)")
            l_winner = gr.Markdown()
            def _ui_librarian_pick_winner(grade: int):
                top5 = top_readers_by_grade(grade, 1)
                if not top5:
                    return f"**Winner (Grade {grade})**\n\n- No readers yet."
                name, count, books = top5[0]
                LAST_WEEK_WINNERS[grade] = {"student": name, "count": count, "books": books}
                return winner_markdown_for_grade(grade)
            pick_btn.click(_ui_librarian_pick_winner, inputs=[l_grade], outputs=[l_winner])

        with gr.Accordion("Metrics & Exports", open=False):
            gr.Markdown(
                "Track **approved** books over time. These charts use timestamps when librarians approve student submissions.\n"
                "- **Quarterly overall** shows total approved books per quarter.\n"
                "- **Quarterly by grade** stacks grade totals per quarter.\n"
                "- Export summaries as **JSON** or **CSV**."
            )
            m_refresh = gr.Button("Compute / Refresh Metrics")

            with gr.Row():
                m_plot_q = gr.Plot(label="Books per Quarter (Overall)")
                m_plot_qg = gr.Plot(label="Books per Quarter by Grade (Stacked)")

            m_table = gr.Dataframe(
                headers=["year","quarter","grade","books_read"],
                interactive=False,
                label="Quarterly by Grade (table)"
            )

            with gr.Row():
                m_exp_json = gr.Button("Export JSON")
                m_exp_csv = gr.Button("Export CSV")

            m_json_file = gr.File(label="Download JSON")
            m_csv_file = gr.File(label="Download CSV")

            def _ui_compute_metrics():
                fig_q, fig_qg, table, *_ = compute_metrics()
                return fig_q, fig_qg, table

            m_refresh.click(_ui_compute_metrics, inputs=[], outputs=[m_plot_q, m_plot_qg, m_table])

            m_exp_json.click(lambda: export_metrics_json(), inputs=[], outputs=[m_json_file])
            m_exp_csv.click(lambda: export_metrics_csv(), inputs=[], outputs=[m_csv_file])

        with gr.Accordion("Reading Insights by Grade", open=False):
            li_grade = gr.Slider(1, 12, value=5, step=1, label="Grade")

            li_refresh = gr.Button("Refresh Insights")

            li_topcats = gr.Dataframe(
                headers=["Category", "Count"],
                row_count=5,
                interactive=False,
                label="Top 5 Categories (this grade)"
            )

            li_lex = gr.Dataframe(
                headers=["Category", "Count (with Lexile)", "Average Lexile"],
                row_count=5,
                interactive=False,
                label="Average Lexile by Category (based on books read)"
            )

            def _insights_for_grade(grade: int):
                # top categories
                cats = top_categories_for_grade(int(grade), 5)
                topcats = [[c, n] for c, n in cats] or [["(no data)", 0]]

                # average lexile
                lex_rows = avg_lexile_by_category_for_grade(int(grade))
                if not lex_rows:
                    lex_rows = [["(no data)", 0, None]]

                return topcats, lex_rows

            li_refresh.click(_insights_for_grade, inputs=[li_grade], outputs=[li_topcats, li_lex])
            li_grade.release(_insights_for_grade, inputs=[li_grade], outputs=[li_topcats, li_lex])

            with gr.Accordion("Approvals Queue", open=True):
                a_grade = gr.Slider(1, 12, value=5, step=1, label="Grade")
                a_refresh = gr.Button("Refresh queue")

                # Table for quick scan + multi-select for bulk actions
                a_table = gr.Dataframe(headers=["ID", "Student", "Title", "Lexile", "Status", "Submitted (UTC)"], interactive=False)
                a_select = gr.CheckboxGroup(label="Select items to approve/reject")

                # NEW: detail viewers
                a_detail = gr.Dropdown(label="View details for one item", choices=[], value=None)
                a_quiz_md = gr.Markdown(label="Quiz Answer")

                def _list_pending_for_grade(grade: int):
                    items = PENDING_LOGS.get(int(grade), [])
                    rows, options, detail_opts = [], [], []
                    for it in items:
                        info = BOOK_DB.get(it["book_id"], {})
                        title = info.get("title", it["book_id"])
                        lex = info.get("lexile", "—")
                        ts = it.get("ts", 0)
                        rows.append([it["id"], it["student"], title, lex, it.get("status"), time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ts))])
                        options.append(pending_label(it))
                        detail_opts.append(it["id"])
                    if not rows:
                        rows = [["(none)", "", "", "", "", ""]]
                    return (
                        rows,
                        gr.update(choices=options, value=[]),
                        gr.update(choices=detail_opts, value=(detail_opts[0] if detail_opts else None)),
                        _render_quiz_md(int(grade), detail_opts[0] if detail_opts else None),
                    )

                def _render_quiz_md(grade: int, req_id: str | None) -> str:
                    if not req_id:
                        return "_No item selected._"
                    for it in PENDING_LOGS.get(int(grade), []):
                        if it["id"] == req_id:
                            info = BOOK_DB.get(it["book_id"], {})
                            title = info.get("title", it["book_id"])
                            lex = info.get("lexile", "—")
                            return (
                                f"**Submission:** `{it['id']}`\n\n"
                                f"- **Student:** {it['student']}\n"
                                f"- **Book:** *{title}*  •  Lexile **{lex}**\n"
                                f"- **Status:** {it['status']}  •  **Quiz passed:** {bool(it.get('quiz_passed'))}\n\n"
                                f"**Quiz answer:**\n\n> {it.get('quiz_answer','(none)') or '(none)'}"
                            )
                    return "_Not found._"

                a_refresh.click(_list_pending_for_grade, inputs=[a_grade], outputs=[a_table, a_select, a_detail, a_quiz_md])
                a_grade.release(_list_pending_for_grade, inputs=[a_grade], outputs=[a_table, a_select, a_detail, a_quiz_md])

                # Update quiz preview when a different item is selected
                a_detail.change(lambda g, i: _render_quiz_md(int(g), i), inputs=[a_grade, a_detail], outputs=[a_quiz_md])

                with gr.Row():
                    a_approve = gr.Button("Approve selected")
                    a_reject  = gr.Button("Reject selected")

                a_status = gr.Markdown()

                def _extract_ids_from_labels(labels: List[str]) -> List[str]:
                    # labels look like "req_ab12cd34 — Student — Title (Lexile 820) — pending_approval"
                    ids = []
                    for lab in (labels or []):
                        part = (lab or "").split(" — ", 1)[0]
                        if part.startswith("req_"):
                            ids.append(part)
                    return ids

                def _approve_selected(grade: int, labels: List[str]):
                    ids = set(_extract_ids_from_labels(labels))
                    if not ids:
                        table, opts, det, quiz = _list_pending_for_grade(grade)
                        student_win, student_rows = _student_overview(grade)
                        return ("⚠️ No items selected.", table, opts, det, quiz, student_win, student_rows)

                    kept = []
                    approved = 0
                    for it in PENDING_LOGS.get(int(grade), []):
                        if it["id"] in ids:
                            # approve regardless of quiz_passed (librarian override allowed)
                            record_reading(grade, it["student"], it["book_id"])
                            approved += 1
                        else:
                            kept.append(it)
                    PENDING_LOGS[int(grade)] = kept

                    msg = f"✅ Approved {approved} item(s)."
                    table, opts, det, quiz = _list_pending_for_grade(grade)
                    student_win, student_rows = _student_overview(grade)
                    # NEW: clear student status line so student sees fresh state
                    student_status = ""
                    return (msg, table, opts, det, quiz, student_win, student_rows, student_status)

                def _reject_selected(grade: int, labels: List[str]):
                    ids = set(_extract_ids_from_labels(labels))
                    if not ids:
                        table, opts, det, quiz = _list_pending_for_grade(grade)
                        student_win, student_rows = _student_overview(grade)
                        return ("⚠️ No items selected.", table, opts, det, quiz, student_win, student_rows)

                    kept = []
                    rejected = 0
                    for it in PENDING_LOGS.get(int(grade), []):
                        if it["id"] in ids:
                            rejected += 1
                        else:
                            kept.append(it)
                    PENDING_LOGS[int(grade)] = kept

                    msg = f"🗑️ Rejected {rejected} item(s)."
                    table, opts, det, quiz = _list_pending_for_grade(grade)
                    student_win, student_rows = _student_overview(grade)
                    # NEW: clear student status line so student sees fresh state
                    student_status = ""
                    return (msg, table, opts, det, quiz, student_win, student_rows, student_status)

                a_approve.click(_approve_selected, inputs=[a_grade, a_select], outputs=[a_status, a_table, a_select, a_detail, a_quiz_md, s_winner, s_leader, s_log_msg])
                a_reject.click(_reject_selected, inputs=[a_grade, a_select], outputs=[a_status, a_table, a_select, a_detail, a_quiz_md, s_winner, s_leader, s_log_msg])

            # ---- Book Requests Queue (Librarian) ----
            with gr.Accordion("Book Requests Queue", open=False):
                br_show_all = gr.Checkbox(label="Show all (not just pending)", value=False)
                br_refresh  = gr.Button("Refresh")

                br_table = gr.Dataframe(
                    headers=[
                        "ID","Submitted (UTC)","Grade","Student","Title","Lexile","Category",
                        "Needed By","Status","Available Date"
                    ],
                    interactive=False,
                    label="Requests"
                )
                br_select = gr.CheckboxGroup(label="Select requests")

                # Detail + action
                br_detail = gr.Dropdown(label="View details for one item", choices=[], value=None)
                br_avail  = gr.Textbox(label="Availability Date to Student (YYYY-MM-DD)", placeholder="YYYY-MM-DD")
                br_msg    = gr.Markdown()

                with gr.Row():
                    br_approve = gr.Button("Approve selected")
                    br_reject  = gr.Button("Reject selected (no availability date)")

                # Populate table & selectors
                def _br_list(show_all: bool):
                    rows = _librarian_requests_table(only_pending=not show_all)
                    # build selector labels like "req_1234 — Student — Title"
                    labels = []
                    ids = []
                    for r in BOOK_REQUESTS:
                        if not show_all and r["status"] != "pending":
                            continue
                        labels.append(f"{r['id']} — {r['student']} — {r['title']}")
                        ids.append(r["id"])
                    detail_ids = ids[:]
                    if not rows:
                        rows = [["(none)", "", "", "", "", "", "", "", "", ""]]
                    return (
                        rows,
                        gr.update(choices=labels, value=[]),
                        gr.update(choices=detail_ids, value=(detail_ids[0] if detail_ids else None)),
                        "_Select a single request to preview its details here._"
                    )

                br_refresh.click(_br_list, inputs=[br_show_all], outputs=[br_table, br_select, br_detail, br_msg])
                br_show_all.change(_br_list, inputs=[br_show_all], outputs=[br_table, br_select, br_detail, br_msg])

                def _br_detail_render(req_id: str | None):
                    if not req_id:
                        return "_No item selected._"
                    r = _find_request_by_id(req_id)
                    if not r:
                        return "_Not found._"
                    return (
                        f"**{r['id']}**\n\n"
                        f"- **Student:** {r['student']} (Grade {r['grade']})\n"
                        f"- **Title:** *{r['title']}*  •  Lexile **{r['lexile'] if r['lexile'] is not None else '—'}**  •  `{r['category'] or '—'}`\n"
                        f"- **Needed by:** {r['date_needed'] or '—'}\n"
                        f"- **Status:** {r['status']}  •  **Available date:** {r.get('availability_date') or '—'}\n"
                        f"- **Special request:** {r.get('special') or '(none)'}"
                    )

                br_detail.change(_br_detail_render, inputs=[br_detail], outputs=[br_msg])

                # Approve/Reject helpers
                def _ids_from_labels(labels: list[str]) -> list[str]:
                    out = []
                    for lab in (labels or []):
                        rid = lab.split(" — ", 1)[0]
                        if rid.startswith("req_"):
                            out.append(rid)
                    return out

                def _approve_requests(labels: list[str], availability_iso: str, s_grade_val, s_name_val):
                    ids = _ids_from_labels(labels)
                    if not ids:
                        rows, sel, det, msg = _br_list(False)
                        # also refresh student "My Requests"
                        return ("⚠️ No items selected.",
                                rows, sel, det, msg,
                                _student_requests_table(int(s_grade_val), s_name_val))
                    avail = _validate_iso_date_or_none(availability_iso)
                    if not avail:
                        raise gr.Error("Please enter Availability Date (YYYY-MM-DD) to approve.")

                    count = 0
                    for rid in ids:
                        r = _find_request_by_id(rid)
                        if r and r["status"] == "pending":
                            r["status"] = "approved"
                            r["availability_date"] = avail
                            count += 1

                    rows, sel, det, msg = _br_list(False)
                    return (f"✅ Approved {count} request(s); availability date set to **{avail}**.",
                            rows, sel, det, msg,
                            _student_requests_table(int(s_grade_val), s_name_val))

                def _reject_requests(labels: list[str], s_grade_val, s_name_val):
                    ids = _ids_from_labels(labels)
                    if not ids:
                        rows, sel, det, msg = _br_list(False)
                        return ("⚠️ No items selected.",
                                rows, sel, det, msg,
                                _student_requests_table(int(s_grade_val), s_name_val))
                    count = 0
                    for rid in ids:
                        r = _find_request_by_id(rid)
                        if r and r["status"] == "pending":
                            r["status"] = "rejected"
                            r["availability_date"] = None
                            count += 1
                    rows, sel, det, msg = _br_list(False)
                    return (f"🗑️ Rejected {count} request(s).",
                            rows, sel, det, msg,
                            _student_requests_table(int(s_grade_val), s_name_val))

                # Wire actions — note we also refresh the student's "My Requests" (r_mine)
                br_approve.click(
                    _approve_requests,
                    inputs=[br_select, br_avail, s_grade, r_name],
                    outputs=[br_msg, br_table, br_select, br_detail, br_msg, r_mine]
                )
                br_reject.click(
                    _reject_requests,
                    inputs=[br_select, s_grade, r_name],
                    outputs=[br_msg, br_table, br_select, br_detail, br_msg, r_mine]
                )

        with gr.Accordion("Research Assistant (Prompt)", open=False):
            with gr.Row():
                l_book = gr.Dropdown(choices=BOOK_CHOICES(), value=FIRST_BOOK_ID_DEFAULT(), label="(Optional) Book")
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

            # (Reload Books button removed; dynamic reloads are handled elsewhere)

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