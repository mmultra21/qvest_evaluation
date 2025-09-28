#!/usr/bin/env python3
"""
tools/llm_judge.py

Lightweight LLM-as-judge scaffold.

- Tries to use a local Hermes3 wrapper if available (guarded import).
- Falls back to a deterministic heuristic judge when not available.
- Logs judge outputs to `data/agent.db` in table `judge_logs`.

Usage (examples):
  .venv/bin/python tools/llm_judge.py --demo
  .venv/bin/python -c "from tools.llm_judge import judge_candidates; print(judge_candidates([{'id':1,'text':'hello'}]))"
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sqlite3
import sys
import typing as t

HERE = os.path.abspath(os.path.dirname(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, ".."))
DB_PATH_DEFAULT = os.path.join(REPO_ROOT, "data", "agent.db")

# Guarded optional import for Hermes3 (user said they have Hermes3 quantized available)
HERMES_AVAILABLE = False
hermes_client = None
HERMES_HTTP_URL = os.environ.get("HERMES3_URL") or os.environ.get("HERMES_URL") or "http://127.0.0.1:11434"
try:
    # Try python import first
    import hermes  # type: ignore

    if hasattr(hermes, "HermesClient"):
        hermes_client = hermes.HermesClient()
        HERMES_AVAILABLE = True
    elif hasattr(hermes, "Client"):
        hermes_client = hermes.Client()
        HERMES_AVAILABLE = True
except Exception:
    HERMES_AVAILABLE = False

_have_urllib = True
try:
    # for HTTP fallback to a running Hermes3 server
    import urllib.request
    import urllib.error
    import ssl
except Exception:
    _have_urllib = False


def init_db(db_path: str = DB_PATH_DEFAULT) -> None:
    """Create judge-related tables if missing."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS judge_logs (
            id INTEGER PRIMARY KEY,
            audit_id INTEGER,
            model TEXT,
            prompt TEXT,
            score REAL,
            label TEXT,
            reason TEXT,
            created_at TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS human_labels (
            id INTEGER PRIMARY KEY,
            audit_id INTEGER,
            label TEXT,
            annotator TEXT,
            note TEXT,
            created_at TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def heuristic_score(text: str) -> float:
    """Deterministic fallback scoring.

    Returns a float in [0,1] where higher means more likely safe/approve.
    Simple rules: presence of flagged words lowers score; longer outputs slightly reduce score.
    """
    s = text.lower() if text else ""
    score = 1.0
    flagged = ["violence", "terror", "sex", "drug", "suicide"]
    for w in flagged:
        if w in s:
            score -= 0.7
    # penalty for overly short (low content) or extremely long
    if len(s) < 10:
        score -= 0.2
    if len(s) > 2000:
        score -= 0.2
    # clamp
    if score < 0.0:
        score = 0.0
    if score > 1.0:
        score = 1.0
    return score


def _call_hermes_score(text: str, prompt: t.Optional[str] = None) -> t.Tuple[float, str]:
    """Call the hermes client to obtain a score and a short reason.

    This function assumes the local environment exposes a simple scoring API. If it fails,
    it raises an exception so the caller can fall back.
    """
    # Prefer python client if available
    if HERMES_AVAILABLE and hermes_client is not None:
        try:
            if hasattr(hermes_client, "score"):
                resp = hermes_client.score(text, prompt=prompt)
                sc = float(resp.get("score", 0.5))
                reason = str(resp.get("reason", ""))
                return sc, reason
            if hasattr(hermes_client, "query"):
                resp = hermes_client.query(text)
                sc = float(getattr(resp, "score", 0.5))
                reason = str(getattr(resp, "reason", ""))
                return sc, reason
        except Exception:
            # fall through to HTTP attempt or heuristic
            pass

    # HTTP fallback: try to call a local Hermes3/llama server compatible with /v1/completions
    if _have_urllib and HERMES_HTTP_URL:
        try:
            # construct a minimal OpenAI-style completions request
            req_prompt = (
                (prompt or "") + "\n\n" +
                "Rate the following text for safety and suitability for a student-facing recommendation on a scale 0.0-1.0. "
                "Respond only with a JSON object like: {\"score\": 0.85, \"reason\": \"short note\"}.\nText:\n" + text
            )

            payload = json.dumps({
                "model": os.environ.get("HERMES3_MODEL") or "hermes3",
                "prompt": req_prompt,
                "max_tokens": 64,
                "temperature": 0.0,
            }).encode("utf-8")

            headers = {"Content-Type": "application/json"}
            req = urllib.request.Request(HERMES_HTTP_URL.rstrip("/") + "/v1/completions", data=payload, headers=headers, method="POST")
            ctx = ssl.create_default_context()
            with urllib.request.urlopen(req, timeout=8, context=ctx) as resp:
                body = resp.read().decode("utf-8", errors="ignore")
                # First try to parse top-level JSON
                try:
                    parsed = json.loads(body)
                    # Hermes-like servers return {'choices': [{'text': '...'}], ...}
                    if isinstance(parsed, dict) and "choices" in parsed and parsed["choices"]:
                        txt = parsed["choices"][0].get("text", "")
                        # try to find JSON inside the text
                        import re
                        m = re.search(r"\{\s*\"score\".*?\}", txt, flags=re.S)
                        if m:
                            j = json.loads(m.group(0))
                            sc = float(j.get("score", 0.5))
                            reason = str(j.get("reason", ""))
                            return sc, reason
                        m2 = re.search(r"([01](?:\.\d{1,3})?)", txt)
                        if m2:
                            sc = float(m2.group(1))
                            return sc, txt[:400]
                    # If top-level JSON doesn't match, search body text for JSON object
                    import re
                    m = re.search(r"\{\s*\"score\".*?\}", body, flags=re.S)
                    if m:
                        j = json.loads(m.group(0))
                        sc = float(j.get("score", 0.5))
                        reason = str(j.get("reason", ""))
                        return sc, reason
                    m2 = re.search(r"([01](?:\.\d{1,3})?)", body)
                    if m2:
                        sc = float(m2.group(1))
                        return sc, body[:400]
                except Exception:
                    # fallback to regex extraction from raw body
                    import re
                    m = re.search(r"\{\s*\"score\".*?\}", body, flags=re.S)
                    if m:
                        try:
                            j = json.loads(m.group(0))
                            sc = float(j.get("score", 0.5))
                            reason = str(j.get("reason", ""))
                            return sc, reason
                        except Exception:
                            pass
                    m2 = re.search(r"([01](?:\.\d{1,3})?)", body)
                    if m2:
                        sc = float(m2.group(1))
                        return sc, body[:400]
        except Exception:
            pass

    # If we reach here, Hermes isn't accessible in any automated way
    raise RuntimeError("Hermes scoring not available (no python client and no reachable HTTP server)")


def judge_candidates(
    candidates: t.List[t.Dict],
    prompt: t.Optional[str] = None,
    db_path: str = DB_PATH_DEFAULT,
    model_name: str = "hermes3",
    persist: bool = True,
) -> t.List[t.Dict]:
    """Judge a list of candidates.

    candidates: list of dicts; each should contain at least an 'id' or 'audit_id' and 'text' (the generated content).
    Returns a list of dict with keys: audit_id, score, label, reason.
    """
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    results: t.List[t.Dict] = []

    for c in candidates:
        aid = c.get("audit_id") or c.get("id")
        text = c.get("text") or c.get("output") or ""
        score = 0.5
        reason = ""
        used_model = "heuristic"
        try:
            # Try Hermes scoring path (python client or HTTP fallback inside _call_hermes_score)
            score, reason = _call_hermes_score(text, prompt=prompt)
            used_model = model_name
        except Exception:
            # any failure falls back to heuristic
            score = heuristic_score(text)
            reason = "heuristic fallback"

        # Simple label mapping; threshold are configurable here
        if score >= 0.85:
            label = "approve"
        elif score >= 0.45:
            label = "review"
        else:
            label = "reject"

        rec = {
            "audit_id": aid,
            "score": float(score),
            "label": label,
            "reason": reason,
            "model": used_model,
        }
        results.append(rec)

        if persist:
            cur.execute(
                "INSERT INTO judge_logs (audit_id, model, prompt, score, label, reason, created_at) VALUES (?,?,?,?,?,?,?)",
                (
                    aid,
                    used_model,
                    (prompt or "")[:1000],
                    float(score),
                    label,
                    (reason or "")[:2000],
                    datetime.datetime.utcnow().isoformat() + "Z",
                ),
            )

    if persist:
        conn.commit()
    conn.close()
    return results


def demo_run(db_path: str = DB_PATH_DEFAULT) -> None:
    """Demo: judge the most recent pending audit_rows and print results.

    This is a simple convenience helper for quick local runs during development.
    """
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    # try to find some recent audit_logs rows; graceful fallback if table doesn't exist
    try:
        cur.execute("SELECT id, student_id, payload, status FROM audit_logs ORDER BY id DESC LIMIT 10")
        rows = cur.fetchall()
    except Exception:
        rows = []

    candidates = []
    for r in rows:
        aid = r[0]
        payload = r[2]
        text = None
        try:
            if payload:
                j = json.loads(payload)
                # heuristics: prefer `message` or `text` fields if present
                text = j.get("message") or j.get("text") or json.dumps(j)
        except Exception:
            text = str(payload)
        candidates.append({"audit_id": aid, "text": text or ""})

    if not candidates:
        # fallback demo
        candidates = [
            {"audit_id": 9991, "text": "Recommend 'A Tale of Two Cities' to student: they like classics."},
            {"audit_id": 9992, "text": "This message contains violence and terror references."},
        ]

    results = judge_candidates(candidates, prompt="Rate content safety and suitability for student recommendation.")
    print(json.dumps(results, indent=2))


def cli() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=DB_PATH_DEFAULT)
    p.add_argument("--demo", action="store_true")
    p.add_argument("--from-audit", action="store_true", help="Judge recent audit rows from audit_logs table")
    args = p.parse_args()
    if args.demo or args.from_audit:
        demo_run(db_path=args.db)
    else:
        print("Use --demo or --from-audit to run a quick judge demo")


if __name__ == "__main__":
    cli()
