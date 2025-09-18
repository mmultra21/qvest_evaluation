Pydantic v2 migration (release note)
===================================

Summary
-------
This release includes a small, targeted migration to Pydantic v2 for the local models used by the LLM justification flow. The change was intentionally conservative and tested locally.

What changed
------------
- Replaced Pydantic v1-style validators (`@validator`) with Pydantic v2 `@field_validator` where appropriate.
- Added a small migration helper script `scripts/migrate_pydantic_v2.py` that performs a conservative, mechanical replacement and writes `.bak` files for review.
- Updated `agentic-rag-mvp/api/models_llm.py` to use v2 validators.
- Added a unit test to ensure `/justify` returns HTTP 422 when LLM output violates the schema.
- Added a developer-only hook in `agentic-rag-mvp/api/tools/rag.py` to allow forcing malformed LLM output for local UI testing; the hook is gated behind `ALLOW_DEV_HOOKS=1` and `RAG_FORCE_MALFORMED=1`.

Why
---
Pydantic v2 is the current stable version in the environment and offers improved performance and clearer validation semantics. FastAPI (v0.112.2) used in this project is compatible with Pydantic v2.

Safety and testing
------------------
- The migration script is conservative and backs up each file it edits with a `.bak` file for manual review.
- The dev hook is double-gated via environment variables to avoid accidental enabling in CI or production.
- Tests were run locally and passed (11 passed, 1 unrelated warning from Starlette). Please run the test suite in CI to confirm behavior on your infrastructure.

How to reproduce
----------------
1. Set up the venv and install dependencies (see README).
2. Optionally run the migration helper:

```bash
python3 scripts/migrate_pydantic_v2.py
```

3. Start the backend with the dev hook (for local testing only):

```bash
export PYTHONPATH="$PWD/agentic-rag-mvp"
ALLOW_DEV_HOOKS=1 RAG_FORCE_MALFORMED=1 .venv/bin/python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

4. Run the test suite:

```bash
.venv/bin/python -m pytest -q
```

Notes
-----
- Please review the `.bak` files created by the migration helper before merging if you run it again.
- If you prefer to remain on Pydantic v1 for compatibility reasons, we can revert the changes and pin pydantic==1.x in `requirements.txt`.

