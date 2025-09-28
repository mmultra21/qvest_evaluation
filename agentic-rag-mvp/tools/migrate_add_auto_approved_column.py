#!/usr/bin/env python3
"""
Add an `auto_approved` BOOLEAN column to `audit_logs` and migrate existing flags
found in the `notes` column (e.g., notes LIKE '%auto-approved%') into the new
column. This script is idempotent-safe: it will skip the migration if the
column already exists.

Usage: python tools/migrate_add_auto_approved_column.py
"""
import sqlite3
import os
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'agent.db')

con = sqlite3.connect(DB_PATH)
cur = con.cursor()
# Check if column exists
cur.execute("PRAGMA table_info(audit_logs)")
cols = [r[1] for r in cur.fetchall()]
if 'auto_approved' in cols:
    print('auto_approved column already exists; nothing to do')
    con.close()
    raise SystemExit(0)

print('Adding auto_approved column to audit_logs...')
cur.execute('ALTER TABLE audit_logs ADD COLUMN auto_approved INTEGER DEFAULT 0')
con.commit()

# Migrate existing notes-based flags into the new column
print('Migrating notes-based flags into auto_approved...')
cur.execute("UPDATE audit_logs SET auto_approved = 1 WHERE notes LIKE '%auto-approved%'")
con.commit()
print(f'Migrated rows: {con.total_changes}')
con.close()
print('Migration complete.')
