
# Campus Assistant LINE Bot + Website

功能：課表查詢、筆記＋AI重點、回顧包、新聞關鍵字、語音/文字翻譯（Azure STT + Translator）。

## 指令
- `/help`
- `/schedule today|tomorrow|week`
- `/note <文字>`
- `/review today`
- `/news add <kw> | /news list | /news remove <kw>`
- `/translate on [lang]` / `/translate off` / `/translate lang <code>` / `/translate status`
- `/t <text>` 或 `t: <text>`：文字翻譯到目標語言

## Translation commands
- `/translate on [lang]`  開啟語音翻譯（預設 zh-Hant）
- `/translate off`        關閉語音翻譯
- `/translate lang <code>`設定目標語言（zh-Hant|en|ja|ko|de|es|hi）
- `/translate status`     查看狀態
- `/t <text>` 或 `t: <text>` 文字翻譯到目標語言
