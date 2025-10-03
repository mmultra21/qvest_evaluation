#!/usr/bin/env python3
"""
List tables in a SQLite database and show row counts.
Usage: python sqlite_list_tables.py [path/to/db]
"""
import sqlite3
import sys
import os


def list_tables(db_path):
    if not os.path.exists(db_path):
        print('DB not found at', db_path)
        return
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;")
    tables = [r[0] for r in cur.fetchall()]
    if not tables:
        print('No user tables found in', db_path)
        return
    print('Tables in', db_path)
    for t in tables:
        try:
            cur.execute(f'SELECT count(*) FROM {t}')
            cnt = cur.fetchone()[0]
        except Exception as e:
            cnt = f'error: {e}'
        print(f'- {t}: {cnt} rows')
    con.close()


if __name__ == '__main__':
    # Resolve default DB relative to this script file so the script works regardless of cwd
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..'))  # points to agentic-rag-mvp
    default_db = os.path.join(REPO_ROOT, 'data', 'agent.db')
    db = sys.argv[1] if len(sys.argv) > 1 else default_db
    list_tables(db)
