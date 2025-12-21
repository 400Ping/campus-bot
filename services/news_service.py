
import os
import feedparser
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
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

def crawl_and_filter(keywords, feeds=None, include_sent=False):
    if feeds is None:
        feeds = os.environ.get("NEWS_FEEDS", "").split(",")
        feeds = [f.strip() for f in feeds if f.strip()]
    results = []
    for f in feeds:
        try:
            d = feedparser.parse(f)
            entries = list(d.entries[:50])
            # 若 feedparser 沒抓到，嘗試簡單 HTML 解析
            if not entries:
                entries = _scrape_html_links(f, limit=200)
            for e in entries:
                title = e.get('title','')
                summary = e.get('summary','') or e.get('desc','')
                url = e.get('link','') or e.get('url','')
                text = f"{title} {summary}".lower()
                if any(kw.lower() in text for kw in keywords):
                    if not url:
                        continue
                    if include_sent or not _already_sent(url):
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

def _scrape_html_links(feed_url, limit=30):
    """Fallback：對非 RSS 頁面簡單抓取 <a> 連結作為項目。"""
    try:
        resp = requests.get(feed_url, timeout=8)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        links = []
        for a in soup.find_all("a"):
            title = (a.get_text() or "").strip()
            href = a.get("href")
            if not title or not href:
                continue
            if href.startswith("#"):
                continue
            if len(title) < 4:
                continue
            links.append({
                "title": title,
                "summary": "",
                "link": urljoin(feed_url, href),
                "feed": feed_url,
            })
            if len(links) >= limit:
                break
        return links
    except Exception:
        return []

def search_news(user_id, query: str, limit_per_feed: int = 15):
    """即時從使用者的來源抓資料並搜尋 query（標題+摘要）。"""
    feeds = get_feeds_for_user(user_id)
    if not feeds or not query:
        return []
    q = query.lower()
    matches = []
    for f in feeds:
        try:
            d = feedparser.parse(f)
            entries = list(d.entries[: max(limit_per_feed, 50)])
            if not entries:
                entries = _scrape_html_links(f, limit=200)
            for e in entries:
                title = e.get("title", "")
                summary = e.get("summary", "") or e.get("desc","")
                url = e.get("link", "") or e.get("url","")
                text = f"{title} {summary}".lower()
                if q in text:
                    matches.append(
                        {
                            "title": title,
                            "summary": summary,
                            "url": url,
                            "feed": f,
                            "published": e.get("published", "") or "",
                        }
                    )
        except Exception:
            continue
    return matches
