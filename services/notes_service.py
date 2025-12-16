
import os
from datetime import datetime
from .db import get_conn
from .summarize_service import summarize_note

def add_note(user_id, content, course_name=None):
    ts = datetime.now().isoformat(timespec='seconds')
    summary = summarize_note(content) or None
    conn = get_conn()
    conn.execute(
        "INSERT INTO notes(user_id, course_name, ts, content, summary) VALUES (?,?,?,?,?)",
        (user_id, course_name, ts, content, summary),
    )
    conn.commit()
    conn.close()
    return summary

def get_notes_for_date(user_id, date_obj):
    date_str = date_obj.strftime('%Y-%m-%d')
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM notes WHERE user_id=? AND ts LIKE ? ORDER BY ts DESC",
        (user_id, date_str + '%')
    ).fetchall()
    result = [dict(r) for r in rows]
    conn.close()
    return result

def list_notes(user_id, limit=50):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM notes WHERE user_id=? ORDER BY ts DESC LIMIT ?", (user_id, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_note(user_id, note_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM notes WHERE id=? AND user_id=?", (note_id, user_id)).fetchone()
    conn.close()
    return dict(row) if row else None

def regenerate_note_summary(user_id, note_id, new_summary=None):
    """Force regenerate one note's summary; return updated row or None."""
    conn = get_conn()
    row = conn.execute("SELECT id, content FROM notes WHERE id=? AND user_id=?", (note_id, user_id)).fetchone()
    if not row:
        conn.close()
        return None
    summary = new_summary or summarize_note(row["content"]) or None
    if summary:
        conn.execute("UPDATE notes SET summary=? WHERE id=?", (summary, note_id))
        conn.commit()
    updated = conn.execute("SELECT * FROM notes WHERE id=?", (note_id,)).fetchone()
    conn.close()
    return dict(updated) if updated else None

def ensure_summaries(user_id, limit=20):
    """Backfill summaries for this user（有 LLM 用 LLM，沒有就用 rule-based）。"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, content FROM notes WHERE user_id=? AND (summary IS NULL OR summary='') ORDER BY ts DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    updated = 0
    for r in rows:
        s = summarize_note(r["content"])
        if not s:
            continue
        conn.execute("UPDATE notes SET summary=? WHERE id=?", (s, r["id"]))
        updated += 1
    if updated:
        conn.commit()
    conn.close()
    return updated

def ensure_summaries_for_all(limit_per_user=200):
    """Backfill summaries for every user in notes table."""
    conn = get_conn()
    users = [r[0] for r in conn.execute("SELECT DISTINCT user_id FROM notes").fetchall()]
    conn.close()
    total = 0
    for u in users:
        total += ensure_summaries(u, limit=limit_per_user)
    return total

def delete_note(user_id, note_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM notes WHERE id=? AND user_id=?", (note_id, user_id))
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return deleted
