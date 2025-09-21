"""
Minimal Gradio Student + Librarian demo scaffold.
- Keeps Tabs always visible
- Shows a demo sign-in banner (display-only)
- Librarian accordions default to closed (open=False)

This file is intentionally minimal and self-contained so importing it
won't fail due to external dependencies or legacy code left behind.

To run the UI locally for interactive testing, execute:
    python -m app.gradio_main

"""
from __future__ import annotations

import gradio as gr
from typing import Dict, Any
import os
import time
import json
import uuid
from typing import Tuple

# Minimal demo BOOK_DB used by the UI while you wire real data/DB later.
BOOK_DB = globals().get("BOOK_DB", {
    "book1": {"title": "The Little Engine", "author": "A. Author", "lexile": 600, "grade": "K-2", "category": "fiction"},
    "book2": {"title": "Space Adventure", "author": "B. Writer", "lexile": 850, "grade": "4-6", "category": "science"},
    "book3": {"title": "History 101", "author": "C. Historian", "lexile": 950, "grade": "6-8", "category": "history"},
})

# Lightweight stubs for services used in the legacy code. These make the
# module importable in demo mode. Replace with real implementations later.
RAG_CORPUS = globals().get("RAG_CORPUS", {})

def vs_search(q: str, top_k: int = 5):
    # return a tiny stubbed hits list-like object
    class Hit:
        def __init__(self, score=0.0, text=""):
            self.score = score
            self.text = text
    return []

def wants_freshness(q: str) -> bool:
    return False

def is_prompt_safe(q: str) -> Tuple[bool, str]:
    return True, ""

def synthesize_from_hits(q: str, hits: list):
    return ""

LIBRARIAN_SYSTEM_PROMPT = "You are a helpful librarian assistant."

class _LLMStub:
    def completion(self, prompt: str, **kwargs):
        return "(demo LLM answer)"

llm = globals().get("llm", _LLMStub())

def _format_snippets(hits, k=3, char_limit=260):
    return ""

def serpapi_search(q: str, num: int = 3):
    return []

def format_results_bullets(results):
    return ""

def upsert_chunks(chunks: list):
    return 0

# ===== Book request workflow stores (in-memory demo stores) =====
# Keep these in module globals so other functions can reference them safely.
BOOK_REQUESTS = globals().get("BOOK_REQUESTS", {})  # { username: [ {book_id, status, ...}, ...] }
LIBRARIAN_QUEUES = globals().get("LIBRARIAN_QUEUES", {
    "requests": [],   # pending approval items
    "returns":  []    # (if you also use a returns queue elsewhere)
})


def _book_label(book_id: str) -> str:
    info = globals().get("BOOK_DB", {}).get(book_id, {})
    title = info.get("title", book_id)
    author = info.get("author", "Unknown")
    lexile = info.get("lexile", "—")
    grade = info.get("grade", "All grades")
    return f"{title} — {author} • Lexile {lexile} • {grade} ({book_id})"


def _parse_id_from_label(label: str) -> str:
    if not label:
        return ""
    if "(" in label and label.endswith(")"):
        return label[label.rfind("(")+1:-1].strip()
    return label.strip()


def _student_requests(username: str):
    return BOOK_REQUESTS.get(username or "", [])


STUDENT_INSTRUCTIONS_MD = """
### What you can do
- **See your grade’s leaders:** Set **Your Grade** to view the *Top 5 Readers* and last week’s winner.
- **Request a book:** Use **Book Request** to choose a title and provide your need-by date and any special requests. Your request goes to the librarian for approval.
- **Log a finished book:** After a librarian **approves** your request, it will appear in **Log a finished book (from your approved requests)**. Select it and submit when you’ve finished reading.
- **Learn more about a book:** Use **Learn more about a book** to ask safe questions (themes, characters, reading level).

### What happens behind the scenes
1) Your **Book Request** is added to the librarian’s **Pending Book Requests** queue.  
2) The librarian **approves or rejects** the request and can set an **Available On** date and a note.  
3) When approved, your request appears in your **approved requests** list (used to log a finished book).  
4) When you **log a finished book**, it moves to *returned pending* for librarian verification and then updates the **Top 5 Readers** board.

### Lexile® measure (reading level)
- A **Lexile** score estimates text complexity (higher number ⇒ generally more advanced).
- Rough guide:  
    - Grades 4–5: ~ 500–900  
    - Grades 6–8: ~ 800–1100  
    - Grades 9–12: ~ 900–1300  
- Ask a teacher/librarian if a Lexile looks too high/low for you.

### Safety & responsible use
- Keep questions **age-appropriate**; **don’t share personal info** (emails, phone numbers, usernames, links).
- If something looks inaccurate or confusing, ask your librarian to double-check.
- When web sources are used by the librarian tool, they’ll be reviewed before being recommended.

### Tips
- Use **Refresh** buttons where available to update lists (approved requests, my requests).
- If you don’t see your approved title, try **Refresh My Requests** and/or ask the librarian.
"""

LIBRARIAN_INSTRUCTIONS_MD = """
### Daily workflow
1) **Campaign Setup**  
    - Set **Title**, **Prize Rules**, **Dates**, **Categories**, and **Featured Seed Books** (by title/ID with Lexile).  
    - Click **Apply Campaign Settings**.  
    - Featured books surface as **Librarian Recommended** items for students.

2) **Pending Book Requests**  
    - Open the accordion and click **Refresh** to list *pending* requests.  
    - Select a request, set **Available On** (optional), add a **Note** (optional), then **Approve** or **Reject**.  
    - Approved requests flow into the student’s **approved requests** list (enabling **Log a finished book**).

3) **Verify returns & update leaderboards**  
    - When students log finished books, they appear as *returned pending* (if return queue is enabled in your build).  
    - Verify/approve returns to update **Top 5 Readers (by grade)**.  
    - Use **Pick Weekly Winner (by grade)** to finalize winners.

4) **Research Assistant (Prompt)**  
    - Ask for summaries, themes, or level guidance.  
    - Toggle **Allow web routing** to pull SerpAPI snippets for time-sensitive facts (results are synthesized and should be verified if critical).

5) **Agentic RAG — Upload Sources**  
    - Upload `.txt/.md/.csv/.json` content (district lists, reading guides, publisher notes).  
    - Click **Ingest to RAG (demo)** to chunk, embed (BGE), and index in **Qdrant** for better grounded answers.

6) **Admin — Vector Store Stats / Metrics**  
    - **Vector Store Stats**: check collection size, embedding model/dim, and health.  
    - **Metrics / Analytics**: generate grade/quarter/year rollups for total books read; export **JSON/CSV** for reporting.

### Lexile® measure (reading level)
- **Lexile** ≈ text complexity; use it to guide grade-appropriate recommendations.  
- Typical bands (approximate):  
  - Grades 4–5: ~ 500–900  
  - Grades 6–8: ~ 800–1100  
  - Grades 9–12: ~ 900–1300

### Safety & moderation
- Student prompts are filtered for PII (emails, phone numbers, links) and NSFW terms.  
- For web-sourced info, keep answers **concise and cautious**; invite students to verify sources and/or consult you.

### Troubleshooting
- If **web search** returns no results, verify `SERPAPI_KEY` in `.env`.  
- If RAG uploads are skipped, ensure file type is `.txt/.md/.csv/.json`.  
- If **Local LLM** isn’t responding, confirm Hermes-3 server is running (e.g., `./scripts/run_hermes3.sh`).
"""


# ===== Student-side handlers =====
def submit_book_request(user: str, book_choice: str, date_needed: str, special: str):
    user = (user or "").strip()
    if not user:
        return "Please enter your name.", [], []
    book_id = _parse_id_from_label(book_choice)
    if not book_id or book_id not in BOOK_DB:
        return "Please select a valid book.", [], []
    req = {
        "user": user,
        "book_id": book_id,
        "status": "pending",
        "requested_at": __import__("time").time(),
        "date_needed": (date_needed or "").strip(),
        "special": (special or "").strip(),
        "available_on": None,
        "librarian_note": ""
    }
    BOOK_REQUESTS.setdefault(user, []).append(req)
    LIBRARIAN_QUEUES.setdefault("requests", []).append({
        "user": user,
        "book_id": book_id,
        "label": _book_label(book_id),
        "date_needed": req["date_needed"],
        "special": req["special"],
        "status": "pending",
        "submitted_at": req["requested_at"]
    })
    return f"Request submitted for **{_book_label(book_id)}**. Status: pending.", *refresh_my_requests(user)

def refresh_my_requests(user: str):
    rows = []
    for r in _student_requests(user):
        info = BOOK_DB.get(r["book_id"], {})
        rows.append([
            info.get("title", r["book_id"]),
            r.get("status", ""),
            r.get("available_on", "") or "—",
            r.get("librarian_note", "") or "—"
        ])
    # Build the choices of approved requests (for your “Log a finished book” flow)
    approved_choices = [
        _book_label(r["book_id"]) for r in _student_requests(user) if r.get("status") == "approved"
    ]
    return rows, approved_choices


# ===== Librarian-side handlers =====
def librarian_list_pending():
    # dropdown of pending request labels with embedded user
    pending = [
        f"{it['label']}  —  requested by {it['user']}  (need-by: {it.get('date_needed') or '—'})"
        for it in LIBRARIAN_QUEUES.get("requests", []) if it.get("status") == "pending"
    ]
    return pending or []

def librarian_approve(selected_label: str, available_on: str, note: str):
    if not selected_label:
        return "Select a pending request first.", [], []
    # locate item
    q = LIBRARIAN_QUEUES.get("requests", [])
    target = None
    idx = -1
    for i, it in enumerate(q):
        tag = f"{it['label']}  —  requested by {it['user']}  (need-by: {it.get('date_needed') or '—'})"
        if tag == selected_label and it.get("status") == "pending":
            target, idx = it, i
            break
    if target is None:
        return "Could not find that pending request (maybe already handled).", librarian_list_pending(), []

    # update student record
    user = target["user"]
    book_id = target["book_id"]
    # find matching student request by book_id still pending
    updated = False
    for r in _student_requests(user):
        if r["book_id"] == book_id and r["status"] == "pending":
            r["status"] = "approved"
            r["available_on"] = (available_on or "").strip()
            r["librarian_note"] = (note or "").strip()
            updated = True
            break

    # update queue
    q[idx]["status"] = "approved"
    q[idx]["available_on"] = (available_on or "").strip()
    q[idx]["note"] = (note or "").strip()

    msg = f"Approved: **{_book_label(book_id)}** for **{user}**. Available on: {available_on or '—'}."
    return msg, librarian_list_pending(), refresh_my_requests(user)[0]

def librarian_reject(selected_label: str, note: str):
    if not selected_label:
        return "Select a pending request first.", [], []
    q = LIBRARIAN_QUEUES.get("requests", [])
    target = None
    idx = -1
    for i, it in enumerate(q):
        tag = f"{it['label']}  —  requested by {it['user']}  (need-by: {it.get('date_needed') or '—'})"
        if tag == selected_label and it.get("status") == "pending":
            target, idx = it, i
            break
    if target is None:
        return "Could not find that pending request (maybe already handled).", librarian_list_pending(), []

    # update student record
    user = target["user"]
    book_id = target["book_id"]
    for r in _student_requests(user):
        if r["book_id"] == book_id and r["status"] == "pending":
            r["status"] = "rejected"
            r["librarian_note"] = (note or "").strip()
            break

    # update queue
    q[idx]["status"] = "rejected"
    q[idx]["note"] = (note or "").strip()

    msg = f"Rejected: **{_book_label(book_id)}** for **{user}**. Note sent."
    return msg, librarian_list_pending(), refresh_my_requests(user)[0]


def build_student_ui() -> Dict[str, Any]:
    """Return component references for the Student tab.

    This builder constructs the components but does not attach them to events
    (wiring happens when the Blocks are built). It's safe to import.
    """
    gr.Markdown("> **Demo Mode:** Login is display-only; both tabs are accessible regardless of role.")

    # Instructions at the very top in an accordion
    with gr.Accordion("How to use (Student)", open=True):
        gr.Markdown(STUDENT_INSTRUCTIONS_MD)

    # Grade + Top 5 Readers
    s_grade = gr.Slider(1, 12, value=5, step=1, label="Your Grade")
    s_leader = gr.Dataframe(headers=["Student", "Count", "Books"], row_count=5, interactive=False, label="Top 5 Readers (your grade)")
    s_winner_md = gr.Markdown("No winner yet.")

    # --- NEW: Book Request accordion ---
    with gr.Accordion("Book Request", open=False):
        s_name = gr.Textbox(label="Your Name")
        s_book_req = gr.Dropdown(
            label="Choose a book",
            choices=[_book_label(bid) for bid in BOOK_DB.keys()],
            interactive=True
        )
        s_needed = gr.Textbox(label="Date needed by (YYYY-MM-DD)")
        s_special = gr.Textbox(label="Special request (optional)")
        s_req_btn = gr.Button("Submit Request", variant="primary")
        s_req_msg = gr.Markdown()
        s_req_table = gr.Dataframe(
            headers=["Title", "Status", "Available On", "Librarian Note"],
            interactive=False,
            label="My Requests",
            row_count=5
        )
        s_req_refresh = gr.Button("Refresh My Requests", size="sm")

    # Log a finished book (from approved)
    with gr.Accordion("Log a finished book (from your approved requests)", open=False):
        s_approved = gr.Dropdown(choices=[], label="Select from your approved requests", interactive=True)
        s_refresh = gr.Button("Refresh", size="sm")
        s_submit = gr.Button("Submit Finished Book", variant="primary")
        s_log_status = gr.Markdown()

    # Learn more about a book
    with gr.Accordion("Learn more about a book", open=False):
        s_book = gr.Dropdown(choices=list(BOOK_DB.keys()), label="Book ID")  # or pretty labels if you prefer
        s_q    = gr.Textbox(label="Your question", lines=2)
        s_ask  = gr.Button("Ask")
        s_ans  = gr.Textbox(label="Answer", lines=8)

    # --- Wiring (Student) ---
    # Book Request
    s_req_btn.click(
        submit_book_request,
        inputs=[s_name, s_book_req, s_needed, s_special],
        outputs=[s_req_msg, s_req_table, s_approved]
    )
    s_req_refresh.click(refresh_my_requests, inputs=[s_name], outputs=[s_req_table, s_approved])

    # Approved dropdown refresh + log finished (wire to your existing return/log handler if you have it)
    # If you already have _mark_request_returned, wire it here; otherwise leave as-is.
    try:
        s_refresh.click(_refresh_approved_dropdown, inputs=[s_name], outputs=[s_approved])  # optional if you have it
        s_submit.click(_mark_request_returned, inputs=[s_name, s_grade, s_approved], outputs=[s_log_status, s_approved])
    except NameError:
        pass

    # “Learn more" wiring — keep your existing handler
    try:
        s_ask.click(ui_student_learn_book, inputs=[s_book, s_q], outputs=[s_ans])
    except NameError:
        pass

    return {
        "grade": s_grade,
        "leader": s_leader,
        "winner_md": s_winner_md,
        "name": s_name,
        "req_table": s_req_table,
    }


def build_librarian_ui() -> Dict[str, Any]:
    """Build a richer Librarian tab for the demo.

    This function is safe to import; it constructs components when
    run inside a Blocks context (the primary `build_demo` uses it).
    """
    gr.Markdown("> **Demo Mode:** Login is display-only; both tabs are accessible regardless of role.")

    with gr.Accordion("How to use (Librarian)", open=True):
        gr.Markdown(LIBRARIAN_INSTRUCTIONS_MD)

    # Campaign (leave as you already have it)
    with gr.Accordion("Campaign Setup", open=False):
        l_title = gr.Textbox(label="Campaign Title")
        l_prize = gr.Textbox(label="Prize Rules")
        l_categories = gr.CheckboxGroup(
            choices=["fiction","non-fiction","sports","mystery","science","history","fantasy","animals"],
            value=["fiction","non-fiction","sports"],
            label="Categories"
        )
        with gr.Row():
            l_start = gr.Textbox(label="Start Date (YYYY-MM-DD)")
            l_end   = gr.Textbox(label="End Date (YYYY-MM-DD)")
        l_seed = gr.CheckboxGroup(choices=list(BOOK_DB.keys()), label="Featured Seed Books (IDs)")
        l_apply = gr.Button("Apply Campaign Settings", variant="primary")
        l_campaign_md = gr.Markdown("_(Campaign details will appear here)_")

    # --- NEW: Pending Book Requests ---
    with gr.Accordion("Pending Book Requests", open=False):
        l_pending_dd = gr.Dropdown(choices=[], label="Select a pending request", interactive=True)
        l_pending_refresh = gr.Button("Refresh", size="sm")
        l_avail = gr.Textbox(label="Available On (YYYY-MM-DD)")
        l_note  = gr.Textbox(label="Note to student (optional)")
        with gr.Row():
            l_approve = gr.Button("Approve", variant="primary")
            l_reject  = gr.Button("Reject", variant="secondary")
        l_decision_msg = gr.Markdown()
        l_student_mirror = gr.Dataframe(
            headers=["Title", "Status", "Available On", "Librarian Note"],
            interactive=False,
            label="Student's updated request list (mirror)",
            row_count=5
        )

    # Leaderboards / Winners (as you have)
    with gr.Accordion("Leaderboards & Winners", open=False):
        l_grade = gr.Slider(1, 12, value=5, step=1, label="Grade")
        l_refresh = gr.Button("Refresh Leaderboard")
        l_table = gr.Dataframe(headers=["Student", "Count", "Books"], row_count=5, interactive=False)
        l_pick = gr.Button("Pick Weekly Winner (by grade)")
        l_winner_md = gr.Markdown("_(Winner will appear here)_")

    # Research Assistant, RAG Uploads, Stats, Metrics… (unchanged)

    # --- Wiring (Librarian) ---
    l_pending_refresh.click(librarian_list_pending, inputs=[], outputs=[l_pending_dd])
    l_approve.click(librarian_approve, inputs=[l_pending_dd, l_avail, l_note], outputs=[l_decision_msg, l_pending_dd, l_student_mirror])
    l_reject.click(librarian_reject, inputs=[l_pending_dd, l_note], outputs=[l_decision_msg, l_pending_dd, l_student_mirror])

    return {}


def build_demo(return_blocks: bool = False):
    """Construct the Gradio Blocks UI.

    If return_blocks is True, return the Blocks instance instead of launching.
    This is helpful for testing or for mounting into a FastAPI app.
    """
    with gr.Blocks(title="Agentic RAG MVP — Student & Librarian (Demo)") as demo:
        # Demo login row (display only)
        with gr.Row():
            li_user = gr.Textbox(label="Username", scale=2)
            li_pass = gr.Textbox(label="Password (ignored in demo)", type="password", scale=2)
            li_role = gr.Radio(choices=["Student", "Librarian"], value="Student", label="Role (display only)", interactive=True, scale=2)
            li_btn = gr.Button("Sign in (Demo)", variant="primary", scale=1)
        li_msg = gr.Markdown("_Not signed in_")

        def demo_login(user, pwd, role):
            user = (user or "").strip()
            role = (role or "Student").strip()
            if not user:
                return "Please enter a username."
            return f"**Signed in (demo):** {user}  \n**Role selected:** {role}  \n_Note: In demo mode, both tabs are accessible regardless of role._"

        li_btn.click(demo_login, inputs=[li_user, li_pass, li_role], outputs=[li_msg])

        # Tabs ALWAYS visible; build each tab's UI INSIDE its context
        with gr.Tabs():
            with gr.Tab("Student"):
                gr.Markdown("> **Demo Mode:** Login is display-only; both tabs are accessible regardless of role.")
                gr.Markdown("### Student — Select your grade")
                s_grade = gr.Slider(1, 12, value=5, step=1, label="Your Grade")

                # Top 5 Readers under the grade slider
                s_leader = gr.Dataframe(headers=["Student", "Count", "Books"], row_count=5, interactive=False, label="Top 5 Readers (your grade)")

                # Winner of the week (friendly text) just below
                s_winner_md = gr.Markdown("No winner yet.")

                # Log a finished book (from your approved requests)
                with gr.Accordion("Log a finished book (from your approved requests)", open=False):
                    s_name = gr.Textbox(label="Your Name")
                    s_approved = gr.Dropdown(choices=[], label="Select from your approved requests", interactive=True)
                    s_refresh = gr.Button("Refresh", size="sm")
                    s_submit = gr.Button("Submit Finished Book", variant="primary")
                    s_log_status = gr.Markdown()

                # Learn more about a book
                with gr.Accordion("Learn more about a book", open=False):
                    s_book = gr.Dropdown(choices=[], label="Book ID")
                    s_q = gr.Textbox(label="Your question", lines=2)
                    s_ask = gr.Button("Ask")
                    s_ans = gr.Textbox(label="Answer", lines=8)

                with gr.Accordion("How to use (Student)", open=True):
                    gr.Markdown(STUDENT_INSTRUCTIONS_MD)

            with gr.Tab("Librarian"):
                gr.Markdown("> **Demo Mode:** Login is display-only; both tabs are accessible regardless of role.")
                gr.Markdown("### Librarian Console")

                # Keep all librarian accordions here, and set open=False so the tab loads collapsed
                with gr.Accordion("Campaign Setup", open=False):
                    # Campaign fields…
                    l_title = gr.Textbox(label="Campaign Title")
                    l_prize = gr.Textbox(label="Prize Rules")
                    l_categories = gr.CheckboxGroup(choices=["fiction", "non-fiction", "sports", "mystery", "science", "history", "fantasy", "animals"],
                                                    value=["fiction", "non-fiction", "sports"], label="Categories")
                    with gr.Row():
                        l_start = gr.Textbox(label="Start Date (YYYY-MM-DD)")  # DatePicker not available in all Gradio builds
                        l_end = gr.Textbox(label="End Date (YYYY-MM-DD)")
                    l_seed = gr.CheckboxGroup(choices=[], label="Featured Seed Books")
                    l_apply = gr.Button("Apply Campaign Settings", variant="primary")
                    l_campaign_md = gr.Markdown("_(Campaign details will appear here)_")

                with gr.Accordion("Leaderboards & Winners", open=False):
                    l_grade = gr.Slider(1, 12, value=5, step=1, label="Grade")
                    l_refresh = gr.Button("Refresh Leaderboard")
                    l_table = gr.Dataframe(headers=["Student", "Count", "Books"], row_count=5, interactive=False)
                    l_pick = gr.Button("Pick Weekly Winner (by grade)")
                    l_winner_md = gr.Markdown("_(Winner will appear here)_")

                with gr.Accordion("Research Assistant (Prompt)", open=False):
                    l_allow_web = gr.Checkbox(label="Allow web routing", value=False)
                    l_q = gr.Textbox(label="Your question", lines=2)
                    l_ask = gr.Button("Ask")
                    l_ans = gr.Textbox(label="Answer", lines=10)

                with gr.Accordion("Agentic RAG — Upload Sources", open=False):
                    rag_files = gr.Files(label="Upload text/CSV/JSON files")
                    ingest_btn = gr.Button("Ingest to RAG (demo)")
                    rag_status = gr.Code(label="Ingestion Status", language="json")

                with gr.Accordion("Admin — Vector Store Stats", open=False):
                    stats_btn = gr.Button("Refresh Stats")
                    stats_box = gr.Code(label="Qdrant / Embedding Stats", language="json")

                with gr.Accordion("Metrics / Analytics", open=False):
                    m_refresh = gr.Button("Generate Metrics")
                    m_plot = gr.Plot(label="Reading by Quarter / Year")
                    m_export_json = gr.Button("Export JSON")
                    m_export_csv = gr.Button("Export CSV")

                with gr.Accordion("How to use (Librarian)", open=True):
                    gr.Markdown(LIBRARIAN_INSTRUCTIONS_MD)

    # Optionally return the Blocks object for mounting into FastAPI
    if return_blocks:
        return demo

    return demo


if __name__ == "__main__":
    # Running as a script launches the demo locally
    demo_blocks = build_demo()
    demo_blocks.launch(share=False)

import gradio as gr
from typing import Dict, Any


def build_student_ui() -> Dict[str, Any]:
    """Return component references for the Student tab.

    This builder is safe to import and does not launch Gradio by itself.
    Callers should mount the returned components into a Blocks context.
    """
    return {
        "grade": "s_grade_slider",
        "leader": "s_leader_df",
        "winner_md": "s_winner_md",
        "name": "s_name",
        "approved": "s_approved_dropdown",
        "refresh": "s_refresh_btn",
        "submit": "s_submit_btn",
        "log_status": "s_log_status_md",
        "book": "s_book_dropdown",
        "q": "s_question",
        "ask": "s_ask_btn",
        "ans": "s_answer",
    }


def build_librarian_ui() -> Dict[str, Any]:
    """Return component references for the Librarian tab.

    Keep accordions closed by default (open=False).
    """
    return {
        "title": "l_title",
        "prize": "l_prize",
        "categories": "l_categories",
        "start": "l_start",
        "end": "l_end",
        "seed": "l_seed",
        "apply": "l_apply",
        "campaign_md": "l_campaign_md",
        "l_grade": "l_grade",
        "l_refresh": "l_refresh",
        "l_table": "l_table",
        "l_pick": "l_pick",
        "l_winner_md": "l_winner_md",
        "allow_web": "l_allow_web",
        "q": "l_q",
        "ask": "l_ask",
        "ans": "l_ans",
        "rag_files": "rag_files",
        "ingest_btn": "ingest_btn",
        "rag_status": "rag_status",
        "stats_btn": "stats_btn",
        "stats_box": "stats_box",
        "m_refresh": "m_refresh",
        "m_plot": "m_plot",
        "m_export_json": "m_export_json",
        "m_export_csv": "m_export_csv",
    }


def build_demo(return_blocks: bool = False):
    """Construct the Gradio Blocks UI.

    If return_blocks is True, return the Blocks instance instead of launching.
    This is helpful for testing or for mounting into a FastAPI app.
    """
    with gr.Blocks(title="Agentic RAG MVP — Student & Librarian (Demo)") as demo:
        # Demo login row (display only)
        with gr.Row():
            li_user = gr.Textbox(label="Username", scale=2)
            li_pass = gr.Textbox(label="Password (ignored in demo)", type="password", scale=2)
            li_role = gr.Radio(choices=["Student", "Librarian"], value="Student", label="Role (display only)", interactive=True, scale=2)
            li_btn = gr.Button("Sign in (Demo)", variant="primary", scale=1)
        li_msg = gr.Markdown("_Not signed in_")

        def demo_login(user, pwd, role):
            user = (user or "").strip()
            role = (role or "Student").strip()
            if not user:
                return "Please enter a username."
            return f"**Signed in (demo):** {user}  \n**Role selected:** {role}  \n_Note: In demo mode, both tabs are accessible regardless of role._"

        li_btn.click(demo_login, inputs=[li_user, li_pass, li_role], outputs=[li_msg])

        # Tabs ALWAYS visible; build each tab's UI INSIDE its context
        with gr.Tabs():
            with gr.Tab("Student"):
                gr.Markdown("> **Demo Mode:** Login is display-only; both tabs are accessible regardless of role.")
                gr.Markdown("### Student — Select your grade")
                s_grade = gr.Slider(1, 12, value=5, step=1, label="Your Grade")

                # Top 5 Readers under the grade slider
                s_leader = gr.Dataframe(headers=["Student", "Count", "Books"], row_count=5, interactive=False, label="Top 5 Readers (your grade)")

                # Winner of the week (friendly text) just below
                s_winner_md = gr.Markdown("No winner yet.")

                # Log a finished book (from your approved requests)
                with gr.Accordion("Log a finished book (from your approved requests)", open=False):
                    s_name = gr.Textbox(label="Your Name")
                    s_approved = gr.Dropdown(choices=[], label="Select from your approved requests", interactive=True)
                    s_refresh = gr.Button("Refresh", size="sm")
                    s_submit = gr.Button("Submit Finished Book", variant="primary")
                    s_log_status = gr.Markdown()

                # Learn more about a book
                with gr.Accordion("Learn more about a book", open=False):
                    s_book = gr.Dropdown(choices=[], label="Book ID")
                    s_q = gr.Textbox(label="Your question", lines=2)
                    s_ask = gr.Button("Ask")
                    s_ans = gr.Textbox(label="Answer", lines=8)

                gr.Markdown(
                    """
**How to use (Student):**
- Select your grade to see the leaderboard.
- You can only log **approved** books (from your requests).
- Lexile scores estimate reading complexity; higher = generally more advanced.
- Keep questions age-appropriate; avoid sharing personal info or links.
                    """
                )

            with gr.Tab("Librarian"):
                gr.Markdown("> **Demo Mode:** Login is display-only; both tabs are accessible regardless of role.")
                gr.Markdown("### Librarian Console")

                # Keep all librarian accordions here, and set open=False so the tab loads collapsed
                with gr.Accordion("Campaign Setup", open=False):
                    # Campaign fields…
                    l_title = gr.Textbox(label="Campaign Title")
                    l_prize = gr.Textbox(label="Prize Rules")
                    l_categories = gr.CheckboxGroup(choices=["fiction", "non-fiction", "sports", "mystery", "science", "history", "fantasy", "animals"],
                                                    value=["fiction", "non-fiction", "sports"], label="Categories")
                    with gr.Row():
                        l_start = gr.Textbox(label="Start Date (YYYY-MM-DD)")  # DatePicker not available in all Gradio builds
                        l_end = gr.Textbox(label="End Date (YYYY-MM-DD)")
                    l_seed = gr.CheckboxGroup(choices=[], label="Featured Seed Books")
                    l_apply = gr.Button("Apply Campaign Settings", variant="primary")
                    l_campaign_md = gr.Markdown("_(Campaign details will appear here)_")

                with gr.Accordion("Leaderboards & Winners", open=False):
                    l_grade = gr.Slider(1, 12, value=5, step=1, label="Grade")
                    l_refresh = gr.Button("Refresh Leaderboard")
                    l_table = gr.Dataframe(headers=["Student", "Count", "Books"], row_count=5, interactive=False)
                    l_pick = gr.Button("Pick Weekly Winner (by grade)")
                    l_winner_md = gr.Markdown("_(Winner will appear here)_")

                with gr.Accordion("Research Assistant (Prompt)", open=False):
                    l_allow_web = gr.Checkbox(label="Allow web routing", value=False)
                    l_q = gr.Textbox(label="Your question", lines=2)
                    l_ask = gr.Button("Ask")
                    l_ans = gr.Textbox(label="Answer", lines=10)

                with gr.Accordion("Agentic RAG — Upload Sources", open=False):
                    rag_files = gr.Files(label="Upload text/CSV/JSON files")
                    ingest_btn = gr.Button("Ingest to RAG (demo)")
                    rag_status = gr.Code(label="Ingestion Status", language="json")

                with gr.Accordion("Admin — Vector Store Stats", open=False):
                    stats_btn = gr.Button("Refresh Stats")
                    stats_box = gr.Code(label="Qdrant / Embedding Stats", language="json")

                with gr.Accordion("Metrics / Analytics", open=False):
                    m_refresh = gr.Button("Generate Metrics")
                    m_plot = gr.Plot(label="Reading by Quarter / Year")
                    m_export_json = gr.Button("Export JSON")
                    m_export_csv = gr.Button("Export CSV")

                gr.Markdown(
                    """
**How to use (Librarian):**
- Configure **Campaign Setup**, select **Featured Seed Books** (by title/Lexile), then **Apply**.
- Approve **Book Requests** and verify **Returns** to update leaderboards.
- **Research Assistant** can use web routing (SerpAPI) when enabled.
- **Metrics / Analytics** shows student performance by grade/quarter/year.
                    """
                )

    # Optionally return the Blocks object for mounting into FastAPI
    if return_blocks:
        return demo

    return demo


if __name__ == "__main__":
    # Running as a script launches the demo locally
    demo_blocks = build_demo()
    demo_blocks.launch(share=False)

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

    # WEB path: try a quick web search and synthesize bullets; fallback to LLM below
    if route_used == "web":
        try:
            results = serpapi_search(question, num=3)
            if results:
                bullets = format_results_bullets(results)[:1600]
                return f"Based on web results:\n\n{bullets}"
        except Exception:
            # If web search fails, fall back to LLM below
            pass
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
# ---------- Session state & simple login helpers ----------
# Session state keys:
# - session_role: "student" | "librarian" | None
# - session_user: username/display name
# - session_msg: banner / errors

def _check_student_login(user: str, pwd: str) -> bool:
    # Demo mode: any non-empty username is accepted, no password required.
    if not AUTH_STUDENTS:
        return bool((user or "").strip())
    return AUTH_STUDENTS.get((user or "").strip()) == (pwd or "")

# Demo-only login flow for the playground: no gating, only a banner message.
def demo_login(user: str, pwd: str, role: str):
    user = (user or "").strip()
    role = (role or "Student").strip()
    if not user:
        return "Please enter a username."
    # No gating—purely a banner message for demo
    return f"**Signed in (demo):** {user}  \n**Role selected:** {role}  \n_Note: In demo mode, both tabs are visible and unrestricted._"


def demo_logout():
    return "You have been logged out."


def _demo_finalize(msg: str, user: str, role: str):
    """Helper to finalize UI after demo login/logout: show both student and librarian views."""
    who_text = f"**Signed in (demo):** { (user or '') }  \n**Role selected:** { (role or '') }  \n_Note: In demo mode, both tabs are visible and unrestricted._"
    # Return values matching the outputs used in the .then() wiring later
    return (
        msg,
        gr.update(visible=False),  # hide login_view
        gr.update(visible=True),   # show app_view
        (role or "").lower() if role else None,
        user or None,
        who_text,
        gr.update(visible=True),   # student_view
        gr.update(visible=True),   # librarian_view
    )

with gr.Blocks(title="Agentic RAG MVP — Student & Librarian (Demo)") as demo:
    # --- Simple demo login banner (does not gate tabs) ---
    with gr.Row():
        li_user = gr.Textbox(label="Username", scale=2, placeholder="e.g., alex_t or librarian")
        li_pass = gr.Textbox(label="Password (ignored in demo)", type="password", scale=2)
        li_role = gr.Radio(choices=["Student", "Librarian"], value="Student", label="Role (display only)", interactive=True, scale=2)
        li_btn = gr.Button("Sign in (Demo)", variant="primary", scale=1)
    li_msg = gr.Markdown("_Not signed in_")

    # Wire the button to just update the banner text
    li_btn.click(demo_login, inputs=[li_user, li_pass, li_role], outputs=[li_msg])

    # --- Always-visible tabs (no role-based gating) ---
    with gr.Tabs():
        with gr.Tab("Student"):
            gr.Markdown("> **Demo Mode:** Login is display-only; both tabs are accessible regardless of role.")
            # >>> your existing Student UI goes here (no Column visibility toggles)

        with gr.Tab("Librarian"):
            gr.Markdown("> **Demo Mode:** Login is display-only; both tabs are accessible regardless of role.")
            # >>> your existing Librarian UI goes here
            # Set all accordions open=False by default if you want them collapsed on load
            pass

        # ---- How to use (Student) AT TOP ----
        with gr.Accordion("How to use (Student)", open=False):
            gr.Markdown(
                "- **You may only log books that were approved from your requests.**\n"
                "- **Use the 'Log a finished book' accordion to record a finished book.** Status updates (pending, approved, returned) will appear under the 'Log Status' area.\n"
                "- **Use the 'Learn more about a book' accordion to view Lexile scores and other metadata before requesting.**\n"
                "- Set your **grade** to see the weekly winner and top readers.\n"
                "- **Lexile (reading level)**: a number that estimates difficulty (lower = easier, higher = more challenging). Aim near your level, and stretch a bit for growth.\n"
                "- **Key terms**: *Pending* = awaiting quiz/approval; *Approved* = counts on the board; *Rejected* = not counted.\n"
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

        # Wire student-side behavior for requests
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

        # ---- Log a finished book (from your approved requests) ----
        with gr.Accordion("Log a finished book (from your approved requests)", open=False):
            with gr.Row():
                s_name = gr.Textbox(label="Your Name", placeholder="First name & last initial (e.g., Sam T.)")
                # s_grade already exists above

            # pick from only *approved* requests for this student
            with gr.Row():
                log_dropdown = gr.Dropdown(
                    label="Select from your approved requests",
                    choices=[],
                    allow_custom_value=False,
                    interactive=True,
                )
                log_refresh = gr.Button("Refresh", scale=1)

            with gr.Row():
                log_submit = gr.Button("Submit Finished Book")

            log_status = gr.Textbox(label="Log Status", interactive=False)

            # Move the Top 5 Readers into this accordion (contextual for the student)
            s_leader = gr.Dataframe(headers=["Student", "Count", "Books"], row_count=5, interactive=False, label="Top 5 Readers (your grade)")

        # Helper to refresh winner + leaderboard together (reintroduced)
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

        # Populate the approved-request dropdown whenever name or grade changes
        def _refresh_approved_dropdown_ui(g, n):
            # call the runtime helper that expects (user) and returns a list
            return gr.update(choices=_refresh_approved_dropdown((n or "").strip()), value=None)

        s_name.change(_refresh_approved_dropdown_ui, inputs=[s_grade, s_name], outputs=[log_dropdown])
        s_grade.release(_refresh_approved_dropdown_ui, inputs=[s_grade, s_name], outputs=[log_dropdown])
        log_refresh.click(_refresh_approved_dropdown_ui, inputs=[s_grade, s_name], outputs=[log_dropdown])

        # Wire the submit button to the more complete user-provided flow
        # Our _mark_request_returned returns (msg, refreshed_choices)
        log_submit.click(
            _mark_request_returned,
            inputs=[s_name, s_grade, log_dropdown],
            outputs=[log_status, log_dropdown]
        )

        # ---- Learn more about a book (safe chat) — moved below logging ----
        with gr.Accordion("Learn more about a book", open=False):
            with gr.Row():
                # Quick lookup by ID (handy if student knows bk ID)
                book_id_input = gr.Textbox(label="Enter Book ID")
                book_lookup_btn = gr.Button("Lookup Book")

            book_info_output = gr.Markdown()

            # Also keep the existing dropdown + Ask chat UI inside the accordion
            with gr.Row():
                s_book = gr.Dropdown(choices=BOOK_CHOICES(), value=FIRST_BOOK_ID_DEFAULT(), label="Book")
                s_q = gr.Textbox(label="Your question", placeholder="e.g., What is the main theme? Is this age-appropriate for grade 5?", lines=2)

            def _student_book_info(bid: str):
                info = BOOK_DB.get(bid) or {}
                title = info.get("title", "Untitled")
                author = info.get("author", "Unknown")
                cat = info.get("category", "other")
                lx = info.get("lexile", "—")
                return f"**Selected:** *{title}* — {author}  •  Category: `{cat}`  •  Lexile: `{lx}`"

            # Wire quick lookup (also used by dropdown change)
            book_lookup_btn.click(lambda bid: _student_book_info((bid or "").strip()), inputs=[book_id_input], outputs=[book_info_output])
            s_book.change(_student_book_info, inputs=[s_book], outputs=[book_info_output])

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

    with gr.Tab("Librarian") as librarian_tab:
        # IMPORTANT: wrap all librarian UI in a Column we can toggle
        with gr.Column(visible=False) as librarian_view:
            gr.Markdown("### Librarian Console")

        with gr.Accordion("How to use (Librarian)", open=False):
            gr.Markdown(
                "- **Review pending requests and quiz submissions in your tab.**\n"
                "- **Approve books to allow students to log them.**\n"
                "- **Approved books flow into students’ 'Log a finished book' accordion. Returned books close the loop.**\n"
                "- **Campaign Setup**: set title, prize rules, dates, featured books.\n"
                "- **Leaderboards & Winners**: leaders reflect **approved** books only. Use **Pick Weekly Winner** when ready.\n"
                "- **Reading Insights**: top categories and **average Lexile by category** (approved books only).\n"
                "- **Lexile**: numeric reading difficulty (lower = easier, higher = advanced). Use averages to gauge appropriateness and growth.\n"
                "- **Key terms**: *Pending* = awaiting quiz/approval; *Approved* = counted; *Rejected* = not counted.\n"
                "- **Research Assistant**: router-aware (vector/web/LLM); enable web routing for recency; cite snippets.\n"
                "- **Agentic RAG**: upload txt/md/csv/jsondocx/pdf; chunk to Qdrant for retrieval."
            )

            with gr.Accordion("Campaign Setup", open=False):
                l_title = gr.Textbox(label="Campaign Title", value=CAMPAIGN.get("title", "Reading Week Spotlight"))
                l_prize = gr.Textbox(label="Prize Rules", value=CAMPAIGN.get("prize_rules", ""))

                l_categories = gr.CheckboxGroup(
                    choices=list({*CAMPAIGN.get("categories", DEFAULT_CATEGORIES), *[b.get("category", "other") for b in BOOK_DB.values()]}),
                    value=CAMPAIGN.get("categories", DEFAULT_CATEGORIES),
                    label="Categories"
                )

                with gr.Row():
                    # Use plain textboxes to accept YYYY-MM-DD strings for broader compatibility
                    l_start = gr.Textbox(label="Start Date (YYYY-MM-DD)", value=CAMPAIGN.get("start_date") or "")
                    l_end = gr.Textbox(label="End Date (YYYY-MM-DD)",   value=CAMPAIGN.get("end_date") or "")

                # --- Featured Seed Books accordion (stays above campaign details) ---
                with gr.Accordion("Featured Seed Books", open=False):
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
                        "title": title or CAMPAIGN.get("title", "Reading Week Spotlight"),
                        "prize_rules": prize_rules or CAMPAIGN.get("prize_rules", ""),
                        "categories": categories or CAMPAIGN.get("categories", DEFAULT_CATEGORIES),
                        "start_date": start_iso or CAMPAIGN.get("start_date"),
                        "end_date": end_iso or CAMPAIGN.get("end_date"),
                        "seed_list": seed_list or CAMPAIGN.get("seed_list", []),
                    })
                    return campaign_markdown(CAMPAIGN)

                # When campaign is applied, refresh both the campaign card and the Spotlight panel
                apply_btn.click(
                    _ui_librarian_set_campaign,
                    inputs=[l_title, l_prize, l_categories, l_start, l_end, l_seed],
                    outputs=[l_campaign_md],
                )

            # (Spotlight display moved into Campaign Setup above)

            with gr.Accordion("Leaderboards & Winners", open=False):
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

                with gr.Accordion("Approvals Queue", open=False):
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

                    a_approve.click(_approve_selected, inputs=[a_grade, a_select], outputs=[a_status, a_table, a_select, a_detail, a_quiz_md, s_winner, s_leader, log_status])
                    a_reject.click(_reject_selected, inputs=[a_grade, a_select], outputs=[a_status, a_table, a_select, a_detail, a_quiz_md, s_winner, s_leader, log_status])

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

                    # Show returned items by default on explicit refresh
                    br_refresh.click(lambda _: _br_list(True), inputs=[br_show_all], outputs=[br_table, br_select, br_detail, br_msg])
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
# Populate approved-request dropdown on page load (optional)
try:
    demo.load(_refresh_approved_dropdown, inputs=[s_grade, s_name], outputs=[log_dropdown])
except Exception:
    # silent if widgets not available at import time
    pass

# Demo mode: simple banner-only login; no additional wiring required here.
# The Sign-in button already wires directly to `demo_login` above.

app = mount_gradio_app(app, demo, path="/")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")))