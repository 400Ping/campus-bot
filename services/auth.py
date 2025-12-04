# services/auth.py
import os
from werkzeug.security import generate_password_hash, check_password_hash
from .db import create_account, get_account_by_email, get_account_by_id, set_line_link, save_link_code, get_and_delete_link_code
from datetime import datetime, timedelta
import secrets

ALLOWED_EMAIL_DOMAINS = [d.strip().lower() for d in (os.environ.get("ALLOWED_EMAIL_DOMAINS","").split(",") if os.environ.get("ALLOWED_EMAIL_DOMAINS") else [])]

def allow_email(email: str) -> bool:
    if not ALLOWED_EMAIL_DOMAINS:
        return True
    try:
        dom = email.split("@",1)[1].lower()
    except Exception:
        return False
    return dom in ALLOWED_EMAIL_DOMAINS

def register(email: str, password: str, display_name: str, role="student"):
    if not allow_email(email):
        return None, "Email domain not allowed"
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
