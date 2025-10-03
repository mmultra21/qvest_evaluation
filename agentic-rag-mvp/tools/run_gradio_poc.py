#!/usr/bin/env python3
"""Student-facing Gradio POC for the Librarian demo.

This file is a lightweight, demo-safe student UI that shows weekly
recommendations (derived from the existing recommender POC) and exposes a
mock student login + request form. It's guarded so importing the module
does not start a server.

Features:
- Mock student login (Student ID)
- Weekly Recommendations view (uses recommend_by_student)
- Request / Log Finished Book form (optionally persists to data/agent.db as an audit_logs row)
- Optional guarded integration with the RAG / Qdrant helpers if available

Launch: python agentic-rag-mvp/tools/run_gradio_poc.py [port]
"""

from __future__ import annotations

import json
import os
import sys
import re
from collections import Counter
from datetime import datetime
from typing import Any

try:
    import pandas as pd
    import numpy as np
except Exception as e:
    raise ImportError("Please install pandas and numpy to run the POC: pip install pandas numpy") from e

# --- Minimal synthetic catalog and history (fallback) ----------------------------------
catalog = pd.DataFrame([
    {"book_id": 1, "title": "The Great Adventure", "author": "A. Author", "description": "An epic journey through mountains and rivers."},
    {"book_id": 2, "title": "Mystery of the Old House", "author": "B. Writer", "description": "A thrilling mystery set in an abandoned house."},
    {"book_id": 3, "title": "Science for Kids", "author": "C. Scientist", "description": "Fun experiments and facts for young scientists."},
    {"book_id": 4, "title": "History of Space", "author": "D. Historian", "description": "A look at the history of space exploration."},
    {"book_id": 5, "title": "Coding for Kids", "author": "E. Dev", "description": "Intro to programming concepts with fun projects."},
])

borrow_history = pd.DataFrame([
    {"student_id": "S1", "book_id": 1, "ts": "2024-03-01"},
    {"student_id": "S1", "book_id": 4, "ts": "2024-03-15"},
    {"student_id": "S2", "book_id": 2, "ts": "2024-02-05"},
    {"student_id": "S2", "book_id": 4, "ts": "2024-02-20"},
    {"student_id": "S3", "book_id": 3, "ts": "2024-01-10"},
    {"student_id": "S3", "book_id": 2, "ts": "2024-02-10"},
])

catalog['text'] = catalog['title'] + ' - ' + catalog['description']
book_index = {r['book_id']: i for i, r in enumerate(catalog.to_dict('records'))}

# --- tokenizer + TF-IDF fallback ------------------------------------------------------
import math

def tokenize(text: str):
    text = (text or '').lower()
    return [t for t in re.findall(r"\w+", text) if len(t) > 1]

def build_tfidf(docs):
    N = len(docs)
    tokens = [tokenize(d) for d in docs]
    df = {}
    for tks in tokens:
        for t in set(tks):
            df[t] = df.get(t, 0) + 1
    vocab = sorted(df.keys())
    idx = {t:i for i,t in enumerate(vocab)}
    idf = np.array([math.log(1 + N / (1 + df[t])) for t in vocab]) if vocab else np.array([])
    vectors = np.zeros((N, len(vocab)), dtype=float)
    for i, tks in enumerate(tokens):
        tf = {}
        for t in tks:
            tf[t] = tf.get(t, 0) + 1
        max_tf = max(tf.values()) if tf else 1
        for t, c in tf.items():
            vectors[i, idx[t]] = (c / max_tf) * idf[idx[t]]
    return vectors, vocab

tfidf, vocab = build_tfidf(catalog['text'].tolist())

# build student vectors from train split
borrow_history['ts'] = pd.to_datetime(borrow_history['ts'])
train_rows = []
for sid, group in borrow_history.groupby('student_id'):
    rows = group.sort_values('ts')
    if len(rows) >= 2:
        for r in rows.iloc[:-1].to_dict('records'):
            train_rows.append(r)
    else:
        for r in rows.to_dict('records'):
            train_rows.append(r)

train = pd.DataFrame(train_rows) if train_rows else pd.DataFrame(columns=['student_id','book_id','ts'])
student_vecs = {}
for sid, g in train.groupby('student_id'):
    idxs = [book_index[b] for b in g['book_id'] if b in book_index]
    if not idxs:
        continue
    vecs = tfidf[idxs]
    avg = np.asarray(vecs.mean(axis=0)).ravel()
    student_vecs[sid] = avg

# optional embeddings + faiss (guarded)
use_embeddings = False
try:
    from sentence_transformers import SentenceTransformer
    import faiss
    model = SentenceTransformer('all-MiniLM-L6-v2')
    embeddings = model.encode(catalog['text'].tolist(), convert_to_numpy=True)
    faiss.normalize_L2(embeddings)
    dim = embeddings.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(embeddings)
    use_embeddings = True
    print('Embedding index built with', index.ntotal, 'items')
except Exception:
    use_embeddings = False

import numpy as np

def cosine_sim(a, B):
    a_norm = np.linalg.norm(a)
    if a_norm == 0:
        return np.zeros(B.shape[0])
    b_norms = np.linalg.norm(B, axis=1)
    dots = B.dot(a)
    denom = a_norm * b_norms
    sim = np.zeros_like(dots)
    nz = denom > 0
    sim[nz] = dots[nz] / denom[nz]
    return sim


def _fetch_db_approved_recs(student_id: str, top_k: int = 5, db_path: str | None = None):
    """Return approved recommend_email rows from audit_logs for a student as (book_id, score, row).
    This mirrors the UI behavior and preserves order (most recent first) and dedupes by book_id.
    """
    try:
        import sqlite3
        ROOT = os.path.dirname(os.path.dirname(__file__))
        DB_PATH = os.path.join(ROOT, 'data', 'agent.db') if db_path is None else db_path
        if not os.path.exists(DB_PATH):
            return []
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute("SELECT id, payload FROM audit_logs WHERE student_id = ? AND action_type = 'recommend_email' AND status = 'approved' ORDER BY id DESC LIMIT ?", (student_id, top_k))
        rows = cur.fetchall()
        recs = []
        for _, payload in rows:
            try:
                j = json.loads(payload)
                if isinstance(j, dict) and 'book_id' in j:
                    bid = int(j['book_id'])
                    if bid in book_index:
                        row = catalog.iloc[book_index[bid]]
                        recs.append((bid, float(j.get('score', 0.0)), row))
            except Exception:
                continue
        con.close()
        # dedupe while preserving order
        if recs:
            seen_bids = set()
            dedup = []
            for bid, score, row in recs:
                if bid in seen_bids:
                    continue
                seen_bids.add(bid)
                dedup.append((bid, score, row))
            return dedup
        return []
    except Exception:
        return []

def recommend_by_student(student_id=None, query_text=None, top_k=5, use_semantic: bool = False, prefer_db_recs: bool = False):
    # embeddings path
    # Only use embeddings if the environment built them AND caller opted in via use_semantic
    if use_embeddings and use_semantic:
        try:
            if student_id and student_id in student_vecs:
                seen = train[train['student_id'] == student_id]['book_id'].tolist()
                seen_idxs = [book_index[b] for b in seen if b in book_index]
                if seen_idxs:
                    student_emb = embeddings[seen_idxs].mean(axis=0)
                    student_emb = student_emb / np.linalg.norm(student_emb)
                else:
                    student_emb = None
            else:
                student_emb = None
            if query_text and not student_emb:
                q_emb = model.encode([query_text], convert_to_numpy=True)
                faiss.normalize_L2(q_emb)
                D, I = index.search(q_emb, top_k)
                results = [(int(catalog.iloc[i]['book_id']), float(D[0,j]), catalog.iloc[i]) for j,i in enumerate(I[0])]
                return results
            if student_emb is not None:
                q = student_emb.reshape(1, -1)
                faiss.normalize_L2(q)
                D, I = index.search(q, top_k)
                results = [(int(catalog.iloc[i]['book_id']), float(D[0,j]), catalog.iloc[i]) for j,i in enumerate(I[0])]
                return results
        except Exception:
            pass

    # Optionally prefer DB-approved recommend_email rows (keeps parity with UI)
    if student_id and prefer_db_recs:
        db_recs = _fetch_db_approved_recs(student_id, top_k=top_k)
        if db_recs:
            return db_recs[:top_k]

    # fallback TF-IDF
    if student_id:
        recs = []
        if student_id in student_vecs:
            sims = cosine_sim(student_vecs[student_id], tfidf)
            seen = set(train[train['student_id'] == student_id]['book_id'].tolist())
            for i, bid in enumerate(catalog['book_id']):
                if bid in seen:
                    continue
                recs.append((int(bid), float(sims[i]), catalog.iloc[i]))
            recs.sort(key=lambda x: x[1], reverse=True)
            return recs[:top_k]
        return []
    if query_text:
        q_toks = tokenize(query_text)
        c = Counter(q_toks)
        q_vec = np.zeros((tfidf.shape[1],), dtype=float)
        max_tf = max(c.values()) if c else 1
        for t, cnt in c.items():
            if t in vocab:
                idx = vocab.index(t)
                q_vec[idx] = (cnt / max_tf)
        sims = cosine_sim(q_vec, tfidf)
        idxs = np.argsort(sims)[::-1][:top_k]
        return [(int(catalog.iloc[i]['book_id']), float(sims[i]), catalog.iloc[i]) for i in idxs]
    return []

def generate_blurb(row: Any) -> str:
    return f"A great pick: {row['title']} — {row['description'][:140]}..."


# --- DB write helper (opt-in) ---------------------------------------------------------
def persist_audit_row(student_id: str, action_type: str, payload: dict, db_path: str | None = None) -> int | None:
    """Persist a single audit_logs row into data/agent.db. Returns inserted id or None on failure."""
    try:
        import sqlite3
        ROOT = os.path.dirname(os.path.dirname(__file__))
        DATA_DIR = os.path.join(ROOT, 'data')
        DB_PATH = os.path.join(DATA_DIR, 'agent.db') if db_path is None else db_path
        os.makedirs(DATA_DIR, exist_ok=True)
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.executescript('''
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT,
            student_id TEXT,
            action_type TEXT,
            payload TEXT,
            status TEXT,
            notes TEXT
        );
        CREATE TABLE IF NOT EXISTS students (
            student_id TEXT PRIMARY KEY,
            last_30_days_borrows INTEGER DEFAULT 0,
            metadata TEXT
        );
        ''')
        cur.execute('INSERT INTO audit_logs(created_at, student_id, action_type, payload, status, notes) VALUES (?, ?, ?, ?, ?, ?)',
                    (datetime.utcnow().isoformat(), student_id, action_type, json.dumps(payload), 'pending_approval', None))
        inserted_id = cur.lastrowid
        con.commit()
        con.close()
        return int(inserted_id)
    except Exception as e:
        print('Warning: could not persist audit row:', e)
        return None


# --- Gradio UI builder (guarded) ------------------------------------------------------
def create_gradio_interface(port: int | None = None):
    try:
        import gradio as gr

        # UI callbacks
        def ui_weekly_recs(student_id: str, use_semantic: bool = False):
            student_id = (student_id or '').strip() or None
            # Prefer approved recommendations from the shared audit_logs DB if present
            recs = []
            try:
                import sqlite3
                ROOT = os.path.dirname(os.path.dirname(__file__))
                DB_PATH = os.path.join(ROOT, 'data', 'agent.db')
                if os.path.exists(DB_PATH) and student_id:
                    con = sqlite3.connect(DB_PATH)
                    cur = con.cursor()
                    # payload may be JSON with book_id/score; select recent approved recommendations for this student
                    cur.execute("SELECT id, payload FROM audit_logs WHERE student_id = ? AND action_type = 'recommend_email' AND status = 'approved' ORDER BY id DESC LIMIT 10", (student_id,))
                    rows = cur.fetchall()
                    for _, payload in rows:
                        try:
                            j = json.loads(payload)
                            if isinstance(j, dict) and 'book_id' in j:
                                bid = int(j['book_id'])
                                # find catalog row
                                if bid in book_index:
                                    row = catalog.iloc[book_index[bid]]
                                    recs.append((bid, float(j.get('score', 0.0)), row))
                        except Exception:
                            continue
                    con.close()
                    # Deduplicate DB-sourced recommendations by book_id while preserving order
                    if recs:
                        seen_bids = set()
                        deduped = []
                        for bid, score, row in recs:
                            if bid in seen_bids:
                                continue
                            seen_bids.add(bid)
                            deduped.append((bid, score, row))
                        recs = deduped
            except Exception:
                # fallback to recommender if DB path or query fails
                recs = []

            if not recs:
                recs = recommend_by_student(student_id=student_id, query_text=None, top_k=5, use_semantic=bool(use_semantic))
            out = []
            for bid, score, row in recs:
                out.append({'book_id': bid, 'title': row['title'], 'score': round(score, 3), 'blurb': generate_blurb(row)})
            return out

        def ui_request_book(student_id: str, book_id: str, log_to_db: bool):
            sid = (student_id or '').strip() or 'anon'
            try:
                bid = int(book_id)
            except Exception:
                return {'ok': False, 'msg': 'Invalid book id'}
            payload = {'student_id': sid, 'book_id': bid, 'requested_at': datetime.utcnow().isoformat(), 'source': 'student_poc'}
            inserted = None
            if log_to_db:
                inserted = persist_audit_row(sid, 'request_book', payload)
            msg = f'Requested book {bid}.' + (f' (persisted id={inserted})' if inserted else '')
            return {'ok': True, 'msg': msg}

        def ui_log_finished(student_id: str, book_id: str, grade: str, log_to_db: bool):
            sid = (student_id or '').strip() or 'anon'
            try:
                bid = int(book_id)
            except Exception:
                return {'ok': False, 'msg': 'Invalid book id'}
            payload = {'student_id': sid, 'book_id': bid, 'grade': grade or None, 'finished_at': datetime.utcnow().isoformat(), 'source': 'student_poc'}
            inserted = None
            if log_to_db:
                inserted = persist_audit_row(sid, 'finished_book', payload)
            msg = f'Logged finished book {bid}.' + (f' (persisted id={inserted})' if inserted else '')
            return {'ok': True, 'msg': msg}

        # Build UI
        with gr.Blocks(title='Student Library POC (mock)') as demo:
            gr.Markdown('## Mock Student Login')
            with gr.Row():
                sid = gr.Textbox(label='Student ID', value='S1')
                semantic_chk = gr.Checkbox(label='Use semantic embeddings (opt-in)', value=False)
                refresh_btn = gr.Button('Refresh Weekly Recs')

            gr.Markdown('## This Week\'s Recommendations')
            recs = gr.JSON(label='Weekly Recommendations')
            refresh_btn.click(fn=ui_weekly_recs, inputs=[sid, semantic_chk], outputs=[recs])

            gr.Markdown('## Request a Book')
            with gr.Row():
                req_book = gr.Textbox(label='Book ID (numeric)')
                req_log = gr.Checkbox(label='Persist request to audit_logs (opt-in)', value=False)
                req_btn = gr.Button('Request Book')
            req_out = gr.JSON(label='Request Result')
            req_btn.click(fn=ui_request_book, inputs=[sid, req_book, req_log], outputs=[req_out])

            gr.Markdown('## Log a Finished Book')
            with gr.Row():
                fin_book = gr.Textbox(label='Book ID (numeric)')
                fin_grade = gr.Textbox(label='Grade (optional)')
                fin_log = gr.Checkbox(label='Persist finished book to audit_logs (opt-in)', value=False)
                fin_btn = gr.Button('Log Finished Book')
            fin_out = gr.JSON(label='Finished Result')
            fin_btn.click(fn=ui_log_finished, inputs=[sid, fin_book, fin_grade, fin_log], outputs=[fin_out])

        # Determine port
        env_port = os.environ.get('GRADIO_SERVER_PORT') or os.environ.get('PORT')
        arg_port = None
        if len(sys.argv) > 1:
            try:
                arg_port = int(sys.argv[1])
            except Exception:
                arg_port = None
        chosen_port = int(arg_port or env_port or port or 7883)
        print(f'Starting Student POC on http://127.0.0.1:{chosen_port}')
        demo.launch(server_name='127.0.0.1', server_port=chosen_port, share=False, prevent_thread_lock=False)
    except Exception as e:
        print('Gradio is not available or failed to start:', e)
        raise


if __name__ == '__main__':
    try:
        create_gradio_interface()
    except Exception:
        sys.exit(1)
