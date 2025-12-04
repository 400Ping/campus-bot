
import os
import feedparser
from datetime import datetime
from .db import get_conn

def add_keyword(user_id, kw):
    conn = get_conn()
    conn.execute("INSERT INTO keywords(user_id, keyword) VALUES (?,?)", (user_id, kw))
    conn.commit()
    conn.close()

def remove_keyword(user_id, kw):
    conn = get_conn()
    conn.execute("DELETE FROM keywords WHERE user_id=? AND keyword=?", (user_id, kw))
    conn.commit()
    conn.close()

def list_keywords(user_id):
    conn = get_conn()
    rows = conn.execute("SELECT keyword FROM keywords WHERE user_id=? ORDER BY id DESC", (user_id,)).fetchall()
    conn.close()
    return [r['keyword'] for r in rows]

def _already_sent(url):
    conn = get_conn()
    row = conn.execute("SELECT id FROM news_cache WHERE url=?", (url,)).fetchone()
    conn.close()
    return bool(row)

def _mark_sent(url, title):
    conn = get_conn()
    conn.execute("INSERT OR IGNORE INTO news_cache(url, title, ts) VALUES (?,?,?)", (url, title, datetime.now().isoformat(timespec='seconds')))
    conn.commit()
    conn.close()

def crawl_and_filter(keywords, feeds=None):
    if feeds is None:
        feeds = os.environ.get("NEWS_FEEDS", "").split(",")
        feeds = [f.strip() for f in feeds if f.strip()]
    results = []
    for f in feeds:
        try:
            d = feedparser.parse(f)
            for e in d.entries[:20]:
                title = e.get('title','')
                summary = e.get('summary','')
                url = e.get('link','')
                text = f"{title} {summary}".lower()
                if any(kw.lower() in text for kw in keywords):
                    if url and not _already_sent(url):
                        results.append((title, url))
        except Exception:
            continue
    return results

def record_sent(url, title):
    _mark_sent(url, title)

def add_feed(user_id, url):
    conn = get_conn()
    conn.execute("INSERT INTO feeds(user_id, url) VALUES (?,?)", (user_id, url.strip()))
    conn.commit()
    conn.close()

def remove_feed(user_id, url):
    conn = get_conn()
    conn.execute("DELETE FROM feeds WHERE user_id=? AND url=?", (user_id, url.strip()))
    conn.commit()
    conn.close()

def list_feeds(user_id):
    conn = get_conn()
    rows = conn.execute("SELECT url FROM feeds WHERE user_id=? ORDER BY id DESC", (user_id,)).fetchall()
    conn.close()
    return [r['url'] for r in rows]

def get_feeds_for_user(user_id):
    user_feeds = list_feeds(user_id)
    if user_feeds:
        return user_feeds
    feeds = os.environ.get("NEWS_FEEDS", "").split(",")
    return [f.strip() for f in feeds if f.strip()]
