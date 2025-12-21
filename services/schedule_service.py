
from datetime import datetime, timedelta
from .db import get_conn


def add_course(user_id, course_name, dow, start_time, end_time, location=None):
    # 基本時間檢查，避免倒流
    if start_time >= end_time:
        raise ValueError(f"結束時間 ({end_time}) 不能早於或等於開始時間 ({start_time})。")

    conn = get_conn()

    # 檢查衝堂，同一天任一時段重疊就拒絕
    cursor = conn.execute(
        """
        SELECT course_name FROM schedule
        WHERE user_id = ?
          AND day_of_week = ?
          AND start_time < ?
          AND end_time > ?
    """,
        (user_id, dow, end_time, start_time),
    )
    conflict = cursor.fetchone()
    if conflict:
        try:
            exist_name = conflict["course_name"]
        except Exception:
            exist_name = conflict[0]
        conn.close()
        raise ValueError(f"該時段已經有「{exist_name}」課程，無法新增衝堂課程")

    conn.execute(
        "INSERT INTO schedule(user_id, course_name, day_of_week, start_time, end_time, location) VALUES (?,?,?,?,?,?)",
        (user_id, course_name, dow, start_time, end_time, location),
    )
    conn.commit()
    conn.close()
    return True

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
        try:
            start_dt = datetime.combine(now.date(), datetime.strptime(row["start_time"], "%H:%M").time())
            delta = (start_dt - now).total_seconds() / 60.0
            if 0 <= delta <= within_minutes:
                upcoming.append(row)
        except Exception:
            continue
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


def get_indexed_schedule(user_id):
    """Return schedule ordered by insertion with a 1-based display_id."""
    conn = get_conn()
    rows = conn.execute("SELECT * FROM schedule WHERE user_id=? ORDER BY id ASC", (user_id,)).fetchall()
    conn.close()

    results = []
    for idx, row in enumerate(rows, 1):
        d = dict(row)
        d["display_id"] = idx
        results.append(d)
    return results


def remove_course_by_index(user_id, index):
    courses = get_indexed_schedule(user_id)
    target = None
    for c in courses:
        if c["display_id"] == index:
            target = c
            break

    if target:
        remove_course(user_id, target["id"])
        return target["course_name"]
    raise ValueError(f"找不到編號 {index} 的課程")
