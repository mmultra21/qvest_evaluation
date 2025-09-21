# agentic-rag-mvp

Minimal scaffold for an agentic RAG MVP combining a Gradio app and a FastAPI backend.

How to run (local development)

1. Create a Python virtualenv and install dependencies manually (example):

```bash
python -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn gradio pydantic
```

2. Run the API and app in separate terminals:

```bash
# agentic-rag-mvp

Lightweight RAG MVP combining a Gradio UI and FastAPI wiring. This prototype provides a Student-facing logging flow and a Librarian console for approvals, campaigns, and metrics.

Table of contents
- Overview
- Recent changes (high level)
- Quick start
- Student workflow
- Librarian workflow
- Metrics & exports
- Developer notes

## Overview

This project is an in-memory demo used to prototype reading campaigns and a small approval workflow. It is intentionally simple so you can iterate quickly. Core in-memory stores:

- `BOOK_DB` — deterministic book catalog loaded from JSON/demo data
- `PENDING_LOGS` — student submissions waiting for librarian review
- `READ_LOGS` — approved readings grouped by grade/student
- `READ_EVENTS` — lightweight event log (timestamped) used for time-based metrics

## Recent changes

- Student "Submit for approval" flow: mini-quiz and quiz pass/save logic; submissions go into `PENDING_LOGS`.
- Campaign Setup: title, prize rules, categories, start/end dates (YYYY-MM-DD), and featured seed books. Dates validated on apply.
- `READ_EVENTS`: appended when a librarian approves a submission; used to compute quarterly/yearly metrics.
- Metrics helpers added (pandas + matplotlib) and a Librarian "Metrics & Exports" accordion to compute charts and export JSON/CSV.

## Quick start

1. Create a virtualenv and install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

If you don't have `requirements.txt`, at minimum:

```bash
pip install gradio fastapi uvicorn pandas matplotlib python-dotenv
```

2. Run the app (Gradio UI mounted on FastAPI):

```bash
python -m app.gradio_main
```

3. Open the printed local URL in your browser (Gradio UI).

## Student workflow

- Student tab: choose grade, enter your name, pick a book and answer the mini-quiz, then click "Submit for approval".
- Submissions appear in "My submissions" and are placed into `PENDING_LOGS`.

## Librarian workflow

- Approvals Queue: review pending submissions, preview the student quiz answer, approve or reject. Approve calls `record_reading(...)` which updates `READ_LOGS`, `BOOK_PREFS`, and appends a `READ_EVENTS` entry (ts, grade, student, book_id).
- Campaign Setup: edit the campaign card and featured seeds. Start/end date fields expect `YYYY-MM-DD` strings and are validated.
- Leaderboards & Winners: refresh per-grade leaderboards, pick weekly winners, and view recent winners.

## Metrics & Exports

- The Librarian tab includes a "Metrics & Exports" accordion (below Leaderboards). Click "Compute / Refresh Metrics" to render:
  - Books per quarter (overall)
  - Books per quarter by grade (stacked)
  - A table (quarter, grade, books_read)
- Export JSON or CSV using the Export buttons; the app writes temporary files and returns them via Gradio File components.

## Developer notes

- Data is in-memory. For persistence, add a simple SQLite layer or save to files.
- The campaign date fields use simple textbox inputs to support a broader range of Gradio versions; `_ui_librarian_set_campaign` validates `YYYY-MM-DD`.
- Metrics use `pandas` and `matplotlib`. If these are not needed, remove the imports to keep dependencies light.

## Testing the flow

1. As a Student, submit an entry and answer the mini-quiz.
2. In Librarian → Approvals Queue, approve the submission.
3. Compute metrics and observe the new event appearing in quarterly summaries.

## Next steps

- Persist events and logs to disk or SQLite.
- Add unit tests for the submit→approve→metrics pipeline.
- Improve the Approvals UI (bulk actions, search, filters).

If you'd like, I can also add a small script to seed test data and exercise the pipeline automatically.

