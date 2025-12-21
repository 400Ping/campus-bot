import io
import json
import os

import google.generativeai as genai
from PIL import Image


def _get_model():
    """Configure and return the Gemini model; returns None if missing key."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        print("錯誤：找不到 GEMINI_API_KEY")
        return None
    genai.configure(api_key=key)
    return genai.GenerativeModel("gemini-2.5-flash")


def _stitch_images(image_bytes_list):
    """Vertically stitch multiple image bytes into one long image."""
    images = []
    try:
        for b in image_bytes_list:
            img = Image.open(io.BytesIO(b))
            images.append(img)
    except Exception as e:
        print(f"圖片讀取錯誤: {e}")
        return None

    if not images:
        return None

    total_width = max(img.width for img in images)
    total_height = sum(img.height for img in images)
    new_im = Image.new("RGB", (total_width, total_height), (255, 255, 255))

    y_offset = 0
    for img in images:
        new_im.paste(img, (0, y_offset))
        y_offset += img.height

    return new_im


def parse_schedule_from_images(image_bytes_list):
    """Parse schedule entries from a list of image bytes via Gemini OCR."""
    model = _get_model()
    if not model or not image_bytes_list:
        return []

    try:
        stitched_image = _stitch_images(image_bytes_list)
        if not stitched_image:
            return []

        prompt = """
        請扮演一個課表輸入助理。這是一張由多張截圖拼接而成的長條課表圖片。
        請分析圖片，提取所有課程資訊。
        
        請直接回傳一個純 JSON Array (不要用 Markdown ```json )，格式如下：
        [
          {
            "course_name": "課程名稱",
            "day_of_week": 數字(1=週一, 7=週日),
            "start_time": "HH:MM",
            "end_time": "HH:MM",
            "location": "教室地點(若無則null)"
          }
        ]
        
        注意：
        1. 時間請轉為 24 小時制 (HH:MM)。
        2. 如果圖片只寫「第1節」，請幫我轉換成 "08:10" 開始、"09:00" 結束 (依此類推)。
        3. 如果無法辨識或圖片不是課表，請回傳空陣列 []。
        4. 【重要】合併跨頁與連續課程：
           - 由於圖片是拼接的，請忽略拼接處的斷層。
           - 若同一天、同一門課連續上多節（例如 13:00-14:00 和 14:00-15:00 都是「作業系統」），
             請務必將其合併為「單一筆資料」(13:00-15:00)。
           - 不要回傳多筆分開的片段。
        5. 遇到課程名稱換行的話也請不要在中間加入空格。
        """

        response = model.generate_content([prompt, stitched_image])
        text = response.text.strip()

        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]

        data = json.loads(text.strip())
        return data
    except Exception as e:
        print(f"OCR 辨識失敗: {e}")
        return []
