"""Background QThread workers for one-shot translation, live region watching, and Q&A."""

from __future__ import annotations

import threading
from typing import Optional, Sequence

import numpy as np
from PIL import Image
from PySide6.QtCore import QThread, Signal

from app.capture import (
    ScreenCapturer,
    ScreenRegion,
    compute_frame_signature,
    compute_signatures_from_bgra,
    compute_subtitle_signature,
    frame_diff_score,
)
from app.ocr_engine import LocalOCREngine, TextBox
from app.overlay import LocalizedSubtitle, TranslatedBox
from app.text_filter import (
    cluster_boxes_into_lines,
    extract_meaningful_sentences,
    group_into_localized_subtitles,
)
from app.translator import HybridTranslator


def reconstruct_reading_order_text(boxes: Sequence[TextBox]) -> str:
    """Sort OCR boxes in natural reading order (top-to-bottom, left-to-right) and join into coherent text."""
    if not boxes:
        return ""
    lines = cluster_boxes_into_lines(boxes)
    line_strings = [" ".join(b.text.strip() for b in line if b.text.strip()) for line in lines]
    return " ".join(s for s in line_strings if s).strip()


class OneShotTranslateWorker(QThread):
    """Run local OCR + batched cloud translation on a captured image in the background."""

    finished_boxes = Signal(list, str)  # (list[TranslatedBox], raw_ocr_text)
    finished_sentence = Signal(str, str, object)  # (original_text, translated_sentence, ScreenRegion)
    failed = Signal(str)

    def __init__(
        self,
        image: Image.Image,
        region: ScreenRegion,
        ocr: LocalOCREngine,
        translator: HybridTranslator,
        target_language: str,
    ) -> None:
        super().__init__()
        self._image = image
        self._region = region
        self._ocr = ocr
        self._translator = translator
        self._target_language = target_language

    def run(self) -> None:
        try:
            detected = self._ocr.recognize(self._image)
            if not detected:
                self.finished_sentence.emit("", "", self._region)
                self.finished_boxes.emit([], "")
                return

            # Reconstruct the full text into a single coherent sentence/paragraph
            full_original_text = reconstruct_reading_order_text(detected)

            translated_sentence = ""
            if full_original_text:
                translations = self._translator.translate_batch(
                    [full_original_text], self._target_language
                )
                if translations:
                    translated_sentence = translations[0]

            self.finished_sentence.emit(
                full_original_text, translated_sentence, self._region
            )

            results = [
                TranslatedBox(
                    x=box.x + self._region.left,
                    y=box.y + self._region.top,
                    width=box.width,
                    height=box.height,
                    original_text=box.text,
                    translated_text=translated_sentence if len(detected) == 1 else box.text,
                )
                for box in detected
            ]
            self.finished_boxes.emit(results, full_original_text)
        except Exception as exc:
            self.failed.emit(str(exc))


class VisionQAWorker(QThread):
    """Send a snipped screenshot + question to Gemini multimodal Vision."""

    answered = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        image: Image.Image,
        question: str,
        translator: HybridTranslator,
        target_language: str,
    ) -> None:
        super().__init__()
        self._image = image
        self._question = question
        self._translator = translator
        self._target_language = target_language

    def run(self) -> None:
        try:
            answer = self._translator.ask_about_image(
                self._image, self._question, target_language=self._target_language
            )
            self.answered.emit(answer)
        except Exception as exc:
            self.failed.emit(str(exc))


class SlangExplainWorker(QThread):
    """Analyze slang, idioms, and indirect meanings in the background."""

    explained = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        text: str,
        translator: HybridTranslator,
        target_language: str = "Sinhala",
    ) -> None:
        super().__init__()
        self._text = text
        self._translator = translator
        self._target_language = target_language

    def run(self) -> None:
        try:
            explanation = self._translator.explain_slang_and_indirect_meaning(
                self._text, target_language=self._target_language
            )
            self.explained.emit(explanation)
        except Exception as exc:
            self.failed.emit(str(exc))


class LiveTranslateWorker(QThread):
    """Continuously monitors a pinned screen region and updates overlays on pixel changes."""

    boxes_updated = Signal(list, object)  # (list[TranslatedBox], ScreenRegion)
    subtitle_updated = Signal(object, object)  # (list[tuple[str, str]], ScreenRegion)
    failed = Signal(str)

    def __init__(
        self,
        region: ScreenRegion,
        capturer: ScreenCapturer,
        ocr: LocalOCREngine,
        translator: HybridTranslator,
        target_language: str,
        interval_ms: int = 450,
        diff_threshold: float = 0.015,
        mode: str = "boxes",
    ) -> None:
        super().__init__()
        self._region = region
        self._capturer = capturer
        self._ocr = ocr
        self._translator = translator
        self._target_language = target_language
        self._interval_s = max(0.06, interval_ms / 1000.0)
        self._diff_threshold = diff_threshold
        self._mode = mode
        self._stop_event = threading.Event()
        self._force_check = False
        self._prev_sig: Optional[np.ndarray] = None
        self._prev_raw_sig: Optional[np.ndarray] = None
        self._last_raw_sentences: list[str] = []
        self._last_subtitle_blocks: list[LocalizedSubtitle] = []
        self._empty_until = 0.0

    def stop(self) -> None:
        self._stop_event.set()

    def force_refresh(self) -> None:
        """Trigger an immediate OCR and translation check, bypassing diff checks."""
        self._force_check = True
        self._prev_sig = None
        self._prev_raw_sig = None
        self._last_raw_sentences = []
        self._last_subtitle_blocks = []
        self._empty_until = 0.0

    def run(self) -> None:
        import time

        last_ocr_time = 0.0
        has_fast_grab = hasattr(self._capturer, "grab_raw")

        while not self._stop_event.is_set():
            try:
                now = time.time()
                raw_capture = None
                img = None

                if has_fast_grab:
                    raw_capture = self._capturer.grab_raw(self._region)
                    sig, raw_sig = compute_signatures_from_bgra(
                        raw_capture.bgra,
                        raw_capture.width,
                        raw_capture.height,
                        subtitle_mode=(self._mode == "subtitle"),
                    )
                else:
                    img = self._capturer.capture_region(self._region)
                    if self._mode == "subtitle":
                        sig = compute_subtitle_signature(img)
                        raw_sig = compute_frame_signature(img, size=(96, 32))
                    else:
                        sig = compute_frame_signature(img)
                        raw_sig = sig

                diff = frame_diff_score(self._prev_sig, sig)
                raw_diff = frame_diff_score(self._prev_raw_sig, raw_sig)
                # Heartbeat only runs if pixels actually changed subtly (paused video = 0% OCR CPU)
                is_subtle_change = (
                    self._mode == "subtitle"
                    and raw_diff > 0.0008
                    and (now - last_ocr_time >= 0.75)
                )
                needs_check = self._force_check or (diff >= self._diff_threshold) or is_subtle_change

                if needs_check:
                    self._force_check = False
                    last_ocr_time = now
                    self._prev_sig = sig
                    self._prev_raw_sig = raw_sig
                    if img is None and raw_capture is not None:
                        img = self._capturer.raw_to_image(raw_capture)
                    detected = self._ocr.recognize(img)
                    del img, raw_capture
                    if not detected:
                        if self._mode == "subtitle":
                            if self._last_subtitle_blocks:
                                if self._empty_until == 0.0:
                                    self._empty_until = now + 1.2
                                elif now >= self._empty_until:
                                    self._last_raw_sentences = []
                                    self._last_subtitle_blocks = []
                                    self._empty_until = 0.0
                                    self.subtitle_updated.emit([], self._region)
                        else:
                            self.boxes_updated.emit([], self._region)
                    else:
                        raw_texts = [b.text for b in detected]
                        if self._mode == "subtitle":
                            blocks = group_into_localized_subtitles(
                                detected, self._region.left, self._region.top
                            )
                            if blocks:
                                texts_to_translate = [b.text for b in blocks]
                                if texts_to_translate != self._last_raw_sentences:
                                    self._last_raw_sentences = texts_to_translate
                                    self._empty_until = 0.0
                                    translated = self._translator.translate_batch(
                                        texts_to_translate, self._target_language
                                    )
                                    localized_subs = [
                                        LocalizedSubtitle(
                                            x=b.x,
                                            y=b.y,
                                            width=b.width,
                                            height=b.height,
                                            original_text=b.text,
                                            translated_text=tr,
                                        )
                                        for b, tr in zip(blocks, translated)
                                    ]
                                    self._last_subtitle_blocks = localized_subs
                                    self.subtitle_updated.emit(localized_subs, self._region)
                        else:
                            self._empty_until = 0.0
                            translated = self._translator.translate_batch(
                                raw_texts, self._target_language
                            )
                            boxes = [
                                TranslatedBox(
                                    x=b.x + self._region.left,
                                    y=b.y + self._region.top,
                                    width=b.width,
                                    height=b.height,
                                    original_text=b.text,
                                    translated_text=tr,
                                )
                                for b, tr in zip(detected, translated)
                            ]
                            self.boxes_updated.emit(boxes, self._region)
            except Exception as exc:
                self.failed.emit(str(exc))
                # Resume quickly after an error without freezing
                self._stop_event.wait(0.2)
                continue

            self._stop_event.wait(self._interval_s)
