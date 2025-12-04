
import os, sqlite3, pathlib, threading

DB_PATH = os.environ.get("DB_PATH", str(pathlib.Path(__file__).resolve().parent.parent / "data" / "db.sqlite3"))
_lock = threading.Lock()

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS users (
        user_id TEXT PRIMARY KEY,
        translate_on INTEGER DEFAULT 0,
        locale TEXT DEFAULT 'zh-TW',
        timezone TEXT DEFAULT 'Asia/Taipei',
        target_lang TEXT DEFAULT 'zh-Hant'
    );""",

    """CREATE TABLE IF NOT EXISTS schedule (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        course_name TEXT,
        day_of_week INTEGER,
        start_time TEXT,
        end_time TEXT,
        location TEXT
    );""",

    """CREATE TABLE IF NOT EXISTS notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        course_name TEXT,
        ts TEXT,
        content TEXT,
        summary TEXT
    );""",

    """CREATE TABLE IF NOT EXISTS keywords (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        keyword TEXT
    );""",

    """CREATE TABLE IF NOT EXISTS news_cache (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        url TEXT UNIQUE,
        title TEXT,
        ts TEXT
    );"""
]

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with _lock:
        conn = get_conn()
        cur = conn.cursor()
        for ddl in SCHEMA:
            cur.execute(ddl)
        conn.commit()
        conn.close()
    _ensure_columns()

def _ensure_columns():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(users)")
    cols = [r[1] for r in cur.fetchall()]
    if 'target_lang' not in cols:
        try:
            cur.execute("ALTER TABLE users ADD COLUMN target_lang TEXT DEFAULT 'zh-Hant'")
            conn.commit()
        except Exception:
            pass
    conn.close()

def ensure_user(user_id: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    if not row:
        cur.execute("INSERT INTO users(user_id) VALUES (?)", (user_id,))
        conn.commit()
    conn.close()

def get_user_settings(user_id: str):
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def set_translate(user_id: str, on: bool):
    conn = get_conn()
    conn.execute("UPDATE users SET translate_on=? WHERE user_id=?", (1 if on else 0, user_id))
    conn.commit()
    conn.close()

def set_target_lang(user_id: str, lang: str):
    conn = get_conn()
    conn.execute("UPDATE users SET target_lang=? WHERE user_id=?", (lang, user_id))
    conn.commit()
    conn.close()
