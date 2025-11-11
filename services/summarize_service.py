
import os
import google.generativeai as genai

def _maybe_init():
    key = os.environ.get('GEMINI_API_KEY')
    if key:
        genai.configure(api_key=key)
        return genai.GenerativeModel('gemini-1.5-flash')
    return None

def summarize_note(text: str):
    model = _maybe_init()
    if not model:
        return None
    prompt = f"請用繁體中文幫我把下面的上課筆記整理成 3~5 個重點條列，盡量短句：\n{text}\n"
    try:
        res = model.generate_content(prompt)
        return (res.text or '').strip()
    except Exception:
        return None

def build_review_pack(notes):
    model = _maybe_init()
    if not model or not notes:
        return None
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
        return None
