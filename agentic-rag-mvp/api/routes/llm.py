# api/routes/llm.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from app.llm_client import client

router = APIRouter(prefix="/llm", tags=["llm"])

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    max_tokens: int = 512
    temperature: float = 0.7
    stream: bool = False

@router.post("/chat")
def chat(req: ChatRequest):
    try:
        if req.stream:
            # For simplicity, non-streaming response here; streaming can be added with Server-Sent Events
            text = "".join(client.stream_chat([m.dict() for m in req.messages],
                                              max_tokens=req.max_tokens,
                                              temperature=req.temperature))
            return {"text": text}
        else:
            text = client.chat([m.dict() for m in req.messages],
                               max_tokens=req.max_tokens,
                               temperature=req.temperature)
            return {"text": text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))