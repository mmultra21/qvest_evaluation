# qvest_evaluation
Employment Evaluation

This repository contains an `agentic-rag-mvp` scaffold demonstrating a small FastAPI backend, a Gradio UI, a recommender tool, and simple tests. The project is intended as a local demo to iterate on recommender + justifier UX backed by a local model or deterministic logic.

Quickstart (macOS)

1. Create and activate a virtualenv (macOS / zsh):

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r agentic-rag-mvp/requirements.txt
```

2. Start the FastAPI backend (from repo root). Make sure `PYTHONPATH` includes the `agentic-rag-mvp` package so `api` imports resolve:

```bash
export PYTHONPATH="$PWD/agentic-rag-mvp"
.venv/bin/python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

3. Start the Gradio UI (in another shell; it will call the API at http://127.0.0.1:8000 by default):

```bash
export PYTHONPATH="$PWD/agentic-rag-mvp"
.venv/bin/python agentic-rag-mvp/app/main.py
```

4. Run tests (from repo root):

```bash
.venv/bin/python -m pytest -q
```

Files of interest
- `agentic-rag-mvp/api/main.py` — FastAPI app exposing `/campaign/current`, `/recommend`, and `/justify`.
- `agentic-rag-mvp/api/tools/recommender.py` — simple in-repo recommender logic and catalog.
- `agentic-rag-mvp/app/main.py` — Gradio UI wired to the API.
- `agentic-rag-mvp/tests/test_api_endpoints.py` — pytest tests using FastAPI `TestClient`.

Developer notes
---------------
- This project uses Pydantic v2 in the development environment. A small migration was applied to convert v1 `@validator` usages to the v2 `@field_validator` API where safe.
- If you need to perform a conservative automated pass, see `scripts/migrate_pydantic_v2.py` which writes `.bak` files before editing. Review `.bak` files after running the script.

Testing LLM drift (dev-only)
---------------------------
- There's a developer hook to force a malformed justifier response so you can verify UI behavior when the LLM output drifts. To run the backend with the malformed hook:

```bash
export PYTHONPATH="$PWD/agentic-rag-mvp"
RAG_FORCE_MALFORMED=1 .venv/bin/python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

Then open the Gradio UI (in another shell) and click "Get my Top 5". The Student tab shows a red error box when the API returns a 422 validation error.


Notes
- The justifier is a lightweight placeholder: you can replace or extend it to call a local model server for richer language-generated pitches.
- If `uvicorn` is not on your PATH, run it via the venv Python (`python -m uvicorn ...`) as shown above.

Headless UI capture (optional)
------------------------------
If you want a scripted screenshot of the Gradio UI (useful for CI or demos) you can use Playwright:

1. Install into the repo venv:

```bash
.venv/bin/python -m pip install playwright
.venv/bin/python -m playwright install
```

2. Start backend + Gradio (with dev hook enabled if you want the error box):

```bash
export PYTHONPATH="$PWD/agentic-rag-mvp"
ALLOW_DEV_HOOKS=1 RAG_FORCE_MALFORMED=1 .venv/bin/python -m uvicorn api.main:app --host 127.0.0.1 --port 8000 &
.venv/bin/python agentic-rag-mvp/app/main.py &
```

3. Run the capture script:

```bash
.venv/bin/python scripts/capture_gradio.py
```

The script saves `gradio_capture.png` in the repo root by default.
