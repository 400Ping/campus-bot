
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
    conn.close()
    return [dict(r) for r in rows]

def list_notes(user_id, limit=50):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM notes WHERE user_id=? ORDER BY ts DESC LIMIT ?", (user_id, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]
