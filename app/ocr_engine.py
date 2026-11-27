"""Local offline OCR engine powered by RapidOCR (ONNX Runtime)."""

from __future__ import annotations

import gc
import os
import threading
from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np
from PIL import Image


@dataclass(frozen=True)
class TextBox:
    """Detected text line with pixel coordinates relative to the captured image."""

    x: int
    y: int
    width: int
    height: int
    text: str
    confidence: float = 1.0

    def offset(self, dx: int, dy: int) -> "TextBox":
        """Translate box coordinates into virtual-desktop screen space."""
        return TextBox(
            x=self.x + dx,
            y=self.y + dy,
            width=self.width,
            height=self.height,
            text=self.text,
            confidence=self.confidence,
        )


def polygon_to_rect(poly: Sequence[Sequence[float]]) -> tuple[int, int, int, int]:
    """Convert a 4-point OCR polygon [[x1,y1], ...] into (x, y, width, height)."""
    xs = [float(pt[0]) for pt in poly]
    ys = [float(pt[1]) for pt in poly]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    return (
        int(round(x_min)),
        int(round(y_min)),
        max(1, int(round(x_max - x_min))),
        max(1, int(round(y_max - y_min))),
    )


def normalize_rapidocr_output(
    raw_output: Any,
    min_confidence: float = 0.45,
) -> list[TextBox]:
    """Normalize outputs from both rapidocr (>=2.x) and rapidocr_onnxruntime (1.x)."""
    boxes: list[TextBox] = []
    if raw_output is None:
        return boxes

    # rapidocr >= 2.0 returns an object with .boxes, .txts, .scores attributes
    if hasattr(raw_output, "boxes") and hasattr(raw_output, "txts"):
        raw_boxes = getattr(raw_output, "boxes", None)
        raw_txts = getattr(raw_output, "txts", None)
        raw_scores = getattr(raw_output, "scores", None)
        if raw_boxes is None or raw_txts is None:
            return boxes
        scores_iter = (
            raw_scores if raw_scores is not None else [1.0] * len(raw_txts)
        )
        for poly, txt, score in zip(raw_boxes, raw_txts, scores_iter):
            text = str(txt).strip()
            conf = float(score) if score is not None else 1.0
            if not text or conf < min_confidence:
                continue
            x, y, w, h = polygon_to_rect(poly)
            boxes.append(TextBox(x=x, y=y, width=w, height=h, text=text, confidence=conf))
        return boxes

    # rapidocr_onnxruntime 1.x returns (result_list, elapse) where each item is [poly, text, score]
    items = raw_output[0] if isinstance(raw_output, tuple) else raw_output
    if not items:
        return boxes
    for item in items:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        poly, txt = item[0], item[1]
        conf = float(item[2]) if len(item) >= 3 and item[2] is not None else 1.0
        text = str(txt).strip()
        if not text or conf < min_confidence:
            continue
        x, y, w, h = polygon_to_rect(poly)
        boxes.append(TextBox(x=x, y=y, width=w, height=h, text=text, confidence=conf))
    return boxes


class LocalOCREngine:
    """Thread-safe, resource-tuned local RapidOCR wrapper for low-latency text extraction."""

    def __init__(self, min_confidence: float = 0.45) -> None:
        self.min_confidence = min_confidence
        self._engine: Any = None
        self._init_lock = threading.Lock()
        self._infer_lock = threading.Lock()

    def _ensure_engine(self) -> Any:
        if self._engine is not None:
            return self._engine
        with self._init_lock:
            if self._engine is not None:
                return self._engine

            # Tune RapidOCR for fast screen-text latency & balanced thread footprint
            intra_threads = max(2, min(4, os.cpu_count() or 4))
            try:
                from rapidocr import RapidOCR  # type: ignore

                try:
                    self._engine = RapidOCR(
                        params={
                            "Global.use_cls": False,
                            "Global.log_level": "error",
                            "Det.limit_side_len": 384,
                            "EngineConfig.onnxruntime.intra_op_num_threads": intra_threads,
                            "EngineConfig.onnxruntime.inter_op_num_threads": 1,
                            "EngineConfig.onnxruntime.enable_cpu_mem_arena": True,
                        }
                    )
                except Exception:
                    self._engine = RapidOCR()
                return self._engine
            except ImportError:
                pass

            try:
                from rapidocr_onnxruntime import RapidOCR  # type: ignore

                self._engine = RapidOCR()
                return self._engine
            except ImportError as exc:
                raise RuntimeError(
                    "RapidOCR is not installed. Run: pip install rapidocr onnxruntime"
                ) from exc

    @property
    def is_loaded(self) -> bool:
        return self._engine is not None

    def unload(self) -> bool:
        """Unload ONNX models from RAM when idle to minimize memory footprint."""
        with self._init_lock:
            with self._infer_lock:
                if self._engine is None:
                    return False
                self._engine = None
        gc.collect()
        return True

    def warmup(self) -> None:
        """Pre-load ONNX models in background so the first user snip is instantaneous."""
        try:
            dummy = Image.new("RGB", (64, 32), color=(255, 255, 255))
            self.recognize(dummy)
        except Exception:
            pass

    def recognize(self, image: Image.Image) -> list[TextBox]:
        """Run local OCR on a PIL image and return normalized TextBox items."""
        engine = self._ensure_engine()
        rgb_img = image if image.mode == "RGB" else image.convert("RGB")
        rgb_array = np.asarray(rgb_img)
        with self._infer_lock:
            raw = engine(rgb_array)
        return normalize_rapidocr_output(raw, min_confidence=self.min_confidence)
