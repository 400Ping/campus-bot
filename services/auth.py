# services/auth.py
from werkzeug.security import generate_password_hash, check_password_hash
from .db import (
    create_account,
    get_account_by_email,
    get_account_by_id,
    set_line_link,
    save_link_code,
    get_and_delete_link_code,
)
from datetime import datetime, timedelta
import secrets

# 不再限制 email 網域
def register(email: str, password: str, display_name: str, role: str = "student"):
    if get_account_by_email(email):
        return None, "Email already registered"
    ph = generate_password_hash(password)
    acc = create_account(email, ph, display_name, role=role)
    return acc, None

def verify_password(email: str, password: str):
    acc = get_account_by_email(email)
    if not acc:
        return None
    if check_password_hash(acc["password_hash"], password):
        return acc
    return None

def gen_link_code(line_user_id: str) -> str:
    code = secrets.token_urlsafe(5)
    exp = (datetime.utcnow() + timedelta(minutes=15)).isoformat(timespec="seconds")
    save_link_code(code, line_user_id, exp)
    return code

def consume_link_code(code: str):
    row = get_and_delete_link_code(code)
    if not row:
        return None, "invalid"
    try:
        exp = datetime.fromisoformat(row["expires_at"])
        if exp < datetime.utcnow():
            return None, "expired"
    except Exception:
        pass
    return row["line_user_id"], None
