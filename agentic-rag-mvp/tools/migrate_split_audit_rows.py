#!/usr/bin/env python3
"""
Migration helper: split audit_logs rows whose payload is a JSON list into one audit_logs row per item.

Usage: python tools/migrate_split_audit_rows.py

This script is safe to run multiple times: rows already marked with status='split' are skipped.
It marks the original grouped row with status='split' and a note indicating how many child rows were created.
"""

import os
import sqlite3
import json
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(__file__))
DB_PATH = os.path.join(ROOT, 'data', 'agent.db')


def split_grouped_rows(db_path=DB_PATH):
    if not os.path.exists(db_path):
        print('DB not found at', db_path)
        return
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    # Ensure mapping table exists
    cur.executescript('''
    CREATE TABLE IF NOT EXISTS audit_row_splits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        parent_id INTEGER,
        child_id INTEGER,
        created_at TEXT
    );
    ''')

    cur.execute("SELECT id, created_at, student_id, action_type, payload, status, notes FROM audit_logs WHERE status != 'split' ORDER BY id")
    rows = cur.fetchall()
    grouped = []
    for r in rows:
        aid, created_at, student_id, action_type, payload, status, notes = r
        try:
            parsed = json.loads(payload)
        except Exception:
            parsed = None
        if isinstance(parsed, list):
            grouped.append((aid, created_at, student_id, action_type, parsed, status, notes))

    if not grouped:
        print('No grouped/list payload rows found to split.')
        con.close()
        return

    print(f'Found {len(grouped)} grouped rows to split...')
    for aid, created_at, student_id, action_type, items, status, notes in grouped:
        child_ids = []
        for item in items:
            try:
                item_json = json.dumps(item, ensure_ascii=False)
            except Exception:
                item_json = json.dumps(str(item))
            cur.execute('INSERT INTO audit_logs(created_at, student_id, action_type, payload, status, notes) VALUES (?, ?, ?, ?, ?, ?)',
                        (created_at or datetime.utcnow().isoformat(), student_id, action_type, item_json, 'pending_approval', None))
            child_ids.append(cur.lastrowid)
        # persist parent->child mappings (keep original row untouched for traceability)
        for cid in child_ids:
            cur.execute('INSERT INTO audit_row_splits(parent_id, child_id, created_at) VALUES (?,?,?)', (aid, cid, datetime.utcnow().isoformat()))
        # optionally append a note to the original row without changing status
        note = (notes or '') + f' [split into {len(child_ids)} rows: {child_ids}]'
        cur.execute("UPDATE audit_logs SET notes = ? WHERE id = ?", (note, aid))
        con.commit()
        print(f'Row {aid} split into {len(child_ids)} rows: {child_ids} (mappings saved)')

    con.close()


if __name__ == '__main__':
    split_grouped_rows()
