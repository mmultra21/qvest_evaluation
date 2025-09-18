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

Testing the Hermes-3 model server
--------------------------------

If you build and run `llama-server` (llama.cpp) as in `scripts/run_hermes3.sh`, the server will listen on the configured port (default 11434). Use these exact curl commands to verify the server and get a sample completion.

1) Health check

```bash
curl http://127.0.0.1:11434/health
# expected response: {"status":"ok"}
```

2) Simple completion (JSON request)

```bash
curl http://127.0.0.1:11434/completion \
	-H "Content-Type: application/json" \
	-d '{"prompt":"Hello Hermes3!","n_predict":64,"temperature":0.2}'
```

Example response (trimmed):

```json
{
	"index": 0,
	"content": " Welcome to the forums!\nI'm Hermes3, a new member to this forum...",
	"id_slot": 0,
	"model": "gpt-3.5-turbo",
	"tokens_predicted": 55,
	"generation_settings": {
		"n_predict": 64,
		"temperature": 0.2
	}
}
```

Notes
- If the server binary is not in `$HOME/src/llama.cpp/server`, point `LLAMA_DIR` to the folder containing `server` before running `scripts/run_hermes3.sh`.
- On Apple Silicon you can build with Metal support; the server will show Metal device initialization in logs when using Metal.


Client usage
------------

The repository contains a minimal stdlib Python client at `agentic-rag-mvp/scripts/clients/complete.py`.

Basic usage (from repo root):

```bash
source .venv/bin/activate    # recommended
python3 ./agentic-rag-mvp/scripts/clients/complete.py --prompt 'Hello Hermes3!'
```

Specify host/port or full URL:

```bash
python3 ./agentic-rag-mvp/scripts/clients/complete.py --host 127.0.0.1 --port 11434 --prompt 'Hi'
python3 ./agentic-rag-mvp/scripts/clients/complete.py --url 'http://127.0.0.1:11434/completion' --prompt 'Hi'
```

Advanced flags:
- `--timeout` seconds (default 10.0)
- `--retries` number of attempts on network error (default 1)
- `--raw` print raw JSON output
- `--verbose` print extra metadata

If you want to run the tests or CI locally, install the test dependency and run pytest:

```bash
python3 -m pip install -r requirements.txt
python3 -m pytest -q
```

