
import os, io, tempfile, csv
from datetime import datetime, timedelta
from flask import Flask, request, abort, render_template, redirect, url_for
from dotenv import load_dotenv

load_dotenv()

from services import db, schedule_service, notes_service, review_service, news_service
db.init_db()

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, AudioMessage, TextSendMessage

app = Flask(__name__)

CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
if not CHANNEL_SECRET or not CHANNEL_ACCESS_TOKEN:
    print("WARN: LINE credentials are missing. Set LINE_CHANNEL_SECRET & LINE_CHANNEL_ACCESS_TOKEN.")
line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN) if CHANNEL_ACCESS_TOKEN else None
handler = WebhookHandler(CHANNEL_SECRET) if CHANNEL_SECRET else None

from tasks import start_scheduler
if line_bot_api:
    start_scheduler(line_bot_api)

def _current_user():
    return request.args.get("user") or "DEMO_USER"

@app.route("/")
def index():
    conn = db.get_conn()
    schedule = conn.execute("SELECT * FROM schedule WHERE user_id=? ORDER BY day_of_week, start_time", (_current_user(),)).fetchall()
    notes = conn.execute("SELECT * FROM notes WHERE user_id=? ORDER BY ts DESC LIMIT 30", (_current_user(),)).fetchall()
    conn.close()
    return render_template("index.html", schedule=[dict(r) for r in schedule], notes=[dict(n) for n in notes])

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
        return redirect(url_for("web_settings", user=user_id))
    return render_template("settings.html", user_id=user_id, translate_on=bool(settings.get("translate_on")) if settings else False)

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
    return render_template("news.html", user_id=user_id, keywords=news_service.list_keywords(user_id))

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
        reply = (
            "校園助理 Bot 指令：\\n"
            "/schedule today|tomorrow|week\\n"
            "/note <文字>\\n"
            "/review today\\n"
            "/news add <kw> | /news list | /news remove <kw>\\n"
            "/translate on|off\\n"
        )
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        return

    if text.startswith("/schedule"):
        tokens = text.split()
        when = tokens[1] if len(tokens) > 1 else "today"
        now = datetime.now()
        if when == "today":
            rows = schedule_service.get_day_schedule(user_id, now)
            msg = "今天沒有課表或尚未設定。" if not rows else "【今天課表】\\n" + "\\n".join([f"{r['start_time']}-{r['end_time']} {r['course_name']} @ {r.get('location') or '教室'}" for r in rows])
        elif when == "tomorrow":
            rows = schedule_service.get_day_schedule(user_id, now + timedelta(days=1))
            msg = "明天沒有課表或尚未設定。" if not rows else "【明天課表】\\n" + "\\n".join([f"{r['start_time']}-{r['end_time']} {r['course_name']} @ {r.get('location') or '教室'}" for r in rows])
        else:
            rows = schedule_service.get_week_schedule(user_id, now)
            msg = "本週沒有課表或尚未設定。" if not rows else "【本週課表】\\n" + "\\n".join([f"{r['date']} {r['start_time']}-{r['end_time']} {r['course_name']} @ {r.get('location') or '教室'}" for r in rows][:50])
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
            msg += "\\nAI 重點：\\n" + summary
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
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="關鍵字：\\n" + ("、".join(kws) if kws else "（無）")))
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="用法：/news add <kw> | /news list | /news remove <kw>"))
        return

    if text.startswith("/translate "):
        sub = text.split(maxsplit=1)[1].strip().lower()
        if sub in ("on","off"):
            db.set_translate(user_id, sub == "on")
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"語音翻譯已{'開啟' if sub=='on' else '關閉'}"))
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
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False, suffix=".m4a") as tf:
        for chunk in message_content.iter_content():
            tf.write(chunk)
        temp_path = tf.name

    from services.speech_translate_service import speech_to_text, translate_text
    transcript = speech_to_text(temp_path, language='en-US')
    if not transcript:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="語音辨識失敗，請再試一次。"))
        return
    translated = translate_text(transcript, to_lang='zh-Hant') or "(翻譯失敗)"
    msg = f"🎙️ Transcript:\\n{transcript}\\n\\n🌐 翻譯：\\n{translated}"
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=msg))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
