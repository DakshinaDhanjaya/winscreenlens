"""Background Text-to-Speech (TTS) audio engine for English & Sinhala pronunciations."""

from __future__ import annotations

import ctypes
import os
import tempfile
import threading
from typing import Optional

import requests

from app.translator import _get_google_session, resolve_lang_code


class TextToSpeechPlayer:
    """Zero-dependency asynchronous TTS player using Windows SAPI (offline English)

    and Google TTS (Sinhala/Multi-language) via Windows MCI multimedia audio subsystem.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    def speak_async(self, text: str, lang: str = "en") -> None:
        """Play TTS audio asynchronously in a background thread."""
        text = text.strip()
        if not text:
            return

        thread = threading.Thread(
            target=self._speak_worker,
            args=(text, lang),
            daemon=True,
            name="TTSPlayerWorker",
        )
        self._thread = thread
        thread.start()

    def _speak_worker(self, text: str, lang: str) -> None:
        with self._lock:
            # 1. If English, try offline Windows SAPI first
            lang_code = resolve_lang_code(lang)
            if lang_code == "en":
                if self._speak_sapi(text):
                    return

            # 2. Online Google TTS for Sinhala, Tamil, Japanese, etc.
            self._speak_google_tts(text, lang_code)

    def _speak_sapi(self, text: str) -> bool:
        """Speak English text using native Windows SAPI COM object."""
        try:
            import pythoncom
            import win32com.client

            pythoncom.CoInitialize()
            try:
                speaker = win32com.client.Dispatch("SAPI.SpVoice")
                speaker.Speak(text[:300])
                return True
            finally:
                pythoncom.CoUninitialize()
        except Exception:
            return False

    def _speak_google_tts(self, text: str, lang_code: str) -> bool:
        """Fetch TTS audio from Google and play via Windows MCI audio."""
        truncated = text[:200]
        url = (
            f"https://translate.googleapis.com/translate_tts?ie=UTF-8&client=gtx"
            f"&tl={lang_code}&q={requests.utils.quote(truncated)}"
        )
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        sess = _get_google_session()

        temp_path = None
        alias = f"tts_{threading.get_ident()}"
        opened = False
        try:
            resp = sess.get(url, headers=headers, timeout=6)
            if resp.status_code != 200 or len(resp.content) < 100:
                return False

            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                f.write(resp.content)
                temp_path = f.name

            winmm = ctypes.windll.winmm
            winmm.mciSendStringW(f'open "{temp_path}" type mpegvideo alias {alias}', None, 0, None)
            opened = True
            winmm.mciSendStringW(f"play {alias} wait", None, 0, None)
            return True
        except Exception:
            return False
        finally:
            if opened:
                try:
                    ctypes.windll.winmm.mciSendStringW(f"close {alias}", None, 0, None)
                except Exception:
                    pass
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
