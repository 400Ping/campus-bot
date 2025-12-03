# services/speech_translate_service.py

import os
import uuid
import requests
import azure.cognitiveservices.speech as speechsdk


def speech_to_text(
    audio_file_path: str,
    language: str = "en-US",
) -> str | None:
    """
    固定語言的語音辨識（目前沒用到，但保留）。
    """
    key = os.environ.get("AZURE_SPEECH_KEY")
    region = os.environ.get("AZURE_SPEECH_REGION")

    if not key or not region:
        print("[speech_to_text] Missing AZURE_SPEECH_KEY or AZURE_SPEECH_REGION")
        return None

    try:
        speech_config = speechsdk.SpeechConfig(subscription=key, region=region)
        speech_config.speech_recognition_language = language

        audio_config = speechsdk.audio.AudioConfig(filename=audio_file_path)
        recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config,
            audio_config=audio_config,
        )
        result = recognizer.recognize_once()

        print("[speech_to_text] Result reason:", result.reason)
        if result.reason == speechsdk.ResultReason.RecognizedSpeech:
            print("[speech_to_text] Recognized:", result.text)
            return result.text
        else:
            print("[speech_to_text] No recognized speech.")
            return None
    except Exception as e:
        print(f"[speech_to_text] Exception: {e}")
        return None


def speech_to_text_auto(
    audio_file_path: str,
    possible_languages: list[str] | None = None,
) -> tuple[str | None, str | None]:
    """
    自動偵測語音語言的語音辨識。

    :param audio_file_path: wav 檔路徑
    :param possible_languages: 可能出現的語言清單（Speech 要你先給候選）
           例如 ["en-US", "zh-TW", "ja-JP"]
    :return: (辨識出的文字, 偵測出的語言代碼)
    """
    key = os.environ.get("AZURE_SPEECH_KEY")
    region = os.environ.get("AZURE_SPEECH_REGION")

    if not key or not region:
        print("[speech_to_text_auto] Missing AZURE_SPEECH_KEY or AZURE_SPEECH_REGION")
        return None, None

    if not possible_languages:
        possible_languages = ["en-US", "zh-TW", "ja-JP"]

    try:
        speech_config = speechsdk.SpeechConfig(subscription=key, region=region)

        auto_detect_source_language_config = (
            speechsdk.languageconfig.AutoDetectSourceLanguageConfig(
                languages=possible_languages
            )
        )

        audio_config = speechsdk.audio.AudioConfig(filename=audio_file_path)

        recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config,
            auto_detect_source_language_config=auto_detect_source_language_config,
            audio_config=audio_config,
        )

        result = recognizer.recognize_once()
        print("[speech_to_text_auto] Result reason:", result.reason)

        if result.reason != speechsdk.ResultReason.RecognizedSpeech:
            print("[speech_to_text_auto] No recognized speech.")
            return None, None

        auto_detect_result = speechsdk.AutoDetectSourceLanguageResult(result)
        detected_language = auto_detect_result.language
        print("[speech_to_text_auto] Detected language:", detected_language)
        print("[speech_to_text_auto] Recognized text:", result.text)

        return result.text, detected_language
    except Exception as e:
        print(f"[speech_to_text_auto] Exception: {e}")
        return None, None


def translate_text(text: str, to_lang: str = "zh-Hant") -> str | None:
    """
    使用 Azure Translator 將文字翻譯成指定語言。
    """
    endpoint = os.environ.get("AZURE_TRANSLATOR_ENDPOINT")
    key = os.environ.get("AZURE_TRANSLATOR_KEY")
    region = os.environ.get("AZURE_TRANSLATOR_REGION")

    if not endpoint or not key:
        print("[translate_text] Missing AZURE_TRANSLATOR_ENDPOINT or AZURE_TRANSLATOR_KEY")
        return None

    # 確保 endpoint 沒有多一條尾巴斜線
    endpoint = endpoint.rstrip("/")

    path = "/translate"
    params = {"api-version": "3.0", "to": to_lang}
    headers = {
        "Ocp-Apim-Subscription-Key": key,
        "Ocp-Apim-Subscription-Region": region,
        "Content-type": "application/json",
        "X-ClientTraceId": str(uuid.uuid4()),
    }
    body = [{"text": text}]

    try:
        resp = requests.post(
            endpoint + path,
            params=params,
            headers=headers,
            json=body,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return data[0]["translations"][0]["text"]
    except Exception as e:
        print(f"[translate_text] Exception: {e}")
        return None
