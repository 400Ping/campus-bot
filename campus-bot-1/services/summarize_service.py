
import os
import google.generativeai as genai

def _maybe_init():
    key = os.environ.get('GEMINI_API_KEY')
    if key:
        genai.configure(api_key=key)
        return genai.GenerativeModel('gemini-1.5-flash')
    return None

def _fallback_note_summary(text: str) -> str | None:
    """當沒有 LLM 時，取內容前幾句作為摘要。"""
    if not text:
        return None
    parts = [p.strip() for p in text.replace("\r", "\n").split("\n") if p.strip()]
    bullets = []
    for p in parts:
        if len(bullets) >= 4:
            break
        if len(p) > 120:
            p = p[:117] + "..."
        bullets.append(f"• {p}")
    if not bullets:
        return None
    return "\n".join(bullets)

def _fallback_review(notes):
    """If LLM 不可用，也提供簡易回顧包，避免回覆空白。"""
    if not notes:
        return None
    lines = []
    lines.append("【摘要】")
    for n in notes[:5]:
        course = n.get("course_name") or "General"
        summary = n.get("summary") or n.get("content") or ""
        lines.append(f"- ({course}) {summary}")
    lines.append("\n【名詞解釋】")
    for n in notes[:5]:
        raw_text = n.get('summary') or n.get('content') or ''
        first_line = raw_text.split('\n')[0][:140]
        course = n.get('course_name') or '課程'
        lines.append(f"- {course}：{first_line}")
    lines.append("\n【可能考點】")
    lines.append("- 依上方摘要自行延伸，AI 無法產生考點（Gemini 未設定或連線失敗）。")
    lines.append("\n【練習題】")
    lines.append("- 嘗試手寫本日筆記的重點與例題解法。")
    return "\n".join(lines)

def summarize_note(text: str):
    model = _maybe_init()
    if not model:
        return _fallback_note_summary(text)
    prompt = f"請用繁體中文幫我把下面的上課筆記整理成 3~5 個重點條列，盡量短句：\n{text}\n"
    try:
        res = model.generate_content(prompt)
        return (res.text or '').strip()
    except Exception:
        return _fallback_note_summary(text)

def build_review_pack(notes):
    if not notes:
        return None
    model = _maybe_init()
    if not model:
        return _fallback_review(notes)
    texts = "\n\n".join([f"[筆記 {i+1}]\n{n['content']}\n(摘要: {n.get('summary') or '無'})" for i, n in enumerate(notes)])
    prompt = f"""以下是今天的多段上課筆記，請以繁體中文產生「重點回顧包」四個區塊：
1) 摘要 (100~200字) 
2) 名詞解釋 (列出重要術語並逐點解釋)
3) 可能考點 (條列重點與易混淆處)
4) 練習題 (3~5 題，附簡短解答或提示)

內容：
{texts}
"""
    try:
        res = model.generate_content(prompt)
        return (res.text or '').strip()
    except Exception:
        return _fallback_review(notes)
