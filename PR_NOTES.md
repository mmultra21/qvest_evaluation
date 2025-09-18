Pydantic v2 migration and dev-hook gating

Summary
-------
This branch contains the following changes:

- Migrated local Pydantic models used for LLM justification to Pydantic v2 API (`@field_validator`) and added a conservative automated migration helper `scripts/migrate_pydantic_v2.py`.
- Added a guarded developer hook in `agentic-rag-mvp/api/tools/rag.py` to force a malformed LLM response for UI error-surface testing. The hook is gated behind two environment variables: `RAG_FORCE_MALFORMED=1` and `ALLOW_DEV_HOOKS=1`.
- Added a unit test that ensures the `/justify` endpoint returns HTTP 422 when LLM output fails schema validation.
- Documented the migration and dev-hook usage in `README.md`.

Why Pydantic v2?
-----------------
- Pydantic v2 is the supported version in our environment (v2.9.2). It provides performance and API improvements. The FastAPI version in this repo (0.112.2) is compatible with Pydantic v2.

Safety measures
---------------
- The dev-only malformed hook now requires both `RAG_FORCE_MALFORMED=1` and `ALLOW_DEV_HOOKS=1` so it cannot be accidentally enabled in CI or production.
- The migration script writes `.bak` files for manual review and was run locally; tests passed (11 passed, 1 unrelated warning).

How to reproduce the drift test (dev only)
-----------------------------------------
1. Start the backend with the dev hook enabled:

```bash
export PYTHONPATH="$PWD/agentic-rag-mvp"
ALLOW_DEV_HOOKS=1 RAG_FORCE_MALFORMED=1 .venv/bin/python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

2. Start the Gradio UI and click "Get my Top 5" in the Student tab

3. Observe the red error box with Pydantic validation details.

Notes
-----
- The dev hook and migration helper are intended to assist local development and testing. They are not intended for production use.

