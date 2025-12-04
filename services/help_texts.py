TOPICS = {
    "schedule": {
        "title": "課表 (schedule)",
        "body": (
            "用途：查詢/管理課表\n"
            "指令：\n"
            "  /schedule today|tomorrow|week\n"
            "  /schedule add <1-7> <HH:MM-HH:MM> <課程> [@地點]\n"
            "  /schedule list\n"
            "  /schedule remove <id>\n"
            "  /schedule clear all | /schedule clear day <1-7>\n"
            "\n"
            "小撇步：\n"
            "  • 先用 /schedule list 看每筆的 ID 再 remove\n"
            "  • 新增時可加 @地點，例如：/schedule add 3 10:10-12:00 作業系統 @ C303\n"
        )
    },
    "note": {
        "title": "筆記 (note)",
        "body": (
            "用途：新增上課筆記並用 AI 產 3–5 點重點\n"
            "指令：\n"
            "  /note <你的筆記內容>\n"
            "\n"
            "說明：\n"
            "  • 需要 GEMINI_API_KEY 才會附 AI 重點；沒設也會保存筆記\n"
            "  • 可在網站 /web/notes/manage 檢視/新增\n"
        )
    },
    "review": {
        "title": "今日回顧包 (review)",
        "body": (
            "用途：彙整今天的筆記為 4 區塊（摘要/名詞解釋/可能考點/練習題）\n"
            "指令：\n"
            "  /review today\n"
            "\n"
            "說明：\n"
            "  • 需要 GEMINI_API_KEY\n"
            "  • 也可在網站 /web/review 一鍵產生\n"
        )
    },
    "news": {
        "title": "關鍵字新聞 (news)",
        "body": (
            "用途：訂閱關鍵字，系統每小時抓 RSS 命中就推播\n"
            "指令：\n"
            "  /news add <kw>\n"
            "  /news list\n"
            "  /news remove <kw>\n"
            "\n"
            "說明：\n"
            "  • RSS 來源可用 /news feed ... 指令管理，或在網站 /web/news 設定\n"
            "  • 多實例部署需改用雲端排程/鎖避免重複推播\n"
        )
    },
    "feeds": {
        "title": "RSS 來源 (news feed)",
        "body": (
            "用途：每位使用者自訂 RSS 來源（優先於環境變數 NEWS_FEEDS）\n"
            "指令：\n"
            "  /news feed add <url>\n"
            "  /news feed remove <url>\n"
            "  /news feed list\n"
            "\n"
            "說明：\n"
            "  • 網站 /web/news 也能新增/移除 RSS 來源\n"
        )
    },
    "translate": {
        "title": "翻譯 (translate / t:)",
        "body": (
            "用途：開啟語音翻譯（自動語言偵測→翻譯到目標語言）或做文字翻譯\n"
            "指令：\n"
            "  /translate on [lang]\n"
            "  /translate off\n"
            "  /translate lang <code>\n"
            "  /translate status\n"
            "  /t <text> 或 t: <text>\n"
            "\n"
            "說明：\n"
            "  • 語音需要 AZURE_SPEECH_* + ffmpeg；翻譯需要 AZURE_TRANSLATOR_*\n"
            "  • 目標語言在 /settings 或 /web/settings 可改（預設 zh-Hant）\n"
        )
    },
    "link": {
        "title": "帳號連結 (link)",
        "body": (
            "用途：把你的『網站帳號』與『LINE 使用者』綁定，兩邊共用同一組資料。\n"
            "指令：\n"
            "  /link\n"
            "\n"
            "流程：\n"
            "  1) 在 LINE 輸入 /link 取得一組代碼（效期 15 分鐘）\n"
            "  2) 登入網站 → 帳戶 → 連結 LINE 帳號（/account/link-line）\n"
            "  3) 貼上代碼並送出，成功後網站端將改以你的 LINE user id 作為資料鍵值\n"
            "\n"
            "備註：未連結時，網站暫時以 WEB_<account_id> 作為使用者 ID。\n"
        )
    },
    "settings": {
        "title": "設定 (settings)",
        "body": (
            "用途：查/改個人設定（翻譯、提醒）\n"
            "指令：\n"
            "  /settings\n"
            "  /settings reminder on|off\n"
            "  /settings window <分鐘>\n"
            "  /settings tz <Asia/Taipei>\n"
            "\n"
            "說明：\n"
            "  • 網站 /web/settings 也能設定相同內容\n"
        )
    },
    "shortcuts": {
        "title": "常用捷徑 (shortcuts)",
        "body": (
            "• 連結帳號：/link → 然後到網站 /account/link-line 貼代碼\n"
            "• 今天課表：/schedule today\n"
            "• 新增筆記：/note 今天 OS 講到 deadlock 預防…\n"
            "• 今日回顧包：/review today\n"
            "• 開啟語音翻譯：/translate on zh-Hant（然後傳語音）\n"
            "• 文字翻譯：/t 早上好\n"
        )
    },
}

ALIASES = {
    "sch": "schedule",
    "notes": "note",
    "rev": "review",
    "feed": "feeds",
    "f": "feeds",
    "tr": "translate",
    "set": "settings",
    "sc": "shortcuts",
    "connect": "link",
    "bind": "link",
    "綁定": "link",
    "連結": "link",
}

def list_topics():
    return [
        "schedule",
        "note",
        "review",
        "news",
        "feeds",
        "translate",
        "link",
        "settings",
        "shortcuts",
    ]

def get_help(topic: str | None) -> str:
    if not topic:
        topics = list_topics()
        body = "可用主題：\n" + "\n".join([f"  - {t}" for t in topics]) + "\n\n使用：/help <topic> 例如：/help link"
        return body
    t = topic.lower().strip()
    t = ALIASES.get(t, t)
    data = TOPICS.get(t)
    if not data:
        return f"沒有找到主題 `{topic}`。輸入 /help 看所有主題。"
    return f"[{data['title']}]\n{data['body']}"
