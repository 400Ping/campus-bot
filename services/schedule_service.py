
from datetime import datetime, timedelta
from .db import get_conn

def add_course(user_id, course_name, dow, start_time, end_time, location):
    conn = get_conn()
    conn.execute(
        "INSERT INTO schedule(user_id, course_name, day_of_week, start_time, end_time, location) VALUES (?,?,?,?,?,?)",
        (user_id, course_name, dow, start_time, end_time, location),
    )
    conn.commit()
    conn.close()

def get_day_schedule(user_id, date: datetime):
    dow = ((date.isoweekday() - 1) % 7) + 1
    conn = get_conn()
    rows = conn.execute("SELECT * FROM schedule WHERE user_id=? AND day_of_week=? ORDER BY start_time", (user_id, dow)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_week_schedule(user_id, date: datetime):
    result = []
    monday = date - timedelta(days=date.weekday())
    for i in range(7):
        d = monday + timedelta(days=i)
        items = get_day_schedule(user_id, d)
        for x in items:
            x['date'] = d.strftime('%Y-%m-%d')
        result.extend(items)
    return result

def find_upcoming_classes(user_id, now: datetime, within_minutes=15):
    day_list = get_day_schedule(user_id, now)
    upcoming = []
    for row in day_list:
        start_dt = datetime.combine(now.date(), datetime.strptime(row['start_time'], '%H:%M').time())
        delta = (start_dt - now).total_seconds() / 60.0
        if 0 <= delta <= within_minutes:
            upcoming.append(row)
    return upcoming

def list_schedule(user_id):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM schedule WHERE user_id=? ORDER BY day_of_week, start_time", (user_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def remove_course(user_id, row_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM schedule WHERE user_id=? AND id=?", (user_id, int(row_id)))
    conn.commit()
    conn.close()

def clear_schedule(user_id, day_of_week: int | None = None):
    conn = get_conn()
    if day_of_week is None:
        conn.execute("DELETE FROM schedule WHERE user_id=?", (user_id,))
    else:
        conn.execute("DELETE FROM schedule WHERE user_id=? AND day_of_week=?", (user_id, int(day_of_week)))
    conn.commit()
    conn.close()
