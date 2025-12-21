
# Campus Assistant LINE Bot + Website (Full Parity)

功能：課表查詢/管理、筆記＋AI重點、回顧包、新聞關鍵字＋自訂來源（RSS/網頁）、語音/文字翻譯。  
網站與 LINE Bot 皆可設定相同的功能（設定雙向一致）。

## Quickstart
```
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # 填金鑰
python services/seed_data.py
python app.py
```

## LINE 指令速查
- `/help`
- 課表：
  - `/schedule today|tomorrow|week`
  - `/schedule add <dow> <HH:MM-HH:MM> <course> [@location]`
  - `/schedule list`
  - `/schedule remove <id>`
  - `/schedule clear all` 或 `/schedule clear day <1-7>`
- 筆記：`/note 文字`
- 回顧包：`/review today`
- 新聞關鍵字：`/news add <kw> | /news list | /news remove <kw>`
- 來源管理：`/news feed add <url> | /news feed remove <url> | /news feed list`
- 翻譯：
  - `/translate on [lang]`、`/translate off`、`/translate lang <code>`、`/translate status`
  - 文字翻譯：`/t 文字` 或 `t: 文字`
- 設定彙整：
  - `/settings`（查看狀態）
  - `/settings reminder on|off`
  - `/settings window <分鐘>`
  - `/settings tz <Asia/Taipei>`

## 網站路徑
- `/web/schedule`、`/web/schedule/manage`（新增/刪除/CSV 匯入）
- `/web/notes/manage`
- `/web/news`（關鍵字 + 自訂來源）
- `/web/review`
- `/web/settings`（翻譯、提醒開關/分鐘、目標語言）

## 佈署
- Gunicorn/Procfile 已備好；Azure App Service 建議：
```
bash -c 'mkdir -p /home/site/db && gunicorn -c gunicorn_config.py app:app'
```
- 設定 `DB_PATH=/home/site/db/db.sqlite3`、`TIMEZONE=Asia/Taipei` 等。
