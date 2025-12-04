
import os, sqlite3, pathlib, threading

DB_PATH = os.environ.get("DB_PATH", str(pathlib.Path(__file__).resolve().parent.parent / "data" / "db.sqlite3"))
_lock = threading.Lock()

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS users (
        user_id TEXT PRIMARY KEY,
        translate_on INTEGER DEFAULT 0,
        locale TEXT DEFAULT 'zh-TW',
        timezone TEXT DEFAULT 'Asia/Taipei',
        target_lang TEXT DEFAULT 'zh-Hant',
        notifications_on INTEGER DEFAULT 1,
        reminder_window INTEGER DEFAULT 15
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
    );""",

    """CREATE TABLE IF NOT EXISTS feeds (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        url TEXT
    );"""
    """CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE,
        password_hash TEXT,
        display_name TEXT,
        role TEXT DEFAULT 'student',
        line_user_id TEXT,
        is_verified INTEGER DEFAULT 0,
        created_at TEXT
    );""",
    """CREATE TABLE IF NOT EXISTS link_codes (
        code TEXT PRIMARY KEY,
        line_user_id TEXT,
        expires_at TEXT
    );""",
]

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    for ddl in SCHEMA:
        s = (ddl or "").strip()
        if not s:
            continue
        if not s.endswith(";"):
            s += ";"
        cur.executescript(s)
    conn.commit()
    conn.close()

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
    if 'notifications_on' not in cols:
        try:
            cur.execute("ALTER TABLE users ADD COLUMN notifications_on INTEGER DEFAULT 1")
            conn.commit()
        except Exception:
            pass
    if 'reminder_window' not in cols:
        try:
            cur.execute("ALTER TABLE users ADD COLUMN reminder_window INTEGER DEFAULT 15")
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

def set_notifications(user_id: str, on: bool):
    conn = get_conn()
    conn.execute("UPDATE users SET notifications_on=? WHERE user_id=?", (1 if on else 0, user_id))
    conn.commit()
    conn.close()

def set_reminder_window(user_id: str, minutes: int):
    conn = get_conn()
    conn.execute("UPDATE users SET reminder_window=? WHERE user_id=?", (int(minutes), user_id))
    conn.commit()
    conn.close()

def set_timezone(user_id: str, tz: str):
    conn = get_conn()
    conn.execute("UPDATE users SET timezone=? WHERE user_id=?", (tz, user_id))
    conn.commit()
    conn.close()

# --- Accounts helpers ---
def create_account(email, password_hash, display_name, role='student'):
    from datetime import datetime
    conn = get_conn()
    conn.execute("INSERT INTO accounts(email, password_hash, display_name, role, created_at) VALUES (?,?,?,?,?)",
                 (email, password_hash, display_name, role, datetime.now().isoformat(timespec='seconds')))
    conn.commit()
    acc = conn.execute("SELECT * FROM accounts WHERE email=?", (email,)).fetchone()
    conn.close()
    return dict(acc) if acc else None

def get_account_by_email(email):
    conn = get_conn()
    row = conn.execute("SELECT * FROM accounts WHERE email=?", (email,)).fetchone()
    conn.close()
    return dict(row) if row else None

def get_account_by_id(acc_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM accounts WHERE id=?", (acc_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def set_line_link(acc_id, line_user_id):
    conn = get_conn()
    conn.execute("UPDATE accounts SET line_user_id=? WHERE id=?", (line_user_id, acc_id))
    conn.commit()
    conn.close()

def list_accounts(limit=200):
    conn = get_conn()
    rows = conn.execute("""SELECT id,email,display_name,role,line_user_id,is_verified,created_at
                           FROM accounts ORDER BY id DESC LIMIT ?""", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# link codes
def save_link_code(code, line_user_id, expires_at):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO link_codes(code, line_user_id, expires_at) VALUES (?,?,?)",
                 (code, line_user_id, expires_at))
    conn.commit()
    conn.close()

def get_and_delete_link_code(code):
    conn = get_conn()
    row = conn.execute("SELECT * FROM link_codes WHERE code=?", (code,)).fetchone()
    if row:
        conn.execute("DELETE FROM link_codes WHERE code=?", (code,))
        conn.commit()
    conn.close()
    return dict(row) if row else None
