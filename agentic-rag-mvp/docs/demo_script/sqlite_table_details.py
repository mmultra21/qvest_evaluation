#!/usr/bin/env python3
"""
Show schema and sample rows for a given table in a SQLite DB.
Usage: python sqlite_table_details.py [path/to/db] [table] [sample_size]
"""
import sqlite3
import sys
import os


def table_details(db_path, table, sample_size=5):
    if not os.path.exists(db_path):
        print('DB not found at', db_path)
        return
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    # schema
    try:
        cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,))
        row = cur.fetchone()
        if not row:
            print('Table not found:', table)
            return
        print('Schema for', table, ':')
        print(row[0])
    except Exception as e:
        print('Error fetching schema:', e)
        return
    # sample rows
    try:
        cur.execute(f"SELECT * FROM {table} LIMIT ?", (sample_size,))
        rows = cur.fetchall()
        print('\nSample rows:')
        for r in rows:
            print(r)
    except Exception as e:
        print('Error fetching sample rows:', e)
    con.close()

if __name__ == '__main__':
    # Resolve default DB relative to this script file so the script works regardless of cwd
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..'))  # points to agentic-rag-mvp
    default_db = os.path.join(REPO_ROOT, 'data', 'agent.db')
    db = sys.argv[1] if len(sys.argv) > 1 else default_db
    table = sys.argv[2] if len(sys.argv) > 2 else None
    size = int(sys.argv[3]) if len(sys.argv) > 3 else 5
    if not table:
        print('Usage: sqlite_table_details.py db_path table_name [sample_size]')
    else:
        table_details(db, table, size)
