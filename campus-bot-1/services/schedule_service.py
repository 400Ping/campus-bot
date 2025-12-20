from datetime import datetime, timedelta
from .db import get_conn

def add_course(user_id, course_name, dow, start_time, end_time, location=None):
    # 1. === 時間順序檢查 (新功能) ===
    # 防止「13:30 開始，12:30 結束」這種倒流狀況
    if start_time >= end_time:
        raise ValueError(f"結束時間 ({end_time}) 不能早於或等於開始時間 ({start_time})。")

    conn = get_conn()
    
    # 2. === 衝堂檢查 ===
    # 檢查同一天是否已經有課
    cursor = conn.execute("""
        SELECT course_name FROM schedule 
        WHERE user_id = ? 
          AND day_of_week = ? 
          AND start_time < ? 
          AND end_time > ?
    """, (user_id, dow, end_time, start_time))
    
    conflict = cursor.fetchone()
    if conflict:
        try:
            exist_name = conflict['course_name']
        except (TypeError, IndexError, KeyError):
            exist_name = conflict[0]
            
        conn.close() 
        raise ValueError(f"該時段已經有「{exist_name}」課程，無法新增衝堂課程")

    # 3. === 執行新增 ===
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
            start_dt = datetime.combine(now.date(), datetime.strptime(row['start_time'], '%H:%M').time())
            delta = (start_dt - now).total_seconds() / 60.0
            if 0 <= delta <= within_minutes:
                upcoming.append(row)
        except:
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
    conn = get_conn()
    # ORDER BY id ASC 確保是依照「加入先後」排序
    rows = conn.execute("SELECT * FROM schedule WHERE user_id=? ORDER BY id ASC", (user_id,)).fetchall()
    conn.close()
    
    results = []
    # enumerate(rows, 1) 會自動幫我們從 1 開始數
    for idx, row in enumerate(rows, 1):
        d = dict(row)
        d['display_id'] = idx  
        results.append(d)
    return results
def remove_course_by_index(user_id, index):
    # 1. 取得目前標好號碼的列表
    courses = get_indexed_schedule(user_id)
    
    # 2. 找到對應編號的課程
    target = None
    for c in courses:
        if c['display_id'] == index:
            target = c
            break
            
    # 3. 如果找到了，就用它真正的資料庫 ID 來刪除
    if target:
        remove_course(user_id, target['id'])
        return target['course_name']  # 回傳被刪掉的課程名稱方便顯示
    else:
        raise ValueError(f"找不到編號 {index} 的課程")