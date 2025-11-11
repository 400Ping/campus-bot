
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
