#!/usr/bin/env python3
"""
Idempotent executor for demo: safely consumes audit rows with status='approved',
claims them (approved->in_progress) to avoid double-processing, executes known
actions (simulated), and marks rows 'executed' or 'failed' with timestamped notes.

Usage: python tools/executor.py [--batch N] [--dry-run] [--worker NAME]
"""

import os
import sqlite3
import json
import argparse
from datetime import datetime
from typing import Optional

ROOT = os.path.dirname(os.path.dirname(__file__))
DB_PATH = os.path.join(ROOT, 'data', 'agent.db')


def now_iso():
    return datetime.utcnow().isoformat()


def fetch_candidate_ids(con, batch: int = 10):
    cur = con.cursor()
    cur.execute("SELECT id FROM audit_logs WHERE status='approved' ORDER BY id LIMIT ?", (batch,))
    return [row[0] for row in cur.fetchall()]


def claim_row(con, row_id: int, worker: str) -> bool:
    """Try to atomically claim a row by switching status from 'approved' -> 'in_progress'.
    Returns True if claim succeeded, False if the row was already claimed/changed.
    """
    cur = con.cursor()
    claim_note = f"[claimed:{worker}:{now_iso()}] "
    cur.execute("UPDATE audit_logs SET status=?, notes = COALESCE(notes, '') || ? WHERE id=? AND status='approved'",
                ('in_progress', claim_note, row_id))
    con.commit()
    return cur.rowcount == 1


def fetch_row(con, row_id: int):
    cur = con.cursor()
    cur.execute("SELECT id, created_at, student_id, action_type, payload FROM audit_logs WHERE id=?", (row_id,))
    return cur.fetchone()


def complete_row(con, row_id: int, status: str, note: Optional[str] = None):
    cur = con.cursor()
    ts_note = f"[{now_iso()}] " + (note or '')
    # Append to existing notes while updating status
    cur.execute("UPDATE audit_logs SET status=?, notes = COALESCE(notes, '') || ? WHERE id=?", (status, ts_note, row_id))
    con.commit()


def execute_recommend_email(row):
    # row: (id, created_at, student_id, action_type, payload)
    _id, _created_at, student_id, action_type, payload = row
    try:
        pl = json.loads(payload)
    except Exception:
        pl = payload
    # Simulate sending an email: create a human-friendly summary of recommendations
    if isinstance(pl, list):
        books = ', '.join(str(item.get('book_id')) for item in pl[:3])
        note = f"Sent recommendation to {student_id}: books={books}"
    else:
        note = f"Sent recommendation to {student_id}: payload={pl}"
    return True, note


def process_row(con, row_id: int, worker: str, dry_run: bool = False):
    # Try to claim the row first
    claimed = claim_row(con, row_id, worker)
    if not claimed:
        print(f'Skipping {row_id}: could not claim (likely processed by another worker)')
        return

    row = fetch_row(con, row_id)
    if not row:
        print(f'Row {row_id} disappeared after claim; skipping')
        return

    _id, created_at, student_id, action_type, payload = row
    print(f'Worker {worker} processing row {row_id} action={action_type} student={student_id}')

    try:
        if action_type == 'recommend_email':
            if dry_run:
                note = f"DRY-RUN: would send recommendation to {student_id}"
                print(note)
                # Revert status back to approved so real run can pick it up later
                complete_row(con, row_id, 'approved', f'DRY-RUN by {worker}; no action taken')
                return
            ok, note = execute_recommend_email(row)
            if ok:
                complete_row(con, row_id, 'executed', note)
                print(f'Executed {row_id}: {note}')
            else:
                complete_row(con, row_id, 'failed', note)
                print(f'Failed {row_id}: {note}')
        else:
            complete_row(con, row_id, 'failed', f'Unknown action_type: {action_type}')
            print(f'Failed {row_id}: unknown action_type')
    except Exception as e:
        complete_row(con, row_id, 'failed', f'Exception: {e}')
        print(f'Exception while executing {row_id}: {e}')


def run_once(batch: int = 10, dry_run: bool = False, worker: str = 'executor'):
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    candidates = fetch_candidate_ids(con, batch=batch)
    if not candidates:
        print('No approved rows to execute')
        con.close()
        return

    for rid in candidates:
        process_row(con, rid, worker, dry_run=dry_run)

    con.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--batch', type=int, default=10, help='Max number of approved rows to claim and process')
    p.add_argument('--dry-run', action='store_true', help='Do not perform actions; revert claimed rows to approved')
    p.add_argument('--worker', type=str, default=f'pid:{os.getpid()}', help='Worker identifier to record in notes')
    args = p.parse_args()
    run_once(batch=args.batch, dry_run=args.dry_run, worker=args.worker)


if __name__ == '__main__':
    main()
