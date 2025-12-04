
import os
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from pytz import timezone
from services import news_service, schedule_service, db

def start_scheduler(line_bot_api):
    tz = timezone(os.environ.get('TIMEZONE', 'Asia/Taipei'))
    scheduler = BackgroundScheduler(timezone=tz)

    @scheduler.scheduled_job('interval', minutes=60, id='news_crawler')
    def crawl_news():
        from linebot.models import TextSendMessage
        conn = db.get_conn()
        users = conn.execute("SELECT user_id FROM users").fetchall()
        conn.close()
        for u in users:
            user_id = u['user_id']
            kws = news_service.list_keywords(user_id)
            if not kws:
                continue
            feeds = news_service.get_feeds_for_user(user_id)
            items = news_service.crawl_and_filter(kws, feeds=feeds)
            for title, url in items[:5]:
                try:
                    line_bot_api.push_message(user_id, TextSendMessage(text=f"[News] {title}\n{url}"))
                    news_service.record_sent(url, title)
                except Exception:
                    pass

    @scheduler.scheduled_job('interval', minutes=3, id='class_reminders')
    def remind_classes():
        from linebot.models import TextSendMessage
        now = datetime.now(tz)
        conn = db.get_conn()
        users = conn.execute("SELECT * FROM users").fetchall()
        conn.close()
        for u in users:
            user_id = u['user_id']
            if not u['notifications_on']:
                continue
            window = int(u['reminder_window'] or 15)
            upcoming = schedule_service.find_upcoming_classes(user_id, now, within_minutes=window)
            for cl in upcoming:
                msg = f"提醒：{cl['course_name']} 將於 {cl['start_time']} 在 {cl.get('location') or '教室'} 上課喔！"
                try:
                    line_bot_api.push_message(user_id, TextSendMessage(text=msg))
                except Exception:
                    pass

    scheduler.start()
    return scheduler
