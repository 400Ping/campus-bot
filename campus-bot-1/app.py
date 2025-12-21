
import os, io, tempfile, csv
from datetime import datetime, timedelta
from flask import Flask, request, abort, render_template, redirect, url_for, session, flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from dotenv import load_dotenv
from pydub import AudioSegment 


load_dotenv()

from services import db, schedule_service, notes_service, review_service, news_service, ocr_service
db.init_db()

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, AudioMessage, TextSendMessage, ImageMessage

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

PERIOD_MAP = {
    "1": ("08:10", "09:00"),
    "2": ("09:10", "10:00"),
    "3": ("10:10", "11:00"),
    "4": ("11:10", "12:00"),
    "5": ("12:10", "13:00"),
    "6": ("13:10", "14:00"),
    "7": ("14:10", "15:00"),
    "8": ("15:10", "16:00"),
    "9": ("16:10", "17:00"),
    "10": ("17:10", "18:00"),
    "11": ("18:30", "19:20"),
    "12": ("19:30", "20:20"),
    "13": ("20:30", "21:20"),
}
USER_STATES = {}
USER_IMG_BUFFER = {}

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
    """取得目前資料鍵值；優先使用登入的 LINE user_id 或 WEB_<account_id>，再 fallback URL ?user= 或 DEMO_USER。"""
    uid = _active_user_id()
    return uid or "DEMO_USER"

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
    user_id = _current_user()
    
    # 1. 取得原始列表 (這部分保持原本邏輯，用於下方的清單顯示)
    schedule_list = schedule_service.get_indexed_schedule(user_id)
    schedule_list.sort(key=lambda x: (x['day_of_week'], x['start_time']))
    
    # 2. === 準備格狀課表資料 ===
    
    # 定義節次資訊 (由 1 到 13)
    periods = []
    for i in range(1, 14):
        p_key = str(i)
        if p_key in PERIOD_MAP:
            s, e = PERIOD_MAP[p_key]
            periods.append({
                "index": i,
                "label": f"第 {i} 節",
                "time_str": f"{s}<br>|<br>{e}",
                "start": s,
                "end": e
            })

    # 初始化 13列 x 7行 的空二維陣列
    # grid[節次索引 0~12][星期索引 0~6]
    grid = [[None for _ in range(7)] for _ in range(13)]

    # 簡單的時間重疊判斷函式
    def is_overlap(c_start, c_end, p_start, p_end):
        # 字串比對 "08:10" >= "08:00" 是可行的
        return max(c_start, p_start) < min(c_end, p_end)

    # 將每堂課填入格子
    for course in schedule_list:
        # 轉成 0-based index (週一=0, 週日=6)
        dow_idx = int(course['day_of_week']) - 1
        if not (0 <= dow_idx <= 6): continue

        c_start = course['start_time']
        c_end = course['end_time']

        # 檢查這堂課跨越了哪些節次
        for p_idx, p in enumerate(periods):
            if is_overlap(c_start, c_end, p['start'], p['end']):
                # 如果格子已經有課，就用 / 串接 (處理衝堂顯示)
                cell_data = {
                    'name': course['course_name'],
                    'loc': course['location'],
                    'id': course['display_id']
                }
                
                if grid[p_idx][dow_idx]:
                    # 若重疊，將名稱合併顯示
                    grid[p_idx][dow_idx]['name'] += f" / {cell_data['name']}"
                else:
                    grid[p_idx][dow_idx] = cell_data

    # 回傳給網頁
    return render_template("schedule.html", 
                           schedule=schedule_list, 
                           periods=periods, 
                           grid=grid)
@app.route("/web/notes")
def web_notes():
    notes_service.ensure_summaries(_current_user(), limit=30)
    conn = db.get_conn()
    notes = conn.execute("SELECT * FROM notes WHERE user_id=? ORDER BY ts DESC", (_current_user(),)).fetchall()
    conn.close()
    return render_template("notes.html", notes=[dict(n) for n in notes])

@app.route("/web/notes/<int:note_id>")
def web_note_detail(note_id):
    user_id = _current_user()
    # 若該筆缺摘要，嘗試補一次（用 Gemini 或 fallback）
    notes_service.ensure_summaries(user_id, limit=500)
    note = notes_service.get_note(user_id, note_id)
    if not note:
        return "筆記不存在或無權限查看", 404
    today_pack = review_service.generate_review_for_date(user_id, datetime.now())
    return render_template("note_detail.html", note=note, today_pack=today_pack)

@app.route("/web/notes/<int:note_id>/regen", methods=["POST"])
def web_note_regen(note_id):
    user_id = _current_user()
    # 用當天回顧包當作單筆摘要，與 /review today 對齊
    today_pack = review_service.generate_review_for_date(user_id, datetime.now())
    updated = notes_service.regenerate_note_summary(user_id, note_id, new_summary=today_pack)
    if not updated:
        return "筆記不存在或無權限操作", 404
    return redirect(url_for("web_note_detail", note_id=note_id, user=user_id))

@app.route("/web/notes/<int:note_id>/delete", methods=["POST"])
def web_note_delete(note_id):
    user_id = _current_user()
    deleted = notes_service.delete_note(user_id, note_id)
    if not deleted:
        return "筆記不存在或無權限操作", 404
    return redirect(url_for("web_notes", user=user_id))

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
    notes_service.ensure_summaries(user_id, limit=50)
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
    q = request.args.get("q", "").strip()
    results = news_service.search_news(user_id, q, limit_per_feed=10) if q else []
    return render_template(
        "news.html",
        user_id=user_id,
        keywords=news_service.list_keywords(user_id),
        feeds=news_service.list_feeds(user_id),
        query=q,
        results=results,
    )

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
    schedule = schedule_service.get_indexed_schedule(user_id)
    schedule.sort(key=lambda x: (x['day_of_week'], x['start_time']))
    return render_template(
        "schedule_manage.html", 
        schedule=schedule, 
        user_id=user_id,
        form_data={},       
        error_msg=None,
        error_field=None
    )
@app.route("/web/schedule/add", methods=["POST"])
def web_schedule_add():
    user_id = request.form.get("user") or "DEMO_USER"
    form_data = request.form # 保存使用者填寫的資料
    
    try:
        schedule_service.add_course(
            user_id=user_id,
            course_name=request.form.get("course_name"),
            dow=int(request.form.get("day_of_week")),
            start_time=request.form.get("start_time"),
            end_time=request.form.get("end_time"),
            location=request.form.get("location") or None
        )
        flash("課程新增成功！", "success")
        return redirect(url_for("web_schedule_manage", user=user_id))
        
    except ValueError as e:
        # === 發生錯誤時，留在原頁面並顯示紅字 ===
        err_msg = str(e)
        
        # 簡單判斷錯誤欄位
        error_field = "end_time" if "結束" in err_msg else "start_time"
        
        # 重新抓取課表以便顯示列表
        conn = db.get_conn()
        schedule = conn.execute("SELECT * FROM schedule WHERE user_id=? ORDER BY day_of_week, start_time", (user_id,)).fetchall()
        conn.close()
        
        return render_template(
            "schedule_manage.html",
            user_id=user_id,
            schedule=[dict(r) for r in schedule],
            error_msg=err_msg,       # 錯誤訊息
            error_field=error_field, # 錯誤欄位
            form_data=form_data      # 回填資料
        )
    except Exception as e:
        flash(f"系統錯誤: {e}", "error")
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

@app.route("/web/schedule/upload-images", methods=["POST"])
def web_schedule_upload_images():
    user_id = _current_user()
    
    # 1. 抓取上傳的檔案 (對應 HTML 的 name="images")
    files = request.files.getlist("images")
    if not files:
        flash("未選擇任何圖片", "error")
        return redirect(url_for("web_schedule_manage", user=user_id))

    # 2. 讀取圖片內容
    image_bytes_list = []
    for f in files:
        if f.filename == '': continue
        image_bytes_list.append(f.read())
    
    if not image_bytes_list:
        flash("圖片讀取失敗或無有效內容", "error")
        return redirect(url_for("web_schedule_manage", user=user_id))

    try:
        # 3. 呼叫 OCR 服務 (需確保已 import ocr_service)
        # 這裡會自動拼接圖片並呼叫 Gemini
        courses = ocr_service.parse_schedule_from_images(image_bytes_list)
        
        if not courses:
            flash("AI 未能辨識出任何課程，請確認圖片清晰度或格式。", "error")
            return redirect(url_for("web_schedule_manage", user=user_id))

        # 4. 寫入資料庫
        success_count = 0
        fail_msg = []
        
        for c in courses:
            try:
                if not c.get('course_name') or not c.get('start_time'): 
                    continue
                
                schedule_service.add_course(
                    user_id, 
                    course_name=c['course_name'], 
                    dow=int(c['day_of_week']), 
                    start_time=c['start_time'], 
                    end_time=c['end_time'], 
                    location=c.get('location')
                )
                success_count += 1
            except ValueError as ve:
                fail_msg.append(f"• {c.get('course_name')}: {str(ve)}")
            except Exception:
                pass

        # 5. 回報結果
        if success_count > 0:
            flash(f"🎉 成功匯入 {success_count} 堂課程！", "success")
        
        if fail_msg:
            flash("部分失敗：" + " ".join(fail_msg[:3]), "error")

    except Exception as e:
        print(f"Web OCR Error: {e}")
        flash(f"系統發生錯誤: {e}", "error")

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

    if USER_STATES.get(user_id) == "WAIT_SCHEDULE_IMG":
        # 如果使用者說完成，才開始辨識
        if text.lower() in ["完成", "done", "ok", "沒有", "沒有了", "結束", "no"]:
            
            # 取出暫存的圖片們
            images = USER_IMG_BUFFER.get(user_id, [])
            
            if not images:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="您還沒有上傳任何圖片！請傳送圖片。"))
                return

            # 【修改點 1】移除原本的「辨識中...」回覆，改為後台紀錄
            print(f"使用者 {user_id} 輸入完成，開始辨識 {len(images)} 張圖片...") 
            
            # 呼叫 ocr_service.parse_schedule_from_images
            courses = ocr_service.parse_schedule_from_images(images)
            
            # 寫入資料庫
            success_count = 0
            fail_msg = []
            for c in courses:
                try:
                    if not c.get('course_name') or not c.get('start_time'): continue
                    schedule_service.add_course(
                        user_id, c['course_name'], int(c['day_of_week']), 
                        c['start_time'], c['end_time'], c.get('location')
                    )
                    success_count += 1
                except ValueError as ve:
                    fail_msg.append(f"• {c['course_name']}: {str(ve)}")
                except Exception:
                    pass

            # 清除狀態與暫存
            del USER_STATES[user_id]
            if user_id in USER_IMG_BUFFER: del USER_IMG_BUFFER[user_id]

            # 【修改點 2】辨識完畢後，才使用唯一的 Reply Token 回報結果
            reply = f"辨識完成！共加入 {success_count} 堂課程。"
            if fail_msg: reply += "\n部分失敗：\n" + "\n".join(fail_msg[:3])
            
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
            return

        # 如果不是指令，且不是「完成」，則提示繼續傳 (或者您也可以選擇這裡也安靜)
        if not text.startswith("/"):
            count = len(USER_IMG_BUFFER.get(user_id, []))
            # 這裡維持簡單提示，以免使用者以為機器人當機
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"已收集 {count} 張。請繼續傳下一張，傳完請輸入「完成」。"))
            return
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
                parts = payload.split()
                
                if len(parts) < 3:
                    raise Exception("參數不足") 

                dow = int(parts[0])      # 星期幾
                period = parts[1]        # 節次 (1, 2-4, 09:00-12:00)
                rest = " ".join(parts[2:]) 
                
                # 解析地點
                course = rest
                location = None
                if "@" in rest:
                    course, location = [x.strip() for x in rest.split("@", 1)]

                # === 時間解析邏輯 (支援連續節次) ===
                if period in PERIOD_MAP:
                    # 情況 1: 單節次 (例如 "3")
                    start, end = PERIOD_MAP[period]
                    
                elif "-" in period:
                    # 切割減號前後
                    p_start, p_end = period.split("-")
                    
                    # 情況 2: 連續節次 (例如 "2-4") -> 判斷前後是否都是節次代號
                    if p_start in PERIOD_MAP and p_end in PERIOD_MAP:
                        start = PERIOD_MAP[p_start][0] # 拿第 2 節的「開始時間」
                        end = PERIOD_MAP[p_end][1]     # 拿第 4 節的「結束時間」
                    else:
                        # 情況 3: 手動時間 (例如 "09:00-12:00")
                        start, end = p_start, p_end
                else:
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"錯誤節次： '{period}' 請輸入 1~13, 2-4 或 09:00-12:00 格式。"))
                    return
                # =================================

                # 呼叫 Service (含衝堂檢查)
                schedule_service.add_course(user_id, course_name=course, dow=dow, start_time=start, end_time=end, location=location)
                
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"已新增週{dow} ({start}-{end}) 的 {course}。"))
            
            except ValueError as e:
                # 捕捉衝堂檢查的錯誤
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=str(e)))
            except Exception as e:
                print(f"Error: {e}")
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="用法：\n/schedule add <週1-7> <節次範圍> <課程> [@地點]\n範例：/schedule add 3 2-4 電子學 @ R102\n節次範圍可輸入：1~13, 2-4 或 09:00-12:00格式"))
            return
        if text == "/schedule list":
            # Service 直接給我們整理好的資料 (含 index)
            rows = schedule_service.get_indexed_schedule(user_id)
            rows.sort(key=lambda x: (x['day_of_week'], x['start_time']))
            if not rows:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="尚無課表資料。"))
            else:
                # 直接拿 r['index'] 來顯示
                lines = [f"#{r['display_id']} {r['course_name']} (週{r['day_of_week']} {r['start_time']})" for r in rows]
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="\n".join(lines)))
            return
        if text.startswith("/schedule remove "):
            try:
                idx = int(text.split()[2])
                deleted_name = schedule_service.remove_course_by_index(user_id, idx)
                
                line_bot_api.reply_message(event.reply_token, TextSendMessage(
                    text=f"已刪除 #{idx} {deleted_name}。\n"
                ))
            except ValueError as e:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=str(e)))
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
        if text == "/schedule upload image":
            if schedule_service.list_schedule(user_id):
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="課表已有資料，請先清空。"))
            
            # 設定狀態 & 初始化 Buffer
            USER_STATES[user_id] = "WAIT_SCHEDULE_IMG"
            USER_IMG_BUFFER[user_id] = []  # <--- [關鍵] 建立空列表
            
            line_bot_api.reply_message(
                event.reply_token, 
                TextSendMessage(text="請依序傳送課表圖片\n\n全部傳完後，請輸入「完成」")
            )
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
        payload = text[len("/note"):].strip()
        web_notes_url = (os.environ.get("HOST_BASE_URL") or "http://localhost:5000") + "/web/notes/manage"
        if not payload or payload.lower() in ("help", "?"):
            msg = ("筆記指令：\n"
                   "/note <內容> → 新增筆記並產重點\n"
                   "/note today → 查看今天筆記\n"
                   "/note list [N] → 查看最近 N 筆（預設 5）\n"
                   f"網頁版管理：{web_notes_url}")
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=msg))
            return

        tokens = payload.split()
        sub = tokens[0].lower()

        if sub in ("list", "ls"):
            try:
                limit = int(tokens[1]) if len(tokens) >= 2 else 5
            except Exception:
                limit = 5
            notes = notes_service.list_notes(user_id, limit=max(1, min(limit, 50)))
            if not notes:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="尚無筆記，可以用 /note <內容> 新增。"))
                return
            lines = []
            for n in notes:
                ts = (n.get("ts") or "")[5:16]
                course = n.get("course_name") or "General"
                summary = (n.get("summary") or n.get("content") or "").replace("\n", " ")
                if len(summary) > 80:
                    summary = summary[:77] + "..."
                lines.append(f"{ts} {course}｜{summary}")
            body = "【近期筆記】\n" + "\n".join(lines)
            body += f"\n\n在網頁查看完整內容：{web_notes_url}"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=body))
            return

        if sub in ("today", "tod"):
            today_notes = notes_service.get_notes_for_date(user_id, datetime.now())
            if not today_notes:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="今天還沒有筆記。用 /note <內容> 立即新增！"))
                return
            chunks = []
            for n in today_notes:
                course = n.get("course_name") or "General"
                ts = (n.get("ts") or "")[11:16]
                summary = n.get("summary") or "(無 AI 重點)"
                chunks.append(f"[{ts} {course}]\n{n.get('content','')}\nAI 重點：{summary}")
            msg = "【今天的筆記】\n" + "\n\n".join(chunks)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=msg[:4000]))
            return

        if sub in ("add", "+") and len(tokens) >= 2:
            content = payload[len(tokens[0]):].strip()
        else:
            content = payload

        if not content:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="請在 /note 後面接上筆記內容。"))
            return

        summary = notes_service.add_note(user_id, content, course_name=None)
        msg = "已新增筆記。"
        if summary:
            msg += "\nAI 重點：\n" + summary
        msg += f"\n\n在網頁管理：{web_notes_url}"
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
        elif sub == "refresh":
            kws = news_service.list_keywords(user_id)
            if not kws:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="尚未設定關鍵字，可先用 /news add <kw>。"))
                return
            feeds = news_service.get_feeds_for_user(user_id)
            hits = news_service.crawl_and_filter(kws, feeds=feeds)
            if not hits:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="目前沒有符合關鍵字的最新新聞。"))
            else:
                body = "【即時刷新】\n" + "\n".join([f"- {t}\n  {u}" for t, u in hits[:5]])
                for title, url in hits:
                    news_service.record_sent(url, title)
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=body[:4000]))
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
    if not settings or not settings.get("translate_on"):
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="語音翻譯未開啟。請輸入 /translate on"),
        )
        return

    # 1) 從 LINE 把 m4a 抓下來
    message_content = line_bot_api.get_message_content(event.message.id)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".m4a") as tf:
        for chunk in message_content.iter_content():
            tf.write(chunk)
        m4a_path = tf.name

    # 2) m4a → wav（Azure 對 wav 最穩）
    wav_path = m4a_path + ".wav"
    try:
        audio = AudioSegment.from_file(m4a_path)
        audio.export(wav_path, format="wav")
    except Exception as e:
        print("[handle_audio_message] m4a -> wav 失敗:", e)
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="語音檔轉換失敗，請再試一次 QQ"),
        )
        return

    # 3) 丟給 speech_to_text_auto（裡面會自己限制最多 4 種語言）
    from services.speech_translate_service import speech_to_text_auto, translate_text

    # 這裡直接用預設語言列表（en / zh / ja / ko），如果你在 service 裡有寫預設就不用傳
    transcript, detected = speech_to_text_auto(wav_path)
    if not transcript:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="語音辨識失敗，請再試一次。"),
        )
        return

    # 4) 依照 DB 中設定的目標語言翻譯
    target = _get_target_lang(user_id)
    translated = translate_text(transcript, to_lang=target) or "(翻譯失敗)"
    det = detected or "unknown"

    msg = (
        f"🎙️ Detected: {det}\n"
        f"Transcript:\n{transcript}\n\n"
        f"🌐 → {target}\n"
        f"{translated}"
    )
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=msg))
@handler.add(MessageEvent, message=ImageMessage)
def handle_image_message(event):
    user_id = event.source.user_id
    db.ensure_user(user_id)

    # 1. 狀態檢查
    if USER_STATES.get(user_id) != "WAIT_SCHEDULE_IMG":
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="若要上傳課表，請先輸入指令：\n/schedule upload image")
        )
        return

    # 2. 靜默接收圖片並暫存
    try:
        message_content = line_bot_api.get_message_content(event.message.id)
        image_bytes = b""
        for chunk in message_content.iter_content():
            image_bytes += chunk

        # 將圖片 bytes 加入使用者的暫存列表
        if user_id not in USER_IMG_BUFFER:
            USER_IMG_BUFFER[user_id] = []
        
        USER_IMG_BUFFER[user_id].append(image_bytes)
        count = len(USER_IMG_BUFFER[user_id])

        # 【修改點】這裡只在後台印出紀錄，不再回覆使用者，避免干擾
        print(f"[Silent] 已收到使用者 {user_id} 的第 {count} 張圖片")

    except Exception as e:
        print(f"Image Receive Error: {e}")
        # 出錯時才回覆
        line_bot_api.reply_message(
            event.reply_token, 
            TextSendMessage(text="圖片接收失敗，請重試。")
        )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5001"))
    app.run(host="0.0.0.0", port=port, debug=True)
