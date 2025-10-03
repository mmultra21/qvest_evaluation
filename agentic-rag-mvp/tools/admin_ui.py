#!/usr/bin/env python3
"""
Minimal guarded Gradio admin UI module.

This file provides DB helpers and a build_admin_ui()/launch_admin() pair.
Importing this module will NOT start a Gradio server. Call launch_admin()
explicitly to run the interface.
"""

import os
import sys
import sqlite3
import json
import io
import csv
from typing import List, Dict, Any

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'agent.db')


def _escape_html(s: str) -> str:
    try:
        return (str(s)
                .replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;')
                .replace('"', '&quot;')
                .replace("'", '&#39;'))
    except Exception:
        return str(s)


def get_pending_rows() -> List[Dict[str, Any]]:
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    try:
        cur.execute("SELECT id, created_at, student_id, action_type, payload, status, notes FROM audit_logs WHERE status='pending_approval' ORDER BY id DESC")
        rows = cur.fetchall()
    except Exception:
        rows = []
    con.close()
    out = []
    for id_, created_at, student_id, action_type, payload, status, notes in rows:
        try:
            pl = json.loads(payload)
        except Exception:
            pl = payload
        # fetch latest judge label/score if present
        judge_label = None
        judge_score = None
        judge_id = None
        judge_created_at = None
        try:
            con2 = sqlite3.connect(DB_PATH)
            cur2 = con2.cursor()
            cur2.execute('SELECT id, label, score, created_at FROM judge_logs WHERE audit_id = ? ORDER BY created_at DESC LIMIT 1', (id_,))
            jr = cur2.fetchone()
            con2.close()
            if jr:
                judge_id, judge_label, judge_score, judge_created_at = jr[0], jr[1], jr[2], jr[3]
        except Exception:
            pass
        # Try to extract a human-friendly book title for audit rows when possible
        book_title = None
        try:
            # payload may be dict-like
            if isinstance(pl, dict):
                # candidate keys that may contain book id or label
                bid = pl.get('book_id') or pl.get('book') or pl.get('id')
                if bid is not None:
                    # numeric IDs stored as ints in some places, or strings elsewhere
                    try:
                        # If book ids in this repo are numeric (like 1,2,..) try integer mapping
                        bid_int = int(bid)
                    except Exception:
                        bid_int = None
                    # First, try in-module BOOK_DB if present (common admin stub)
                    try:
                        BOOK_DB  # type: ignore
                        info = globals().get('BOOK_DB', {})
                        # If book ids in BOOK_DB are stored as keys, try both string and numeric
                        candidate = None
                        if str(bid) in info:
                            candidate = info.get(str(bid))
                        elif bid_int is not None and bid_int in info:
                            candidate = info.get(bid_int)
                        if candidate and isinstance(candidate, dict):
                            book_title = candidate.get('title')
                    except Exception:
                        book_title = None

                # Prefer explicit title fields in the payload (common from student UI or agent jobs)
                if isinstance(pl, dict):
                    if not book_title:
                        maybe_title = pl.get('title') or pl.get('book_title') or pl.get('label')
                        if maybe_title:
                            book_title = str(maybe_title)[:200]
                    # If payload had a numeric id but no title, fall back to BOOK_DB mapping
                    if not book_title and bid is not None:
                        try:
                            info = globals().get('BOOK_DB', {})
                            if str(bid) in info and isinstance(info.get(str(bid)), dict):
                                book_title = info.get(str(bid)).get('title')
                            elif bid_int is not None and bid_int in info and isinstance(info.get(bid_int), dict):
                                book_title = info.get(bid_int).get('title')
                        except Exception:
                            book_title = None

                    # Prefer a canonical catalog table in the shared DB if available
                    if not book_title and bid_int is not None:
                        try:
                            # look for a books table with title column
                            con3 = sqlite3.connect(DB_PATH)
                            cur3 = con3.cursor()
                            row3 = None
                            try:
                                cur3.execute('SELECT title FROM books WHERE book_id = ? LIMIT 1', (bid_int,))
                                row3 = cur3.fetchone()
                            except Exception:
                                row3 = None
                            if not row3:
                                try:
                                    cur3.execute('SELECT title FROM books WHERE id = ? LIMIT 1', (bid_int,))
                                    row3 = cur3.fetchone()
                                except Exception:
                                    row3 = None
                            if row3 and row3[0]:
                                book_title = str(row3[0])
                            con3.close()
                        except Exception:
                            # DB lookup failed/no table; fall through to other fallbacks
                            book_title = None

                    # If still None and we have numeric book ids (catalog DF in POC), try importing it
                    if not book_title and bid_int is not None:
                        try:
                            import importlib
                            poc = importlib.import_module('agentic-rag-mvp.tools.run_gradio_poc')
                            if hasattr(poc, 'catalog'):
                                try:
                                    df = poc.catalog
                                    # find row where book_id == bid_int
                                    row = df[df['book_id'] == bid_int]
                                    if row is not None and len(row) > 0:
                                        book_title = str(row.iloc[0]['title'])
                                except Exception:
                                    book_title = None
                        except Exception:
                            book_title = None
        except Exception:
            book_title = None

        out.append({'id': id_, 'created_at': created_at, 'student_id': student_id, 'action_type': action_type, 'payload': pl, 'status': status, 'notes': notes, 'book_title': book_title, 'judge_label': judge_label, 'judge_score': judge_score, 'judge_id': judge_id, 'judge_created_at': judge_created_at})
    return out


def update_row_status(row_id: int, status: str, notes: str | None = None):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute('UPDATE audit_logs SET status = ?, notes = ? WHERE id = ?', (status, notes, row_id))
    con.commit()
    con.close()


def fetch_full_judge_json(audit_id: int) -> str:
    """Return the latest judge_logs row for the given audit_id as a JSON string, or empty string if none."""
    try:
        sid = int(audit_id)
    except Exception:
        return ''
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute('SELECT id, model, prompt, score, label, reason, created_at FROM judge_logs WHERE audit_id = ? ORDER BY created_at DESC LIMIT 1', (sid,))
        jr = cur.fetchone()
        con.close()
        if not jr:
            return ''
        j = {
            'id': jr[0],
            'model': jr[1],
            'prompt': jr[2],
            'score': jr[3],
            'label': jr[4],
            'reason': jr[5],
            'created_at': jr[6],
        }
        return json.dumps(j, indent=2, ensure_ascii=False)
    except Exception:
        return ''


# Attempt to import Gradio but keep this module import-safe for CI/tests
try:
    import gradio as gr

    LAST_CHOICES: List[str] = []


    def _badge_html(label: str | None) -> str:
        if label is None:
            return ''
        lab = str(label).lower()
        color = '#6b7280'  # gray
        if lab == 'approve':
            color = '#10b981'  # green
        elif lab == 'review':
            color = '#f59e0b'  # amber
        elif lab == 'reject':
            color = '#ef4444'  # red
        return f"<span style='display:inline-block;padding:2px 8px;border-radius:12px;background:{color};color:white;font-weight:600;font-size:0.9em'>{_escape_html(str(label))}</span>"


    def show_selected_details(selected_id):
        if not selected_id:
            return '<i>No id selected</i>'
        try:
            sid = int(selected_id)
        except Exception:
            return f'<i>Invalid id: {_escape_html(str(selected_id))}</i>'
        try:
            con = sqlite3.connect(DB_PATH)
            cur = con.cursor()
            cur.execute('SELECT payload, status, notes FROM audit_logs WHERE id = ?', (sid,))
            row = cur.fetchone()
            if not row:
                con.close()
                return f'<i>No audit row with id {sid}</i>'
            payload, status, notes = row
            try:
                payload_obj = json.loads(payload)
                payload_str = json.dumps(payload_obj, indent=2, ensure_ascii=False)
            except Exception:
                payload_str = str(payload)

            # fetch latest judge row including id and timestamp so we can show it
            cur.execute('SELECT id, label, score, reason, created_at FROM judge_logs WHERE audit_id = ? ORDER BY created_at DESC LIMIT 1', (sid,))
            jr = cur.fetchone()

            children_html = ''
            try:
                cur.execute('SELECT child_id FROM audit_row_splits WHERE parent_id = ? ORDER BY created_at', (sid,))
                mapping_rows = cur.fetchall()
                if mapping_rows:
                    child_parts = ["<div style='margin-top:10px'><strong>Mapped children:</strong></div>"]
                    for (child_id,) in mapping_rows:
                        cur.execute('SELECT id, created_at, student_id, action_type, payload, status, notes FROM audit_logs WHERE id = ?', (child_id,))
                        cr = cur.fetchone()
                        if cr:
                            cid, ccreated, cstudent, caction, cpayload, cstatus, cnotes = cr
                            try:
                                cp = json.loads(cpayload)
                                cp_s = json.dumps(cp, ensure_ascii=False)
                            except Exception:
                                cp_s = str(cpayload)
                            try:
                                cur.execute('SELECT label, score FROM judge_logs WHERE audit_id = ? ORDER BY created_at DESC LIMIT 1', (cid,))
                                cj = cur.fetchone()
                                if cj:
                                    c_label, c_score = cj[0], cj[1]
                                    badge = _badge_html(c_label)
                                    score_text = f" <strong style='margin-left:6px'>{float(c_score):.2f}</strong>"
                                else:
                                    badge = ''
                                    score_text = ''
                            except Exception:
                                badge = ''
                                score_text = ''
                            child_parts.append(
                                f"<div style='padding:6px;border:1px solid #374151;border-radius:6px;margin-top:6px;background:#111827;color:#e6eef8'>"
                                f"<div><strong style='color:#e6eef8'>Child ID:</strong> {cid} &nbsp; <strong style='color:#e6eef8'>status:</strong> {_escape_html(str(cstatus))} {badge}{score_text}</div>"
                                f"<div style='font-family:monospace;white-space:pre-wrap;margin-top:6px;color:#e6eef8'>{_escape_html(cp_s)}</div>"
                                f"</div>"
                            )
                    children_html = ''.join(child_parts)
            except Exception:
                children_html = ''

            con.close()

            info_parts = []
            if jr:
                # jr is (id, label, score, reason, created_at)
                j_id = jr[0]
                label = jr[1]
                score = jr[2]
                reason = jr[3] if len(jr) > 3 else None
                j_created = jr[4] if len(jr) > 4 else None
                if j_id is not None:
                    info_parts.append(f"<div style='margin-bottom:6px;color:#9ca3af;font-size:0.9em'>Judge id: <strong style='color:#e6eef8'>{j_id}</strong> &nbsp; at { _escape_html(str(j_created)) }</div>")
                try:
                    info_parts.append(f"<div style='margin-bottom:8px'>{_badge_html(label)} <strong style='margin-left:8px;color:#e6eef8'>{float(score):.2f}</strong></div>")
                except Exception:
                    info_parts.append(f"<div style='margin-bottom:8px'>{_badge_html(label)} <strong style='margin-left:8px;color:#e6eef8'>{_escape_html(str(score))}</strong></div>")
                if reason:
                    # show a short snippet of the raw reason for triage
                    r_snip = _escape_html(str(reason))
                    if len(r_snip) > 800:
                        r_snip = r_snip[:800] + '...'
                    info_parts.append(f"<div style='font-size:0.95em;color:#cbd5e1;margin-bottom:8px;white-space:pre-wrap'>{r_snip}</div>")

            info_parts.append(
                f"<div style='font-family:monospace;background:#111827;padding:8px;border-radius:6px;white-space:pre-wrap;color:#e6eef8;border:1px solid #374151'>"
                f"<pre style='margin:0;color:#e6eef8'>{_escape_html(payload_str)}</pre></div>"
            )
            if children_html:
                info_parts.append(children_html)
            return ''.join(info_parts)
        except Exception as e:
            return f'<i>Error fetching details: {_escape_html(str(e))}</i>'


    def on_approve(selected_id, notes):
        if not selected_id:
            return 'No id selected', gr.update(choices=LAST_CHOICES, value=None)
        if str(selected_id) not in LAST_CHOICES:
            return f'Error: Value {selected_id} is not among current choices', gr.update(choices=LAST_CHOICES, value=None)
        update_row_status(int(selected_id), 'approved', notes)
        remaining = [str(r['id']) for r in get_pending_rows()]
        LAST_CHOICES[:] = remaining
        return f'Approved {selected_id}', gr.update(choices=remaining, value=None)


    def on_reject(selected_id, notes):
        if not selected_id:
            return 'No id selected', gr.update(choices=LAST_CHOICES, value=None)
        if str(selected_id) not in LAST_CHOICES:
            return f'Error: Value {selected_id} is not among current choices', gr.update(choices=LAST_CHOICES, value=None)
        update_row_status(int(selected_id), 'rejected', notes)
        remaining = [str(r['id']) for r in get_pending_rows()]
        LAST_CHOICES[:] = remaining
        return f'Rejected {selected_id}', gr.update(choices=remaining, value=None)


    def on_auto_approve(threshold: float):
        if threshold is None:
            return 'No threshold provided', gr.update(choices=LAST_CHOICES, value=None)
        try:
            con = sqlite3.connect(DB_PATH)
            cur = con.cursor()
            cur.execute("SELECT id FROM audit_logs WHERE status='pending_approval'")
            pending = [r[0] for r in cur.fetchall()]
            approved = []
            for pid in pending:
                cur.execute('SELECT score FROM judge_logs WHERE audit_id = ? ORDER BY created_at DESC LIMIT 1', (pid,))
                row = cur.fetchone()
                if not row:
                    continue
                score = float(row[0])
                if score >= float(threshold):
                    cur.execute('UPDATE audit_logs SET status = ?, notes = ? WHERE id = ?', ('approved', f'auto-approved (score={score})', pid))
                    approved.append(pid)
            con.commit()
            con.close()
            remaining = [str(r['id']) for r in get_pending_rows()]
            LAST_CHOICES[:] = remaining
            return f'Auto-approved: {approved}', gr.update(choices=remaining, value=None)
        except Exception as e:
            return f'Error during auto-approve: {e}', gr.update(choices=LAST_CHOICES, value=None)


    def build_admin_ui():
        with gr.Blocks() as admin_ui:
            gr.Markdown('# Admin — Audit approvals')
            gr.HTML("""
            <style>
            #pending_panel, #quick_view_panel, #details_panel { background: #0f172a !important; color: #e6eef8 !important; border: 1px solid #374151 !important; padding: 8px !important; border-radius:6px !important }
            #pending_panel pre, #quick_view_panel pre, #details_panel pre { color: #e6eef8 !important; background: transparent !important; white-space: pre-wrap !important; word-break: break-word !important }
            </style>
            """)

            with gr.Row():
                pending_html = gr.HTML('<i>Loading pending rows...</i>', elem_id='pending_panel')
                pending_ids = gr.Dropdown(label='Select pending id', choices=[], value=None, allow_custom_value=True)

            details_panel = gr.HTML(label='Selected details', elem_id='details_panel')

            with gr.Row():
                notes = gr.Textbox(label='Notes (optional)', lines=2)

            with gr.Row():
                approve_btn = gr.Button('Approve')
                reject_btn = gr.Button('Reject')
                refresh_btn = gr.Button('Refresh')

            with gr.Row():
                auto_thresh = gr.Number(value=0.95, label='Auto-approve threshold (>=)')
                auto_btn = gr.Button('Auto-approve')

            status_out = gr.Textbox(label='Status', interactive=False)

            quick_rows_state = gr.State(value='')

            # hidden box + button for viewing full judge JSON for debugging
            view_judge_btn = gr.Button('View full judge JSON')
            judge_json_box = gr.Textbox(label='Judge JSON (full)', lines=20, visible=False, interactive=False)

            def _truncate(s: str, n: int = 120) -> str:
                s2 = str(s)
                return (s2[:n] + '...') if len(s2) > n else s2

            def refresh_pending():
                rows = get_pending_rows()
                if not rows:
                    LAST_CHOICES.clear()
                    return '<i>No pending actions</i>', gr.update(choices=[], value=None), ''
                # show top 20 quick summary and include more columns
                quick = rows[:20]
                table_rows = []
                for r in quick:
                    j = ''
                    if r.get('judge_label'):
                        j = f" {r['judge_label']}({r.get('judge_score')})"
                    payload_preview = ''
                    try:
                        p = r.get('payload')
                        if isinstance(p, (dict, list)):
                            payload_preview = json.dumps(p, ensure_ascii=False)
                        else:
                            payload_preview = str(p)
                    except Exception:
                        payload_preview = str(r.get('payload'))
                    jid = r.get('judge_id')
                    jid_html = f"<div style='font-size:0.85em;color:#9ca3af'>J:{jid}</div>" if jid else ''
                    # show an optional title if available for quick inspection
                    title_html = ''
                    try:
                        bt = r.get('book_title')
                        if bt:
                            title_html = f"<div style='font-size:0.95em;color:#9ee6c2;margin-top:4px'>{_escape_html(str(bt))}</div>"
                    except Exception:
                        title_html = ''
                    table_rows.append(
                        "<div style='padding:8px;border-bottom:1px dashed #374151;display:flex;gap:12px;align-items:flex-start'>"
                        f"<div style='min-width:58px;color:#cbd5e1'><strong>{r['id']}</strong><div style='font-size:0.85em;color:#9ca3af'>{_escape_html(str(r.get('created_at') or ''))}</div>{jid_html}</div>"
                        f"<div style='min-width:120px;color:#e6eef8'>{_escape_html(str(r.get('student_id') or ''))}<div style='font-size:0.85em;color:#9ca3af'>{_escape_html(str(r.get('status') or ''))}</div></div>"
                        f"<div style='flex:1;min-width:200px;color:#e6eef8'><div style='font-weight:600'>{_escape_html(str(r.get('action_type') or ''))} { _escape_html(j) }</div>{title_html}<div style='font-family:monospace;color:#cbd5e1;margin-top:6px;white-space:pre-wrap'>{_escape_html(_truncate(payload_preview, 240))}</div></div>"
                        "</div>"
                    )
                html = (
                    "<div style='max-height:420px;overflow-y:auto;overflow-x:hidden;padding-right:6px;background:#0f172a;color:#e6eef8;padding:6px;border-radius:6px;border:1px solid #374151'>"
                    + ''.join(table_rows) + '</div>'
                )
                ids = [str(r['id']) for r in rows]
                LAST_CHOICES[:] = ids
                return html, gr.update(choices=ids, value=None), json.dumps(rows)

            def export_rows(state_json):
                try:
                    rows = json.loads(state_json) if state_json else []
                except Exception:
                    rows = []
                buf = io.StringIO()
                writer = csv.writer(buf)
                writer.writerow(['id', 'student_id', 'action_type', 'payload', 'status', 'notes'])
                for r in rows:
                    writer.writerow([r.get('id'), r.get('student_id'), r.get('action_type'), json.dumps(r.get('payload')), r.get('status'), r.get('notes')])
                buf.seek(0)
                return ('pending_rows_export.csv', buf.getvalue().encode('utf-8'))

            refresh_btn.click(fn=refresh_pending, inputs=[], outputs=[pending_html, pending_ids, quick_rows_state])
            approve_btn.click(fn=on_approve, inputs=[pending_ids, notes], outputs=[status_out, pending_ids])
            reject_btn.click(fn=on_reject, inputs=[pending_ids, notes], outputs=[status_out, pending_ids])
            auto_btn.click(fn=on_auto_approve, inputs=[auto_thresh], outputs=[status_out, pending_ids])
            mappings_refresh = gr.Button('Refresh mappings')
            mappings_html = gr.HTML(label='Parent → Child mappings')

            def fetch_mappings():
                con = sqlite3.connect(DB_PATH)
                cur = con.cursor()
                try:
                    cur.execute('''
                        SELECT s.parent_id, s.child_id, p.student_id as parent_student, c.student_id as child_student,
                               c.action_type as child_action, c.payload as child_payload, s.created_at
                        FROM audit_row_splits s
                        LEFT JOIN audit_logs p ON p.id = s.parent_id
                        LEFT JOIN audit_logs c ON c.id = s.child_id
                        ORDER BY s.parent_id DESC
                    ''')
                    rows = cur.fetchall()
                except Exception:
                    rows = []
                con.close()
                if not rows:
                    return '<i>No mappings found</i>'
                header = (
                    '<table style="width:100%;border-collapse:collapse">'
                    '<tr>'
                    '<th style="text-align:left;border-bottom:1px solid #ddd;padding:6px">Parent ID</th>'
                    '<th style="text-align:left;border-bottom:1px solid #ddd;padding:6px">Child ID</th>'
                    '<th style="text-align:left;border-bottom:1px solid #ddd;padding:6px">Parent student</th>'
                    '<th style="text-align:left;border-bottom:1px solid #ddd;padding:6px">Child student</th>'
                    '<th style="text-align:left;border-bottom:1px solid #ddd;padding:6px">Child action</th>'
                    '<th style="text-align:left;border-bottom:1px solid #ddd;padding:6px">Child payload</th>'
                    '<th style="text-align:left;border-bottom:1px solid #ddd;padding:6px">Mapped at</th>'
                    '</tr>'
                )
                rows_html = []
                for parent_id, child_id, p_student, c_student, c_action, c_payload, created_at in rows:
                    try:
                        cp = json.loads(c_payload)
                        cp_str = json.dumps(cp, ensure_ascii=False)
                    except Exception:
                        cp_str = str(c_payload)
                    rows_html.append(
                        '<tr>'
                        f"<td style='padding:6px;border-bottom:1px solid #eee'>{parent_id}</td>"
                        f"<td style='padding:6px;border-bottom:1px solid #eee'>{child_id}</td>"
                        f"<td style='padding:6px;border-bottom:1px solid #eee'>{_escape_html(str(p_student or ''))}</td>"
                        f"<td style='padding:6px;border-bottom:1px solid #eee'>{_escape_html(str(c_student or ''))}</td>"
                        f"<td style='padding:6px;border-bottom:1px solid #eee'>{_escape_html(str(c_action or ''))}</td>"
                        f"<td style='padding:6px;border-bottom:1px solid #eee'><pre style='margin:0;white-space:pre-wrap'>{_escape_html(cp_str)}</pre></td>"
                        f"<td style='padding:6px;border-bottom:1px solid #eee'>{_escape_html(str(created_at or ''))}</td>"
                        '</tr>'
                    )
                table = header + ''.join(rows_html) + '</table>'
                return f"<div style='max-height:420px;overflow:auto;padding-right:6px;background:#0f172a;color:#e6eef8;padding:6px;border-radius:6px;border:1px solid #374151'>{table}</div>"

            mappings_refresh.click(fn=fetch_mappings, inputs=[], outputs=[mappings_html])

            # wire selection to details (also hide judge json box on selection change)
            def _show_selected_and_hide_json(selected_id):
                html = show_selected_details(selected_id)
                # hide and clear the full JSON box when selection changes
                return html, gr.update(visible=False, value='')

            pending_ids.change(fn=_show_selected_and_hide_json, inputs=[pending_ids], outputs=[details_panel, judge_json_box])

            # fetch full judge JSON and reveal the textbox
            def fetch_full_judge_json(selected_id):
                if not selected_id:
                    return gr.update(visible=False, value='')
                try:
                    sid = int(selected_id)
                except Exception:
                    return gr.update(visible=False, value='')
                try:
                    con = sqlite3.connect(DB_PATH)
                    cur = con.cursor()
                    cur.execute('SELECT id, model, prompt, score, label, reason, created_at FROM judge_logs WHERE audit_id = ? ORDER BY created_at DESC LIMIT 1', (sid,))
                    jr = cur.fetchone()
                    con.close()
                    if not jr:
                        return gr.update(visible=False, value='')
                    j = {
                        'id': jr[0],
                        'model': jr[1],
                        'prompt': jr[2],
                        'score': jr[3],
                        'label': jr[4],
                        'reason': jr[5],
                        'created_at': jr[6],
                    }
                    return gr.update(visible=True, value=json.dumps(j, indent=2, ensure_ascii=False))
                except Exception:
                    return gr.update(visible=False, value='')

            view_judge_btn.click(fn=fetch_full_judge_json, inputs=[pending_ids], outputs=[judge_json_box])
            # initial refresh
            refresh_pending()
        return admin_ui


    def launch_admin(port: int | None = None):
        ui = build_admin_ui()
        env_port = os.environ.get('GRADIO_ADMIN_PORT') or os.environ.get('PORT')
        arg_port = None
        if len(sys.argv) > 1:
            try:
                arg_port = int(sys.argv[1])
            except Exception:
                arg_port = None
        chosen = int(arg_port or env_port or port or 7861)
        print(f'Launching admin UI on http://127.0.0.1:{chosen}')
        ui.launch(server_name='127.0.0.1', server_port=chosen, share=False, prevent_thread_lock=False)

except Exception as e:
    # Keep the DB helpers importable if Gradio isn't available.
    # print the error at import time for developer visibility.
    print('Gradio not available or failed to build admin UI:', e)


# Provide fallback stubs so the module always exposes build_admin_ui and launch_admin
# even when Gradio isn't installed. Calling these will raise a clear error.
if 'build_admin_ui' not in globals():
    def build_admin_ui():
        raise RuntimeError('Gradio is not available. Install gradio to build the admin UI.')

if 'launch_admin' not in globals():
    def launch_admin(port: int | None = None):
        raise RuntimeError('Gradio is not available. Install gradio to launch the admin UI.')


if __name__ == '__main__':
    if 'launch_admin' in globals():
        launch_admin()
    else:
        print('Admin UI cannot be launched: Gradio not available or UI failed to build.')
        sys.exit(1)
