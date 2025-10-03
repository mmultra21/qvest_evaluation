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
import time
import re

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
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS hermes_raw_responses (
            id INTEGER PRIMARY KEY,
            audit_id INTEGER,
            url TEXT,
            raw_body TEXT,
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


def _call_hermes_score(text: str, prompt: t.Optional[str] = None, audit_id: t.Optional[int] = None, db_path: str = DB_PATH_DEFAULT) -> t.Tuple[float, str]:
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
        # health-check first to avoid noisy failed calls
        try:
            health_url = HERMES_HTTP_URL.rstrip("/") + "/health"
            reqh = urllib.request.Request(health_url, method="GET")
            ctx = ssl.create_default_context()
            with urllib.request.urlopen(reqh, timeout=3, context=ctx) as rh:
                code = rh.getcode()
            if code != 200:
                raise RuntimeError(f"Hermes health check returned {code}")
        except Exception:
            # Hermes not healthy / not reachable
            raise RuntimeError("Hermes HTTP health check failed")

        # construct a minimal OpenAI-style completions request once
        # Prompt-tuning: require the model to emit the JSON on the FIRST line, then optionally explain.
        example_json = json.dumps({"score": 0.92, "reason": "example: suitable for middle graders"})
        # If the model cannot produce JSON, instruct it to return this exact fallback JSON so we always get parseable output
        fallback_json = json.dumps({"score": 0.0, "reason": "unable to produce JSON"})
        req_prompt = (
            (prompt or "")
            + "\n\n"
            + "FIRST LINE MUST BE a JSON object with keys 'score' (0.0-1.0) and 'reason' (short string). After that you may optionally write an explanation.\n"
            + "Example first line: "
            + example_json
            + "\nIf you cannot produce the requested JSON, the FIRST LINE must be exactly: "
            + fallback_json
            + "\nText:\n"
            + text
        )

        # Include a stop token to reduce trailing non-JSON text (Hermes3 may honor 'stop')
        payload = json.dumps(
            {
                "model": os.environ.get("HERMES3_MODEL") or "hermes3",
                "prompt": req_prompt,
                "max_tokens": 128,
                "temperature": 0.0,
                "stop": ["\n\n"]
            }
        ).encode("utf-8")

        headers = {"Content-Type": "application/json"}
        url = HERMES_HTTP_URL.rstrip("/") + "/v1/completions"

        # retry with exponential backoff for transient empty/garbled responses
        attempts = 3
        parsed_candidates: t.List[t.Tuple[float, str, str]] = []  # list of (score, reason, raw_body)
        last_body = None
        for attempt in range(attempts):
            try:
                req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=10, context=ssl.create_default_context()) as resp:
                    body = resp.read().decode("utf-8", errors="ignore")
                last_body = body

                # Try parsing strategies in order of confidence
                # 1) top-level JSON
                try:
                    parsed = json.loads(body)
                    # Hermes-like servers return {'choices': [{'text': '...'}], ...}
                    if isinstance(parsed, dict) and "choices" in parsed and parsed["choices"]:
                        txt = parsed["choices"][0].get("text", "")
                        # attempt to extract JSON inside txt
                        m = re.search(r"\{\s*\"score\".*?\}", txt, flags=re.S)
                        if m:
                            j = json.loads(m.group(0))
                            sc = float(j.get("score", 0.5))
                            reason = str(j.get("reason", ""))
                            parsed_candidates.append((sc, reason, txt))
                        else:
                            # fallback: numeric token in the text
                            m2 = re.search(r"([01](?:\.\d{1,4})?)", txt)
                            if m2:
                                sc = float(m2.group(1))
                                parsed_candidates.append((sc, txt[:400], txt))

                    # 2) search the whole body for a JSON object containing score
                    m = re.search(r"\{\s*\"score\".*?\}", body, flags=re.S)
                    if m:
                        try:
                            j = json.loads(m.group(0))
                            sc = float(j.get("score", 0.5))
                            reason = str(j.get("reason", ""))
                            parsed_candidates.append((sc, reason, body))
                        except Exception:
                            pass

                    # 3) find any numeric-looking token that looks like a score
                    m2 = re.search(r"([01](?:\.\d{1,4})?)", body)
                    if m2:
                        sc = float(m2.group(1))
                        parsed_candidates.append((sc, body[:400], body))

                except Exception:
                    # try looser regex-only extraction
                    m = re.search(r"\{\s*\"score\".*?\}", body, flags=re.S)
                    if m:
                        try:
                            j = json.loads(m.group(0))
                            sc = float(j.get("score", 0.5))
                            reason = str(j.get("reason", ""))
                            return sc, reason
                        except Exception:
                            pass
                    m2 = re.search(r"([01](?:\.\d{1,4})?)", body)
                    if m2:
                        sc = float(m2.group(1))
                        return sc, body[:400]

                # If we reached here, the response was not parseable for this attempt – treat as transient
                if attempt < attempts - 1:
                    time.sleep(0.8 * (2 ** attempt))
                    continue
                # last attempt fell through: we'll decide based on aggregated parsed_candidates below
                break
            except Exception:
                # retry on network or parse errors
                if attempt < attempts - 1:
                    time.sleep(0.8 * (2 ** attempt))
                    continue
                # give up after attempts
                break

        # After attempts, prefer the best non-zero parsed candidate (highest score). If none, but we have any parsed candidate, take the max.
        if parsed_candidates:
            # choose the candidate with highest score
            parsed_candidates.sort(key=lambda x: x[0], reverse=True)
            best = parsed_candidates[0]
            return float(best[0]), str(best[1])
        # If we have a last_body but couldn't parse anything, persist the raw response for diagnostics and then raise
        if last_body and audit_id:
            try:
                init_db(db_path)
                conn = sqlite3.connect(db_path)
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO hermes_raw_responses (audit_id, url, raw_body, created_at) VALUES (?,?,?,?)",
                    (audit_id, url, last_body[:20000], datetime.datetime.utcnow().isoformat() + "Z"),
                )
                conn.commit()
                conn.close()
            except Exception:
                # don't let debug persistence break the main flow
                pass

    raise RuntimeError("Hermes returned unparseable response after retries")


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
            score, reason = _call_hermes_score(text, prompt=prompt, audit_id=aid, db_path=db_path)
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
