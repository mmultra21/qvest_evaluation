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

