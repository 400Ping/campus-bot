import os
import uuid
import requests
import azure.cognitiveservices.speech as speechsdk


# ===== 語音辨識：給定 wav 檔，並自動偵測語言 =====
def speech_to_text_auto(
    audio_file_path: str,
    possible_languages: list[str] | None = None,
) -> tuple[str | None, str | None]:
    """
    傳回 (transcript, detected_language)
    transcript 為辨識文字（失敗時 None）
    detected_language 為像 "en-US" 這樣的語言代碼（失敗時 None）
    注意：Azure DetectAudioAtStart 模式一次最多只支援 4 個語言。
    """
    key = os.environ.get("AZURE_SPEECH_KEY")
    region = os.environ.get("AZURE_SPEECH_REGION")

    if not key or not region:
        print("[speech_to_text_auto] AZURE_SPEECH_KEY / REGION 未設定")
        return None, None

    # 預設候選語言（這裡只放 4 個，符合 Azure 限制）
    if not possible_languages:
        possible_languages = [
            "en-US",  # 英文
            "zh-TW",  # 繁體中文
            "ja-JP",  # 日文
            "ko-KR",  # 韓文
        ]

    # 保險起見，如果外面傳進來超過 4 個，就只取前 4 個
    if len(possible_languages) > 4:
        print(
            "[speech_to_text_auto] WARNING: possible_languages 超過 4 個，"
            "依 Azure 限制只會取前 4 個：", possible_languages[:4]
        )
        possible_languages = possible_languages[:4]

    print("[speech_to_text_auto] 使用語言列表:", possible_languages)
    print("[speech_to_text_auto] 音檔路徑:", audio_file_path)

    try:
        speech_config = speechsdk.SpeechConfig(
            subscription=key,
            region=region,
        )

        audio_config = speechsdk.audio.AudioConfig(filename=audio_file_path)

        auto_detect = speechsdk.languageconfig.AutoDetectSourceLanguageConfig(
            languages=possible_languages
        )

        recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config,
            auto_detect_source_language_config=auto_detect,
            audio_config=audio_config,
        )

        result = recognizer.recognize_once()
        print("[speech_to_text_auto] result.reason:", result.reason)

        if result.reason == speechsdk.ResultReason.RecognizedSpeech:
            detected_lang = result.properties.get(
                speechsdk.PropertyId.SpeechServiceConnection_AutoDetectSourceLanguageResult
            )
            print("[speech_to_text_auto] recognized text:", result.text)
            print("[speech_to_text_auto] detected_lang:", detected_lang)
            return result.text, detected_lang

        elif result.reason == speechsdk.ResultReason.NoMatch:
            print("[speech_to_text_auto] NoMatch:", result.no_match_details)
            return None, None

        elif result.reason == speechsdk.ResultReason.Canceled:
            cancellation_details = result.cancellation_details
            print("[speech_to_text_auto] Canceled:", cancellation_details.reason)
            print("[speech_to_text_auto] Error details:", cancellation_details.error_details)
            return None, None

        else:
            print("[speech_to_text_auto] 未知 result.reason:", result.reason)
            return None, None

    except Exception as e:
        print("[speech_to_text_auto] Exception:", repr(e))
        return None, None



# ===== 文字翻譯：用 Azure Translator =====
def translate_text(text: str, to_lang: str = "zh-Hant") -> str | None:
    endpoint = os.environ.get("AZURE_TRANSLATOR_ENDPOINT")
    key = os.environ.get("AZURE_TRANSLATOR_KEY")
    region = os.environ.get("AZURE_TRANSLATOR_REGION")

    if not endpoint or not key:
        print("[translate_text] AZURE_TRANSLATOR_* 未設定")
        return None

    path = "/translate"
    params = {
        "api-version": "3.0",
        "to": to_lang,
    }
    headers = {
        "Ocp-Apim-Subscription-Key": key,
        "Ocp-Apim-Subscription-Region": region,
        "Content-type": "application/json",
        "X-ClientTraceId": str(uuid.uuid4()),
    }
    body = [{"text": text}]

    try:
        r = requests.post(
            endpoint + path,
            params=params,
            headers=headers,
            json=body,
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        print("[translate_text] raw response:", data)
        return data[0]["translations"][0]["text"]
    except Exception as e:
        print("[translate_text] Exception:", repr(e))
        return None
