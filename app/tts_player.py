"""Fast asynchronous Text-to-Speech (TTS) audio engine with caching, chunking, and instant Stop."""

from __future__ import annotations

from collections import OrderedDict
import ctypes
import importlib.util
import os
import re
import tempfile
import threading
from typing import Callable, Optional

import requests

from app.translator import _get_google_session, resolve_lang_code

_HAS_WIN32COM = importlib.util.find_spec("win32com") is not None


def split_tts_chunks(text: str, max_chars: int = 90) -> list[str]:
    """Split longer text into natural short chunks so the first chunk starts playing immediately."""
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return []
    if len(cleaned) <= max_chars:
        return [cleaned]

    chunks: list[str] = []
    # Split first by sentence/clause boundaries (. ! ? , ;)
    parts = re.split(r"(?<=[.!?,;:\u0964])\s+", cleaned)
    current = ""
    for part in parts:
        if not part:
            continue
        if len(part) > max_chars:
            # Break long clause by spaces
            if current:
                chunks.append(current)
                current = ""
            words = part.split(" ")
            buf = ""
            for w in words:
                cand = f"{buf} {w}".strip() if buf else w
                if len(cand) <= max_chars:
                    buf = cand
                else:
                    if buf:
                        chunks.append(buf)
                    buf = w[:max_chars]
            if buf:
                current = buf
        else:
            cand = f"{current} {part}".strip() if current else part
            if len(cand) <= max_chars:
                current = cand
            else:
                if current:
                    chunks.append(current)
                current = part
    if current:
        chunks.append(current)
    return chunks[:4]


class TextToSpeechPlayer:
    """Low-latency TTS player with in-memory LRU cache, sentence chunking, and instant Stop."""

    def __init__(
        self,
        on_state_changed: Optional[Callable[[bool], None]] = None,
        cache_max: int = 24,
    ) -> None:
        self._lock = threading.Lock()
        self._cache_lock = threading.Lock()
        self._audio_cache: OrderedDict[tuple[str, str], bytes] = OrderedDict()
        self._cache_max = max(4, cache_max)
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
        """Immediately interrupt any currently playing or queued TTS audio."""
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

    def _fetch_tts_audio(self, chunk: str, lang_code: str) -> Optional[bytes]:
        """Download MP3 bytes from fast Google TTS endpoint with LRU caching."""
        key = (lang_code, chunk)
        with self._cache_lock:
            cached = self._audio_cache.get(key)
            if cached is not None:
                self._audio_cache.move_to_end(key)
                return cached

        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        sess = _get_google_session()
        encoded = requests.utils.quote(chunk)

        # tw-ob is significantly faster & less throttled than gtx
        for client in ("tw-ob", "gtx"):
            url = f"https://translate.googleapis.com/translate_tts?ie=UTF-8&client={client}&tl={lang_code}&q={encoded}"
            try:
                resp = sess.get(url, headers=headers, timeout=2.2)
                if resp.status_code == 200 and len(resp.content) >= 100:
                    data = resp.content
                    with self._cache_lock:
                        self._audio_cache[key] = data
                        self._audio_cache.move_to_end(key)
                        while len(self._audio_cache) > self._cache_max:
                            self._audio_cache.popitem(last=False)
                    return data
            except Exception:
                continue
        return None

    def _play_mp3_bytes(self, audio_bytes: bytes, stop_ev: threading.Event) -> bool:
        """Play cached MP3 bytes via Windows MCI with non-blocking stop polling."""
        if stop_ev.is_set():
            return False

        temp_path = None
        alias = f"tts_{threading.get_ident()}"
        opened = False
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                f.write(audio_bytes)
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
                stop_ev.wait(0.05)
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
                chunks = split_tts_chunks(text, max_chars=90)
                if not chunks:
                    return

                # Fetch first chunk immediately
                audio_data = self._fetch_tts_audio(chunks[0], lang_code)
                if audio_data is not None:
                    # Prefetch remaining chunks in parallel while chunk 1 plays
                    next_holder: dict[int, Optional[bytes]] = {}

                    def _prefetch_rest():
                        for idx in range(1, len(chunks)):
                            if stop_ev.is_set() or gen != self._generation:
                                break
                            next_holder[idx] = self._fetch_tts_audio(chunks[idx], lang_code)

                    prefetch_t = None
                    if len(chunks) > 1:
                        prefetch_t = threading.Thread(target=_prefetch_rest, daemon=True)
                        prefetch_t.start()

                    self._play_mp3_bytes(audio_data, stop_ev)

                    if prefetch_t is not None and not stop_ev.is_set() and gen == self._generation:
                        prefetch_t.join(timeout=2.5)
                        for idx in range(1, len(chunks)):
                            if stop_ev.is_set() or gen != self._generation:
                                break
                            nxt = next_holder.get(idx)
                            if nxt is None:
                                nxt = self._fetch_tts_audio(chunks[idx], lang_code)
                            if nxt:
                                self._play_mp3_bytes(nxt, stop_ev)
                    return

                # Offline English fallback via Windows SAPI if win32com is installed
                if lang_code == "en" and _HAS_WIN32COM and not stop_ev.is_set():
                    self._speak_sapi(text, stop_ev)
        finally:
            if gen == self._generation:
                self._emit_state(False)

    def _speak_sapi(self, text: str, stop_ev: threading.Event) -> bool:
        """Speak English text using native Windows SAPI COM object with async interruption."""
        try:
            import pythoncom
            import win32com.client

            pythoncom.CoInitialize()
            try:
                speaker = win32com.client.Dispatch("SAPI.SpVoice")
                speaker.Speak(text[:300], 1)  # 1 = SVSFlagsAsync
                while not stop_ev.is_set():
                    if getattr(speaker.Status, "RunningState", 1) == 1:
                        break
                    stop_ev.wait(0.05)
                if stop_ev.is_set():
                    speaker.Speak("", 2)  # 2 = SVSFPurgeBeforeSpeak
                return True
            finally:
                pythoncom.CoUninitialize()
        except Exception:
            return False
