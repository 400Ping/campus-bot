
import os, uuid, requests
import azure.cognitiveservices.speech as speechsdk

def speech_to_text(audio_file_path: str, language: str = 'en-US'):
    key = os.environ.get('AZURE_SPEECH_KEY')
    region = os.environ.get('AZURE_SPEECH_REGION')
    if not key or not region:
        return None
    try:
        speech_config = speechsdk.SpeechConfig(subscription=key, region=region)
        speech_config.speech_recognition_language = language
        audio_config = speechsdk.audio.AudioConfig(filename=audio_file_path)
        recognizer = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config)
        result = recognizer.recognize_once()
        if result.reason == speechsdk.ResultReason.RecognizedSpeech:
            return result.text
        else:
            return None
    except Exception:
        return None

def speech_to_text_auto(audio_file_path: str, languages: list[str] | None = None):
    key = os.environ.get('AZURE_SPEECH_KEY')
    region = os.environ.get('AZURE_SPEECH_REGION')
    if not key or not region:
        return None, None
    tmp_wav = None
    in_path = audio_file_path
    try:
        if not audio_file_path.lower().endswith(".wav"):
            from pydub import AudioSegment
            sound = AudioSegment.from_file(audio_file_path)
            sound = sound.set_frame_rate(16000).set_channels(1).set_sample_width(2)
            import tempfile, os as _os
            fd, tmp_wav = tempfile.mkstemp(suffix=".wav")
            _os.close(fd)
            sound.export(tmp_wav, format="wav")
            in_path = tmp_wav
    except Exception:
        in_path = audio_file_path
    try:
        speech_config = speechsdk.SpeechConfig(subscription=key, region=region)
        lang_list = languages or ["en-US","zh-TW","ja-JP","ko-KR","de-DE","es-ES","hi-IN"]
        auto_config = speechsdk.languageconfig.AutoDetectSourceLanguageConfig(languages=lang_list)
        audio_config = speechsdk.audio.AudioConfig(filename=in_path)
        recognizer = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config, auto_detect_source_language_config=auto_config)
        result = recognizer.recognize_once()
        if result.reason == speechsdk.ResultReason.RecognizedSpeech:
            detected = None
            try:
                lang_res = speechsdk.AutoDetectSourceLanguageResult(result)
                detected = lang_res.language or None
            except Exception:
                detected = None
            return result.text, detected
        else:
            return None, None
    except Exception:
        return None, None
    finally:
        if tmp_wav:
            try:
                os.remove(tmp_wav)
            except Exception:
                pass

def translate_text(text: str, to_lang: str = 'zh-Hant'):
    endpoint = os.environ.get('AZURE_TRANSLATOR_ENDPOINT')
    key = os.environ.get('AZURE_TRANSLATOR_KEY')
    region = os.environ.get('AZURE_TRANSLATOR_REGION')
    if not endpoint or not key:
        return None
    path = '/translate'
    params = { 'api-version': '3.0', 'to': to_lang }
    headers = {
        'Ocp-Apim-Subscription-Key': key,
        'Ocp-Apim-Subscription-Region': region,
        'Content-type': 'application/json',
        'X-ClientTraceId': str(uuid.uuid4())
    }
    body = [{ 'text': text }]
    try:
        r = requests.post(endpoint + path, params=params, headers=headers, json=body, timeout=15)
        r.raise_for_status()
        data = r.json()
        return data[0]['translations'][0]['text']
    except Exception:
        return None
