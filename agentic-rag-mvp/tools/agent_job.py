#!/usr/bin/env python3
"""
Minimal scheduled agent job for the librarian POC.
- Creates/uses a demo SQLite DB at data/agent.db
- Creates tables: students, audit_logs
- Runs a tiny planner to find students with 0 borrows in last 30 days and creates 'recommend_email' actions
- Inserts audit rows with status 'pending_approval'
"""

import os
import sqlite3
import json
from datetime import datetime, timedelta

# optional judge integration
try:
    from tools.llm_judge import judge_candidates
except Exception:
    judge_candidates = None

ROOT = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(ROOT, 'data')
DB_PATH = os.path.join(DATA_DIR, 'agent.db')

# Import the POC code to reuse recommendation logic
# we import by path relative to repo layout
try:
    # The script expects catalog, recommend_by_student etc to be importable
    from tools import run_gradio_poc as poc
except Exception:
    # Fallback: import by file execution
    import importlib.util
    spec = importlib.util.spec_from_file_location('run_gradio_poc', os.path.join(ROOT, 'tools', 'run_gradio_poc.py'))
    poc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(poc)

os.makedirs(DATA_DIR, exist_ok=True)

SCHEMA = '''
CREATE TABLE IF NOT EXISTS students (
    student_id TEXT PRIMARY KEY,
    last_30_days_borrows INTEGER DEFAULT 0,
    metadata TEXT
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT,
    student_id TEXT,
    action_type TEXT,
    payload TEXT,
    status TEXT,
    notes TEXT
);
'''


def init_db(path=DB_PATH):
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.executescript(SCHEMA)
    con.commit()
    return con


def seed_students(con):
    cur = con.cursor()
    # Minimal seed: get students from poc.borrow_history and mark last_30_days_borrows=0 for demo
    student_ids = set(poc.borrow_history['student_id'].tolist())
    for sid in student_ids:
        # Use 0 for demo; in a real system we'd compute from timestamps
        cur.execute('INSERT OR REPLACE INTO students(student_id, last_30_days_borrows, metadata) VALUES (?, ?, ?)',
                    (sid, 0, json.dumps({})))
    con.commit()


def plan_actions(con):
    cur = con.cursor()
    cur.execute('SELECT student_id, last_30_days_borrows FROM students')
    actions = []
    for sid, borrows in cur.fetchall():
        if borrows == 0:
            # Generate recommendations using the POC recommender (top 3)
            recs = poc.recommend_by_student(student_id=sid, query_text=None, top_k=3)
            payload = [{'book_id': int(bid), 'score': float(score)} for bid, score, row in recs]
            actions.append((sid, 'recommend_email', payload))
    return actions


def persist_actions(con, actions):
    cur = con.cursor()
    inserted_ids = []
    for sid, action_type, payload in actions:
        # If payload is a list of candidate books, insert one audit row per book
        if isinstance(payload, list):
            for item in payload:
                cur.execute('INSERT INTO audit_logs(created_at, student_id, action_type, payload, status, notes) VALUES (?, ?, ?, ?, ?, ?)',
                            (datetime.utcnow().isoformat(), sid, action_type, json.dumps(item), 'pending_approval', None))
                inserted_ids.append(cur.lastrowid)
        else:
            # single payload (dict/string/etc.)
            cur.execute('INSERT INTO audit_logs(created_at, student_id, action_type, payload, status, notes) VALUES (?, ?, ?, ?, ?, ?)',
                        (datetime.utcnow().isoformat(), sid, action_type, json.dumps(payload), 'pending_approval', None))
            inserted_ids.append(cur.lastrowid)
    con.commit()

    # If an LLM judge is available, run it on the newly inserted rows and persist logs
    if judge_candidates is not None and inserted_ids:
        # build candidate list with text extracted from payload
        cur.execute('SELECT id, payload FROM audit_logs WHERE id IN ({seq})'.format(seq=','.join('?'*len(inserted_ids))), inserted_ids)
        rows = cur.fetchall()
        candidates = []
        for rid, payload in rows:
            try:
                j = json.loads(payload)
            except Exception:
                j = payload
            # Build a short text for the judge: prefer 'title' or 'label' or dump payload
            try:
                if isinstance(j, dict):
                    txt = j.get('label') or j.get('title') or j.get('message') or j.get('text') or json.dumps(j)
                else:
                    txt = json.dumps(j)
            except Exception:
                txt = str(j)
            candidates.append({'audit_id': rid, 'text': txt})
        try:
            judge_candidates(candidates)
        except Exception:
            # avoid failing the agent job if judge fails
            pass

    # Optionally auto-approve based on judge score threshold (env var)
    try:
        import os
        thresh = float(os.environ.get('AUTO_APPROVE_THRESHOLD', '')) if os.environ.get('AUTO_APPROVE_THRESHOLD') else None
    except Exception:
        thresh = None
    if thresh is not None and inserted_ids:
        try:
            # For each inserted id, check latest judge score
            for rid in inserted_ids:
                cur.execute('SELECT score FROM judge_logs WHERE audit_id = ? ORDER BY created_at DESC LIMIT 1', (rid,))
                row = cur.fetchone()
                if not row:
                    continue
                score = float(row[0])
                if score >= thresh:
                    # append note indicating auto-approval
                    note = f"auto-approved (score={score})"
                    cur.execute('UPDATE audit_logs SET status = ?, notes = ? WHERE id = ?', ('approved', note, rid))
            con.commit()
        except Exception:
            # non-fatal
            pass

    return inserted_ids


def summarize(con):
    cur = con.cursor()
    cur.execute('SELECT COUNT(*) FROM audit_logs')
    total = cur.fetchone()[0]
    cur.execute('SELECT id, created_at, student_id, action_type, status FROM audit_logs ORDER BY id DESC LIMIT 10')
    rows = cur.fetchall()
    print(f'Inserted total audit rows: {total}')
    for r in rows:
        print(r)


if __name__ == '__main__':
    con = init_db()
    seed_students(con)
    actions = plan_actions(con)
    if actions:
        persist_actions(con, actions)
        print('Persisted', len(actions), 'actions to audit_logs (status=pending_approval)')
    else:
        print('No actions planned')
    summarize(con)
    con.close()
