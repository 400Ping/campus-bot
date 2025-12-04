
import os, io, tempfile, csv
from datetime import datetime, timedelta
from flask import Flask, request, abort, render_template, redirect, url_for, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from dotenv import load_dotenv

load_dotenv()

from services import db, schedule_service, notes_service, review_service, news_service
db.init_db()

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, AudioMessage, TextSendMessage

app = Flask(__name__)

app.secret_key = os.environ.get('FLASK_SECRET_KEY','dev-secret')
login_manager = LoginManager(app)
login_manager.login_view = 'auth_login'

CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
if not CHANNEL_SECRET or not CHANNEL_ACCESS_TOKEN:
    print("WARN: LINE credentials are missing. Set LINE_CHANNEL_SECRET & LINE_CHANNEL_ACCESS_TOKEN.")
line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN) if CHANNEL_ACCESS_TOKEN else None
handler = WebhookHandler(CHANNEL_SECRET) if CHANNEL_SECRET else None

class WebUser(UserMixin):
    def __init__(self, row):
        self.id = row['id']
        self.email = row['email']
        self.display_name = row.get('display_name') or self.email.split('@')[0]
        self.role = row.get('role') or 'student'
        self.line_user_id = row.get('line_user_id')

@app.before_request
def _force_login_for_web():
    # 只有網站頁面需要登入；LINE webhook (/callback) 不受影響
    protected_prefixes = ("/web", "/account")
    if any(request.path.startswith(p) for p in protected_prefixes):
        if not current_user.is_authenticated:
            # 登入後回跳原頁
            return redirect(url_for("auth_login", next=request.path))

@login_manager.user_loader
def load_user(user_id):
    from services.db import get_account_by_id
    row = get_account_by_id(int(user_id))
    return WebUser(row) if row else None

def _active_user_id():
    """在網站端，未登入時不給 DEMO_USER；登入後依是否綁定 LINE 決定使用者 ID。
    在非網站端（例如 LINE webhook），保留原本的 fallback（?user= 或 DEMO_USER）。"""
    # Web 頁面（/web、/account、/ 這些視為網站入口，不用 DEMO_USER）
    from flask import request
    if request.path.startswith("/web") or request.path.startswith("/account"):
        if not current_user.is_authenticated:
            return None
        return (getattr(current_user, "line_user_id", None)
                or f"WEB_{current_user.id}")

    # 其他（例如 /, /callback）：保留舊邏輯
    if current_user.is_authenticated and getattr(current_user, "line_user_id", None):
        return current_user.line_user_id
    if current_user.is_authenticated:
        return f"WEB_{current_user.id}"
    # 舊有的容錯：?user=xxx 或 DEMO_USER 僅限非網站端
    return request.args.get("user") or "DEMO_USER"

from tasks import start_scheduler
if line_bot_api:
    start_scheduler(line_bot_api)

def _get_target_lang(user_id: str) -> str:
    settings = db.get_user_settings(user_id) or {}
    return settings.get('target_lang') or 'zh-Hant'

def _set_target_lang(user_id: str, lang: str):
    from services.db import set_target_lang
    set_target_lang(user_id, lang)

def _current_user():
    return request.args.get("user") or "DEMO_USER"

@app.route("/")
def index():
    conn = db.get_conn()
    schedule = conn.execute("SELECT * FROM schedule WHERE user_id=? ORDER BY day_of_week, start_time", (_current_user(),)).fetchall()
    notes = conn.execute("SELECT * FROM notes WHERE user_id=? ORDER BY ts DESC LIMIT 30", (_current_user(),)).fetchall()
    conn.close()
    return render_template("index.html", schedule=[dict(r) for r in schedule], notes=[dict(n) for n in notes])

@app.route("/auth/login", methods=["GET","POST"])
def auth_login():
    from services.auth import verify_password
    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password") or ""
        acc = verify_password(email, password)
        if not acc:
            return render_template("login.html", error="Email 或密碼錯誤")
        login_user(WebUser(acc))
        return redirect(url_for("account_home"))
    return render_template("login.html", error=None)

@app.route("/auth/register", methods=["GET","POST"])
def auth_register():
    from services.auth import register
    error = None
    if request.method == "POST":
        display_name = (request.form.get("display_name") or "").strip()
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password") or ""
        acc, error = register(email, password, display_name)
        if acc and not error:
            login_user(WebUser(acc))
            return redirect(url_for("account_home"))
    return render_template("register.html", error=error)

@app.route("/auth/logout")
@login_required
def auth_logout():
    logout_user()
    return redirect(url_for("index"))

@app.route("/account")
@login_required
def account_home():
    return render_template("account.html")

@app.route("/debug/whoami")
@login_required
def debug_whoami():
    uid = _active_user_id()
    return f"active_user_id = {uid}  (已連結LINE={bool(getattr(current_user,'line_user_id',None))})"

@app.route("/account/link-line", methods=["GET","POST"])
@login_required
def link_line():
    msg = None
    if request.method == "POST":
        code = (request.form.get("code") or "").strip()
        from services.auth import consume_link_code
        from services.db import set_line_link, get_account_by_id, migrate_user_data

        line_user_id, err = consume_link_code(code)
        if err:
            msg = "代碼無效或已過期，請在 LINE 輸入 /link 重新取得。"
        else:
            # 1) 綁定 LINE
            set_line_link(current_user.id, line_user_id)

            # 2) 把舊資料從 WEB_<account_id> → LINE user_id
            old_id = f"WEB_{current_user.id}"
            result = migrate_user_data(old_id, line_user_id)
            moved = sum(result["updated"].values())

            # 3) 刷新登入狀態，讓 current_user 立即帶到 line_user_id
            login_user(WebUser(get_account_by_id(current_user.id)))
            msg = f"已成功連結 LINE 帳號！本次搬移 {moved} 筆資料。"
    return render_template("link_line.html", msg=msg)

@app.route("/web/schedule")
def web_schedule():
    conn = db.get_conn()
    schedule = conn.execute("SELECT * FROM schedule WHERE user_id=? ORDER BY day_of_week, start_time", (_current_user(),)).fetchall()
    conn.close()
    return render_template("schedule.html", schedule=[dict(r) for r in schedule])

@app.route("/web/notes")
def web_notes():
    conn = db.get_conn()
    notes = conn.execute("SELECT * FROM notes WHERE user_id=? ORDER BY ts DESC", (_current_user(),)).fetchall()
    conn.close()
    return render_template("notes.html", notes=[dict(n) for n in notes])

@app.route("/web/settings", methods=["GET","POST"])
def web_settings():
    user_id = _current_user()
    db.ensure_user(user_id)
    settings = db.get_user_settings(user_id)
    if request.method == "POST":
        on = request.form.get("translate_on") == "1"
        db.set_translate(user_id, on)
        lang = (request.form.get("target_lang") or "zh-Hant").strip()
        _set_target_lang(user_id, lang)
        # reminders
        notif_on = request.form.get("notifications_on") == "1"
        from services.db import set_notifications, set_reminder_window
        set_notifications(user_id, notif_on)
        try:
            window = int(request.form.get("reminder_window") or 15)
        except Exception:
            window = 15
        set_reminder_window(user_id, window)
        return redirect(url_for("web_settings", user=user_id))
    return render_template("settings.html",
        user_id=user_id,
        translate_on=bool(settings.get("translate_on")) if settings else False,
        target_lang=(settings.get("target_lang") if settings else "zh-Hant"),
        notifications_on=bool(settings.get("notifications_on")) if settings else True,
        reminder_window=(settings.get("reminder_window") if settings else 15)
    )

@app.route("/web/notes/manage")
def web_notes_page():
    user_id = _current_user()
    notes = notes_service.list_notes(user_id)
    return render_template("web_notes.html", user_id=user_id, notes=notes)

@app.route("/web/notes/add", methods=["POST"])
def web_notes_add():
    user_id = request.form.get("user") or "DEMO_USER"
    content = (request.form.get("content") or "").strip()
    course_name = (request.form.get("course_name") or "").strip() or None
    if content:
        notes_service.add_note(user_id, content, course_name)
    return redirect(url_for("web_notes_page", user=user_id))

@app.route("/web/news")
def web_news_page():
    user_id = _current_user()
    return render_template("news.html", user_id=user_id, keywords=news_service.list_keywords(user_id), feeds=news_service.list_feeds(user_id))

@app.route("/web/news/add", methods=["POST"])
def web_news_add():
    user_id = request.form.get("user") or "DEMO_USER"
    kw = (request.form.get("kw") or "").strip()
    if kw:
        news_service.add_keyword(user_id, kw)
    return redirect(url_for("web_news_page", user=user_id))

@app.route("/web/news/remove", methods=["POST"])
def web_news_remove():
    user_id = request.form.get("user") or "DEMO_USER"
    kw = (request.form.get("kw") or "").strip()
    if kw:
        news_service.remove_keyword(user_id, kw)
    return redirect(url_for("web_news_page", user=user_id))

@app.route("/web/feeds/add", methods=["POST"])
def web_feed_add():
    user_id = request.form.get("user") or "DEMO_USER"
    feed_url = (request.form.get("feed_url") or "").strip()
    if feed_url:
        news_service.add_feed(user_id, feed_url)
    return redirect(url_for("web_news_page", user=user_id))

@app.route("/web/feeds/remove", methods=["POST"])
def web_feed_remove():
    user_id = request.form.get("user") or "DEMO_USER"
    feed_url = (request.form.get("feed_url") or "").strip()
    if feed_url:
        news_service.remove_feed(user_id, feed_url)
    return redirect(url_for("web_news_page", user=user_id))

@app.route("/web/review", methods=["GET","POST"])
def web_review_page():
    user_id = _current_user()
    pack = None
    if request.method == "POST":
        pack = review_service.generate_review_for_date(user_id, datetime.now())
    return render_template("review.html", user_id=user_id, pack=pack)

@app.route("/web/schedule/manage")
def web_schedule_manage():
    user_id = _current_user()
    conn = db.get_conn()
    schedule = conn.execute("SELECT * FROM schedule WHERE user_id=? ORDER BY day_of_week, start_time", (user_id,)).fetchall()
    conn.close()
    return render_template("schedule_manage.html", schedule=[dict(r) for r in schedule], user_id=user_id)

@app.route("/web/schedule/add", methods=["POST"])
def web_schedule_add():
    user_id = request.form.get("user") or "DEMO_USER"
    schedule_service.add_course(
        user_id=user_id,
        course_name=request.form.get("course_name"),
        dow=int(request.form.get("day_of_week")),
        start_time=request.form.get("start_time"),
        end_time=request.form.get("end_time"),
        location=request.form.get("location") or None
    )
    return redirect(url_for("web_schedule_manage", user=user_id))

@app.route("/web/schedule/upload", methods=["POST"])
def web_schedule_upload():
    user_id = _current_user()
    f = request.files.get("csv")
    if f:
        reader = csv.DictReader(io.StringIO(f.stream.read().decode("utf-8")))
        conn = db.get_conn()
        for row in reader:
            conn.execute(
                "INSERT INTO schedule(user_id, course_name, day_of_week, start_time, end_time, location) VALUES (?,?,?,?,?,?)",
                (row["user_id"], row["course_name"], int(row["day_of_week"]), row["start_time"], row["end_time"], row.get("location"))
            )
        conn.commit()
        conn.close()
    return redirect(url_for("web_schedule_manage", user=user_id))

@app.route("/web/schedule/delete", methods=["POST"])
def web_schedule_delete():
    user_id = request.form.get("user") or "DEMO_USER"
    row_id = request.form.get("row_id")
    if row_id:
        schedule_service.remove_course(user_id, int(row_id))
    return redirect(url_for("web_schedule_manage", user=user_id))

@app.route("/healthz")
def healthz():
    return "ok"

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    if not handler:
        return "LINE handler is not configured.", 500
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event: MessageEvent):
    user_id = event.source.user_id
    text = (event.message.text or "").strip()
    db.ensure_user(user_id)

    
    if text.startswith("/help"):
        tokens = text.split(maxsplit=1)
        from services.help_texts import get_help, list_topics
        topic = tokens[1] if len(tokens) == 2 else None
        txt = get_help(topic)
        # 回覆（若太長可分段；目前每段都不大於 4000 字）
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=txt))
        return
    
    if text.strip() == "/link":
        from services.auth import gen_link_code
        code = gen_link_code(user_id)  # 這裡的 user_id 通常是 event.source.user_id
        url = (os.environ.get("HOST_BASE_URL") or "http://localhost:5000") + "/account/link-line"
        line_bot_api.reply_message(event.reply_token,
            TextSendMessage(text=f"請在網站登入後前往 {url}，輸入以下代碼完成連結（15 分鐘內有效）：\n{code}"))
        return

    # text translate shortcut
    if text.startswith("/t ") or text.startswith("t: "):
        payload = text[3:].strip()
        if not payload:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="用法：/t 文字內容"))
            return
        from services.speech_translate_service import translate_text
        lang = _get_target_lang(user_id)
        translated = translate_text(payload, to_lang=lang) or "(翻譯失敗)"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=translated))
        return

    if text.startswith("/translate"):
        tokens = text.split()
        if len(tokens) == 1 or tokens[1] in ("help","?"):
            msg = ("翻譯指令：\n"
                   "/translate on [lang]  → 開啟語音翻譯（預設 zh-Hant）\n"
                   "/translate off        → 關閉語音翻譯\n"
                   "/translate lang <code>→ 設定目標語言（zh-Hant|en|ja|ko|de|es|hi）\n"
                   "/translate status     → 查看狀態\n"
                   "/t <text> 或 t: <text>→ 文字翻譯到目標語言")
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=msg))
            return
        sub = tokens[1].lower()
        if sub == "on":
            lang = tokens[2] if len(tokens) >= 3 else "zh-Hant"
            db.set_translate(user_id, True)
            _set_target_lang(user_id, lang)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"語音翻譯已開啟，目標語言={lang}"))
            return
        if sub == "off":
            db.set_translate(user_id, False)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="語音翻譯已關閉"))
            return
        if sub == "lang" and len(tokens) >= 3:
            lang = tokens[2]
            _set_target_lang(user_id, lang)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"已設定目標語言為 {lang}"))
            return
        if sub == "status":
            settings = db.get_user_settings(user_id) or {}
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"翻譯啟用={bool(settings.get('translate_on'))}, 目標語言={_get_target_lang(user_id)}"))
            return
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="用法：/translate on [lang] | /translate off | /translate lang <code> | /translate status"))
        return

    if text.startswith("/settings"):
        tokens = text.split()
        if len(tokens) == 1 or tokens[1] in ("help","?"):
            settings = db.get_user_settings(user_id) or {}
            msg = (f"設定狀態:\n"
                   f"- 翻譯啟用: {bool(settings.get('translate_on'))}\n"
                   f"- 目標語言: {_get_target_lang(user_id)}\n"
                   f"- 上課提醒: {bool(settings.get('notifications_on',1))}\n"
                   f"- 提前分鐘: {settings.get('reminder_window',15)}\n"
                   "指令：\n"
                   "/settings reminder on|off\n"
                   "/settings window <分鐘>\n"
                   "/settings tz <時區> (選填，如 Asia/Taipei)")
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=msg))
            return
        sub = tokens[1].lower()
        if sub == "reminder" and len(tokens) >= 3:
            on = tokens[2].lower() == "on"
            from services.db import set_notifications
            set_notifications(user_id, on)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"上課提醒已{'開啟' if on else '關閉'}"))
            return
        if sub == "window" and len(tokens) >= 3:
            try:
                mins = int(tokens[2])
                from services.db import set_reminder_window
                set_reminder_window(user_id, mins)
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"提醒時間已設為 {mins} 分鐘前"))
            except Exception:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="請輸入整數分鐘，例如：/settings window 15"))
            return
        if sub == "tz" and len(tokens) >= 3:
            tz = tokens[2]
            from services.db import set_timezone
            set_timezone(user_id, tz)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"已設定時區為 {tz}"))
            return
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="用法：/settings reminder on|off | /settings window <分鐘> | /settings tz <時區>"))
        return

    if text.startswith("/schedule "):
        # Management commands
        if text.startswith("/schedule add "):
            try:
                payload = text[len("/schedule add "):].strip()
                first_sp = payload.find(" ")
                dow = int(payload[:first_sp])
                rest = payload[first_sp+1:].strip()
                time_part, rest2 = rest.split(" ", 1)
                start, end = time_part.split("-")
                course = rest2
                location = None
                if "@" in rest2:
                    course, location = [x.strip() for x in rest2.split("@", 1)]
                schedule_service.add_course(user_id, course_name=course, dow=dow, start_time=start, end_time=end, location=location)
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="已新增課程。"))
            except Exception as e:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="用法：/schedule add <1-7> <HH:MM-HH:MM> <課程> [@地點]"))
            return
        if text == "/schedule list":
            rows = schedule_service.list_schedule(user_id)
            if not rows:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="尚無課表資料。"))
            else:
                body = "\n".join([f"#{r['id']} [週{r['day_of_week']}] {r['start_time']}-{r['end_time']} {r['course_name']} @ {r.get('location') or '教室'}" for r in rows][:50])
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=body))
            return
        if text.startswith("/schedule remove "):
            try:
                rid = int(text.split()[2])
                schedule_service.remove_course(user_id, rid)
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"已刪除課程 #{rid}。"))
            except Exception:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="用法：/schedule remove <ID>（先用 /schedule list 查 ID）"))
            return
        if text.startswith("/schedule clear"):
            parts = text.split()
            if len(parts) == 3 and parts[2].lower() == "all":
                schedule_service.clear_schedule(user_id, None)
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="已清空全部課表。"))
            elif len(parts) == 4 and parts[2].lower() == "day":
                try:
                    dow = int(parts[3])
                    schedule_service.clear_schedule(user_id, dow)
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"已清空週 {dow} 課表。"))
                except Exception:
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="用法：/schedule clear day <1-7>"))
            else:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="用法：/schedule clear all | /schedule clear day <1-7>"))
            return

    if text.startswith("/schedule"):
        tokens = text.split()
        when = tokens[1] if len(tokens) > 1 else "today"
        now = datetime.now()
        if when == "today":
            rows = schedule_service.get_day_schedule(user_id, now)
            msg = "今天沒有課表或尚未設定。" if not rows else "【今天課表】\n" + "\n".join([f"{r['start_time']}-{r['end_time']} {r['course_name']} @ {r.get('location') or '教室'}" for r in rows])
        elif when == "tomorrow":
            rows = schedule_service.get_day_schedule(user_id, now + timedelta(days=1))
            msg = "明天沒有課表或尚未設定。" if not rows else "【明天課表】\n" + "\n".join([f"{r['start_time']}-{r['end_time']} {r['course_name']} @ {r.get('location') or '教室'}" for r in rows])
        else:
            rows = schedule_service.get_week_schedule(user_id, now)
            msg = "本週沒有課表或尚未設定。" if not rows else "【本週課表】\n" + "\n".join([f"{r['date']} {r['start_time']}-{r['end_time']} {r['course_name']} @ {r.get('location') or '教室'}" for r in rows][:50])
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=msg))
        return

    if text.startswith("/note"):
        content = text[len("/note"):].strip()
        if not content:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="請在 /note 後面接上筆記內容。"))
            return
        summary = notes_service.add_note(user_id, content, course_name=None)
        msg = "已新增筆記。"
        if summary:
            msg += "\nAI 重點：\n" + summary
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=msg))
        return

    if text.startswith("/review"):
        tokens = text.split()
        when = tokens[1] if len(tokens) > 1 else "today"
        if when != "today":
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="目前僅支援 `/review today`"))
            return
        pack = review_service.generate_review_for_date(user_id, datetime.now())
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=(pack[:4000] if pack else "今天沒有筆記，或 AI 產生失敗。")))
        return

    if text.startswith("/news feed "):
        parts = text.split(maxsplit=3)
        if len(parts) >= 3:
            sub = parts[2].lower()
            if sub == "add" and len(parts) == 4:
                url = parts[3].strip()
                news_service.add_feed(user_id, url)
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="已新增 RSS 來源。"))
                return
            if sub == "remove" and len(parts) == 4:
                url = parts[3].strip()
                news_service.remove_feed(user_id, url)
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="已移除 RSS 來源。"))
                return
            if sub == "list":
                feeds = news_service.list_feeds(user_id)
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="RSS 來源：\n" + ("\n".join(feeds) if feeds else "（使用預設）")))
                return
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="用法：/news feed add <url> | /news feed remove <url> | /news feed list"))
        return

    if text.startswith("/news "):
        tokens = text.split(maxsplit=2)
        if len(tokens) < 2:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="用法：/news add <kw> | /news list | /news remove <kw>"))
            return
        sub = tokens[1]
        if sub == "add" and len(tokens) == 3:
            news_service.add_keyword(user_id, tokens[2])
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"已加入關鍵字：{tokens[2]}"))
        elif sub == "remove" and len(tokens) == 3:
            news_service.remove_keyword(user_id, tokens[2])
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"已移除關鍵字：{tokens[2]}"))
        elif sub == "list":
            kws = news_service.list_keywords(user_id)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="關鍵字：\n" + ("、".join(kws) if kws else "（無）")))
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="用法：/news add <kw> | /news list | /news remove <kw>"))
        return

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="指令未知。輸入 /help 取得說明。"))

@handler.add(MessageEvent, message=AudioMessage)
def handle_audio_message(event: MessageEvent):
    user_id = event.source.user_id
    db.ensure_user(user_id)
    settings = db.get_user_settings(user_id)
    if not settings or not settings.get('translate_on'):
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="語音翻譯未開啟。請輸入 /translate on"))
        return

    message_content = line_bot_api.get_message_content(event.message.id)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".m4a") as tf:
        for chunk in message_content.iter_content():
            tf.write(chunk)
        temp_path = tf.name

    from services.speech_translate_service import speech_to_text_auto, translate_text
    transcript, detected = speech_to_text_auto(temp_path, languages=["en-US","zh-TW","ja-JP","ko-KR","de-DE","es-ES","hi-IN"])
    if not transcript:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="語音辨識失敗，請再試一次。"))
        return
    target = _get_target_lang(user_id)
    translated = translate_text(transcript, to_lang=target) or "(翻譯失敗)"
    det = detected or "unknown"
    msg = f"🎙️ Detected: {det}\nTranscript:\n{transcript}\n\n🌐 → {target}\n{translated}"
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=msg))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
