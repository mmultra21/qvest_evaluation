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
python -m api.main
python -m app.main
```

Notes
- This is a scaffold: replace placeholder functions with real implementations. Add `pyproject.toml` or `requirements.txt` if you want reproducible installs.
