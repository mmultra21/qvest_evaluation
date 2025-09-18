# app/llm_client.py
import os
import json
import time
from typing import Iterable, Optional, Dict, Any
import requests

LLAMA_HOST = os.environ.get("LLM_HOST", "127.0.0.1")
LLAMA_PORT = int(os.environ.get("LLM_PORT", "11434"))
LLAMA_URL  = os.environ.get("LLM_URL", f"http://{LLAMA_HOST}:{LLAMA_PORT}")

# Toggle depending on how llama-server was built:
#  - native llama.cpp (default below): /completion or /chat
#  - OpenAI-compatible: set LLM_API_STYLE=openai to hit /v1/chat/completions
API_STYLE = os.environ.get("LLM_API_STYLE", "llama").lower()

SESSION = requests.Session()
SESSION.headers.update({"Content-Type": "application/json"})

class LLMClient:
    def __init__(self, url: str = LLAMA_URL, api_style: str = API_STYLE, timeout: int = 120):
        self.url = url.rstrip("/")
        self.api_style = api_style
        self.timeout = timeout

    # ---------- Simple completion (single-turn) ----------
    def completion(self, prompt: str, max_tokens: int = 256, temperature: float = 0.7) -> str:
        if self.api_style == "openai":
            endpoint = f"{self.url}/v1/completions"
            payload = {
                "model": "hermes3",  # ignored by llama.cpp, but required by schema
                "prompt": prompt,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            r = SESSION.post(endpoint, data=json.dumps(payload), timeout=self.timeout)
            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["text"]
        else:
            endpoint = f"{self.url}/completion"
            payload = {
                "prompt": prompt,
                "n_predict": max_tokens,
                "temperature": temperature,
                "stop": ["</s>"]
            }
            r = SESSION.post(endpoint, data=json.dumps(payload), timeout=self.timeout)
            r.raise_for_status()
            data = r.json()
            return data.get("content", data.get("generation", ""))

    # ---------- Chat completion (multi-turn) ----------
    def chat(self, messages: Iterable[Dict[str, str]], max_tokens: int = 512,
             temperature: float = 0.7) -> str:
        """
        messages: list like [{"role":"system","content":"..."},{"role":"user","content":"..."}]
        """
        if self.api_style == "openai":
            endpoint = f"{self.url}/v1/chat/completions"
            payload = {
                "model": "hermes3",
                "messages": list(messages),
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            r = SESSION.post(endpoint, data=json.dumps(payload), timeout=self.timeout)
            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["message"]["content"]
        else:
            endpoint = f"{self.url}/chat"
            # llama.cpp expects {"messages":[{"role":"system","content":"..."},...]}
            payload = {
                "messages": list(messages),
                "n_predict": max_tokens,
                "temperature": temperature,
            }
            r = SESSION.post(endpoint, data=json.dumps(payload), timeout=self.timeout)
            r.raise_for_status()
            data = r.json()
            # Native server often returns {"content":"..."} or {"message":{"content":"..."}}
            return data.get("content") or (data.get("message") or {}).get("content", "")

    # ---------- Streaming chat (generator) ----------
    def stream_chat(self, messages: Iterable[Dict[str, str]],
                    max_tokens: int = 512, temperature: float = 0.7) -> Iterable[str]:
        if self.api_style == "openai":
            endpoint = f"{self.url}/v1/chat/completions"
            payload = {
                "model": "hermes3",
                "messages": list(messages),
                "max_tokens": max_tokens,
                "temperature": temperature,
                "stream": True,
            }
            with SESSION.post(endpoint, data=json.dumps(payload), stream=True, timeout=self.timeout) as r:
                r.raise_for_status()
                for line in r.iter_lines(decode_unicode=True):
                    if not line or not line.startswith("data:"):
                        continue
                    chunk = line[len("data:"):].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        data = json.loads(chunk)
                        delta = data["choices"][0]["delta"].get("content")
                        if delta:
                            yield delta
                    except Exception:
                        continue
        else:
            endpoint = f"{self.url}/chat"
            payload = {
                "messages": list(messages),
                "n_predict": max_tokens,
                "temperature": temperature,
                "stream": True,
            }
            with SESSION.post(endpoint, data=json.dumps(payload), stream=True, timeout=self.timeout) as r:
                r.raise_for_status()
                for line in r.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        delta = data.get("content", "")
                        if delta:
                            yield delta
                    except Exception:
                        continue

# convenience singleton
client = LLMClient()