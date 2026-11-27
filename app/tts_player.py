"""Background Text-to-Speech (TTS) audio engine with instant Stop support."""

from __future__ import annotations

import ctypes
import os
import tempfile
import threading
from typing import Callable, Optional

import requests

from app.translator import _get_google_session, resolve_lang_code


class TextToSpeechPlayer:
    """Asynchronous TTS player with instant stop/interrupt support using Windows SAPI and MCI."""

    def __init__(self, on_state_changed: Optional[Callable[[bool], None]] = None) -> None:
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._active_alias: Optional[str] = None
        self._speaking: bool = False
        self._generation: int = 0
        self._on_state_changed = on_state_changed

    def set_state_callback(self, callback: Optional[Callable[[bool], None]]) -> None:
        self._on_state_changed = callback

    @property
    def is_speaking(self) -> bool:
        return self._speaking

    def _emit_state(self, playing: bool) -> None:
        self._speaking = playing
        cb = self._on_state_changed
        if cb is not None:
            try:
                cb(playing)
            except Exception:
                pass

    def stop(self) -> None:
        """Immediately interrupt any currently playing TTS audio."""
        self._generation += 1
        self._stop_event.set()
        alias = self._active_alias
        if alias:
            try:
                winmm = ctypes.windll.winmm
                winmm.mciSendStringW(f"stop {alias}", None, 0, None)
                winmm.mciSendStringW(f"close {alias}", None, 0, None)
            except Exception:
                pass
        self._emit_state(False)

    def speak_async(self, text: str, lang: str = "en") -> None:
        """Play TTS audio asynchronously in a background thread (interrupts prior playback)."""
        text = text.strip()
        if not text:
            return

        # Interrupt any previous speech before starting the new one
        self.stop()
        self._stop_event = threading.Event()
        gen = self._generation
        self._emit_state(True)

        thread = threading.Thread(
            target=self._speak_worker,
            args=(text, lang, gen, self._stop_event),
            daemon=True,
            name="TTSPlayerWorker",
        )
        self._thread = thread
        thread.start()

    def _speak_worker(
        self,
        text: str,
        lang: str,
        gen: int,
        stop_ev: threading.Event,
    ) -> None:
        try:
            with self._lock:
                if stop_ev.is_set() or gen != self._generation:
                    return
                lang_code = resolve_lang_code(lang)
                if lang_code == "en":
                    if self._speak_sapi(text, stop_ev):
                        return
                if not stop_ev.is_set() and gen == self._generation:
                    self._speak_google_tts(text, lang_code, stop_ev)
        finally:
            if gen == self._generation:
                self._emit_state(False)

    def _speak_sapi(self, text: str, stop_ev: threading.Event) -> bool:
        """Speak English text using native Windows SAPI COM object with async interruption."""
        try:
            import pythoncom
            import win32com.client

            pythoncom.CoInitialize()
            speaker = None
            try:
                speaker = win32com.client.Dispatch("SAPI.SpVoice")
                # 1 = SVSFlagsAsync
                speaker.Speak(text[:300], 1)
                while not stop_ev.is_set():
                    # RunningState == 1 means Done
                    if getattr(speaker.Status, "RunningState", 1) == 1:
                        break
                    stop_ev.wait(0.06)
                if stop_ev.is_set():
                    # 2 = SVSFPurgeBeforeSpeak
                    speaker.Speak("", 2)
                return True
            finally:
                pythoncom.CoUninitialize()
        except Exception:
            return False

    def _speak_google_tts(self, text: str, lang_code: str, stop_ev: threading.Event) -> bool:
        """Fetch TTS audio from Google and play non-blocking via Windows MCI so Stop works instantly."""
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
            resp = sess.get(url, headers=headers, timeout=4)
            if stop_ev.is_set() or resp.status_code != 200 or len(resp.content) < 100:
                return False

            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                f.write(resp.content)
                temp_path = f.name

            if stop_ev.is_set():
                return False

            winmm = ctypes.windll.winmm
            self._active_alias = alias
            err = winmm.mciSendStringW(f'open "{temp_path}" type mpegvideo alias {alias}', None, 0, None)
            if err != 0:
                return False
            opened = True
            winmm.mciSendStringW(f"play {alias}", None, 0, None)

            status_buf = ctypes.create_unicode_buffer(32)
            while not stop_ev.is_set():
                status_buf.value = ""
                winmm.mciSendStringW(f"status {alias} mode", status_buf, 31, None)
                mode = status_buf.value.strip().lower()
                if mode not in ("playing", "seeking"):
                    break
                stop_ev.wait(0.06)
            return True
        except Exception:
            return False
        finally:
            self._active_alias = None
            if opened:
                try:
                    winmm = ctypes.windll.winmm
                    winmm.mciSendStringW(f"stop {alias}", None, 0, None)
                    winmm.mciSendStringW(f"close {alias}", None, 0, None)
                except Exception:
                    pass
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
