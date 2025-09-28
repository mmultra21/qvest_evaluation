# agentic-rag-mvp

Minimal scaffold for an agentic RAG MVP combining a Gradio app and a FastAPI backend.

How to run (local development)

1. Create a Python virtualenv and install dependencies manually (example):

```bash
# agentic-rag-mvp (Agentic RAG MVP)

Minimal demo scaffold combining a Gradio Student + Librarian UI and lightweight helper code for prototyping an approval + reading-tracking workflow.

This README was updated to reflect the current demo-focused scaffold (single-file Gradio demo in `app/gradio_main.py` and an editable working copy `app/gradio_main copy.py`). The project intentionally keeps most features in-memory so you can iterate quickly.

## Highlights / Recent updates
- Single-file Gradio demo UI: Student and Librarian tabs are always visible in demo mode (no gating). A demo login banner is provided (display-only).
- In-memory request workflow: `BOOK_REQUESTS` and `LIBRARIAN_QUEUES` implement a simple submit → approve/reject lifecycle.
- Deterministic book labels and parsers: `_book_label(...)` and `_parse_id_from_label(...)` provide stable labels for dropdowns.
- Demo-friendly stubs: lightweight stubs for LLM/search/RAG functions are included so the demo module imports without heavy external dependencies. Legacy functionality can be re-enabled via an `ENABLE_LEGACY=1` env var if you later add `app/gradio_legacy.py`.
- Tests: a focused pytest file was added at `tests/test_book_request_flow.py` that exercises submit → approve and submit → reject flows against the copy file using an injected dummy `gradio` module.

## Quick start (recommended: use a virtualenv)
macOS notes: the system Python may be "externally managed" (Homebrew/OS protections). Use a virtualenv to avoid permission or system-package errors.

1. Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Install runtime deps if you want to run the UI interactively (optional for tests):

```bash
pip install gradio
```

3. Run the demo UI (in a venv where `gradio` is installed):

```bash
python -m app.gradio_main
```

This opens a Gradio UI locally and prints the URL. The demo uses in-memory stores — nothing is persisted.

## Run tests (no Gradio install required)
The repo includes a small test harness that imports the working copy file by path. The test loader injects a tiny dummy `gradio` module so you don't need the real Gradio to run unit tests.

From the repository root (recommended inside a venv):

```bash
.venv/bin/python -m pip install pytest
.venv/bin/python -m pytest -q tests/test_book_request_flow.py
```

Notes:
- The repository may contain other tests that depend on extra dependencies (FastAPI, etc.). If you want to run just the focused request-flow tests, point pytest at `tests/test_book_request_flow.py` like above.
- If `pip` warns about an externally-managed environment, create and use a venv (as above) or use `pipx` for global tools.

## What the tests cover
- `tests/test_book_request_flow.py` creates a fresh in-memory state, calls `submit_book_request(...)`, asserts the pending queue contains the item, then calls `librarian_approve(...)` (or `librarian_reject(...)`) and verifies the student-side refresh shows the updated status.

## Developer notes & recommendations
- The demo is intentionally minimal and keeps many legacy helpers in-file or stubbed. To keep the top-level module importable:
  - Lightweight stubs are provided for LLM/search/RAG helpers; replace them with real implementations when ready.
  - A conditional `ENABLE_LEGACY` env var is present: set `ENABLE_LEGACY=1` to attempt importing a separate `app/gradio_legacy.py` (not included by default). This is a safe way to keep heavy legacy code out of the import path until needed.
- If you plan to persist data, add a small SQLite adapter or write to JSON files and wire a load/save strategy.

## Next steps (suggested)
- Move large legacy blocks into `app/gradio_legacy.py` and keep the demo import-safe by default.
- Expand unit tests to cover edge cases (duplicate requests, invalid dates, concurrent approvals).
- Add a small seed script to populate `BOOK_DB` and some sample `BOOK_REQUESTS` to exercise the UI quickly.
- Optionally add a `requirements.txt` and a simple GitHub Actions workflow to run the targeted pytest file.

If you'd like, I can implement any of the next steps: move legacy code to a separate module, add more tests, or create a seed script. Tell me which you'd like next.


- Approvals Queue: review pending submissions, preview the student quiz answer, approve or reject. Approve calls `record_reading(...)` which updates `READ_LOGS`, `BOOK_PREFS`, and appends a `READ_EVENTS` entry (ts, grade, student, book_id).

## Quick dev commands

Use the repository virtualenv to run the helper tools. Adjust the port as needed.

Launch the Admin UI (serves the audit approvals UI):

```bash
.venv/bin/python agentic-rag-mvp/tools/admin_ui.py 7861
```

Run the judge demo script (safe demo mode, may write judge logs):

```bash
.venv/bin/python agentic-rag-mvp/tools/llm_judge.py --demo
```

Run the Gradio proof-of-concept script:

```bash
.venv/bin/python agentic-rag-mvp/tools/run_gradio_poc.py
```

Quick import check (CI-friendly) to validate module imports and DB access without starting servers:

```bash
.venv/bin/python - <<'PY'
import sys, sqlite3
sys.path.append('agentic-rag-mvp')
try:
  import tools.admin_ui as admin
  print('admin_ui import ok')
except Exception as e:
  print('admin_ui import failed:', e)
con = sqlite3.connect('agentic-rag-mvp/data/agent.db')
cur = con.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
print('tables:', cur.fetchall())
con.close()
PY
```

If you'd like, I can add a small wrapper script at `tools/run_admin_ui.py` so you can run `.venv/bin/python tools/run_admin_ui.py 7861` from the repo root instead of the longer path above.
