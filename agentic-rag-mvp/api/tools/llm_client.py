import os, re, json, time, requests
from typing import Optional, Dict, Any

# Point to your running llama.cpp server (Hermes-3)
LLM_ENDPOINT = os.getenv("LLM_ENDPOINT", "http://127.0.0.1:11434")

# Preferred route first; some builds serve /completion, others only OpenAI-style
LLM_ROUTE_PRIMARY = os.getenv("LLM_ROUTE", "/completion")
LLM_ROUTE_FALLBACK = "/v1/chat/completions"   # OpenAI-like

# Tunables for Hermes-3 (quantized)
DEFAULT_N_PREDICT = int(os.getenv("LLM_N_PREDICT", "128"))
DEFAULT_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.25"))
DEFAULT_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "120"))

def _post_json(url: str, payload: dict, timeout: float) -> dict:
    r = requests.post(url, json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()

def extract_json_block(text: str) -> Optional[str]:
    # 1) ```json fenced block
    m = re.search(r"```json\s*(\{[\s\S]*?})\s*```", text)
    if m: return m.group(1)
    # 2) <json> ... </json>
    m = re.search(r"<json>([\s\S]*?)</json>", text)
    if m: return m.group(1)
    # 3) first balanced {...}
    depth, start = 0, None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                return text[start:i+1]
    return None

def call_llm_raw(
    prompt: str,
    *,
    n_predict: int = DEFAULT_N_PREDICT,
    temperature: float = DEFAULT_TEMPERATURE,
    tries: int = 2,
    timeout: float = DEFAULT_TIMEOUT,
) -> str:
    primary_url = f"{LLM_ENDPOINT.rstrip('/')}{LLM_ROUTE_PRIMARY}"
    fallback_url = f"{LLM_ENDPOINT.rstrip('/')}{LLM_ROUTE_FALLBACK}"

    payload_completion = {
        "prompt": prompt,
        "n_predict": n_predict,
        "temperature": temperature,
        "stream": False,
    }
    payload_chat = {
        "model": os.getenv("LLM_MODEL", "hermes3"),
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "stream": False,
    }

    last_err: Optional[Exception] = None
    for attempt in range(tries):
        # try /completion
        try:
            data = _post_json(primary_url, payload_completion, timeout=timeout)
            return data.get("content") or data.get("response") or ""
        except Exception as e:
            last_err = e
            # try OpenAI-style as fallback
            try:
                data = _post_json(fallback_url, payload_chat, timeout=timeout)
                choices = data.get("choices") or []
                if choices and "message" in choices[0]:
                    return choices[0]["message"].get("content", "")
            except Exception as e2:
                last_err = e2
                time.sleep(0.6)  # brief backoff before next attempt
    raise last_err if last_err else RuntimeError("LLM call failed")

def call_llm_json(system: str, user: str) -> Dict[str, Any]:
    """
    Compose a simple SYSTEM/USER prompt and return parsed JSON.
    Falls back to returning {"items": [], "_raw": ...} on parse failure.
    """
    prompt = (
        f"[SYSTEM]\n{system}\n\n"
        f"[USER]\n{user}\n\n"
        "Return ONLY a JSON object in ```json fences with shape {\"items\": [...] }."
    )
    out = call_llm_raw(prompt)
    block = extract_json_block(out) or out
    try:
        return json.loads(block)
    except Exception:
        return {"items": [], "_raw": out}