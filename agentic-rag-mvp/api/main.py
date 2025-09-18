from fastapi import FastAPI

app = FastAPI(title="agentic-rag-mvp API")


@app.get("/health")
async def health():
    return {"status": "ok"}
