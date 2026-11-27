"""Fast screen capture and zero-copy lightweight pixel-change detection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
from PIL import Image


@dataclass(frozen=True)
class ScreenRegion:
    """Absolute virtual-screen pixel rectangle."""

    left: int
    top: int
    width: int
    height: int

    def is_valid(self) -> bool:
        return self.width >= 8 and self.height >= 8

    def to_mss_dict(self) -> dict[str, int]:
        return {
            "left": int(self.left),
            "top": int(self.top),
            "width": int(self.width),
            "height": int(self.height),
        }


def compute_frame_signature(image: Image.Image, size: tuple[int, int] = (64, 64)) -> np.ndarray:
    """Downsample an image to a small grayscale array for fast frame-diffing."""
    small = image.convert("L").resize(size, Image.Resampling.BILINEAR)
    return np.asarray(small, dtype=np.float32) / 255.0


def compute_subtitle_signature(image: Image.Image, size: tuple[int, int] = (96, 32)) -> np.ndarray:
    """Isolate high-luminance/contrast subtitle pixels to ignore moving video background."""
    gray = image.convert("L").resize(size, Image.Resampling.BILINEAR)
    arr = np.asarray(gray, dtype=np.uint8)
    # Subtitles are high contrast (broadened threshold > 150 captures yellow, white & dimmed text)
    return (arr > 150).astype(np.float32)


def compute_signatures_from_bgra(
    raw_bgra: bytes,
    width: int,
    height: int,
    subtitle_mode: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute (mode_sig, raw_luma_sig) directly via strided numpy view without PIL allocation."""
    arr = np.frombuffer(raw_bgra, dtype=np.uint8).reshape((height, width, 4))
    target_w = 96 if subtitle_mode else 64
    target_h = 32 if subtitle_mode else 64
    step_y = max(1, height // target_h)
    step_x = max(1, width // target_w)
    sampled = arr[::step_y, ::step_x]
    # Fast integer BT.601 luminance from BGRA channels: (B*29 + G*150 + R*77) >> 8
    luma = (
        sampled[:, :, 0].astype(np.uint16) * 29
        + sampled[:, :, 1].astype(np.uint16) * 150
        + sampled[:, :, 2].astype(np.uint16) * 77
    ) >> 8
    raw_sig = luma.astype(np.float32) / 255.0
    if subtitle_mode:
        mode_sig = (luma > 150).astype(np.float32)
        return mode_sig, raw_sig
    return raw_sig, raw_sig


def frame_diff_score(prev_sig: Optional[np.ndarray], curr_sig: np.ndarray) -> float:
    """Return mean absolute difference in [0.0, 1.0] between two signatures."""
    if prev_sig is None or prev_sig.shape != curr_sig.shape:
        return 1.0
    return float(np.mean(np.abs(prev_sig - curr_sig)))


class ScreenCapturer:
    """High-speed thread-safe wrapper around mss with persistent handles."""

    def __init__(self) -> None:
        import threading

        self._local = threading.local()

    def _get_sct(self):
        import mss

        sct = getattr(self._local, "sct", None)
        if sct is None:
            sct = mss.mss()
            self._local.sct = sct
        return sct

    def grab_raw(self, region: ScreenRegion):
        """Capture region and return raw mss ScreenShot without building a PIL Image yet."""
        if not region.is_valid():
            raise ValueError(f"Invalid capture region: {region}")
        return self._get_sct().grab(region.to_mss_dict())

    @staticmethod
    def raw_to_image(raw) -> Image.Image:
        """Convert an mss raw capture to an RGB PIL Image."""
        return Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

    def capture_region(self, region: ScreenRegion) -> Image.Image:
        raw = self.grab_raw(region)
        return self.raw_to_image(raw)

    def capture_primary_monitor(self) -> tuple[Image.Image, ScreenRegion]:
        sct = self._get_sct()
        mon = sct.monitors[1]  # monitors[0] is virtual all-monitors bounding box
        region = ScreenRegion(
            left=mon["left"],
            top=mon["top"],
            width=mon["width"],
            height=mon["height"],
        )
        raw = sct.grab(mon)
        return self.raw_to_image(raw), region

    def capture_virtual_desktop(self) -> tuple[Image.Image, ScreenRegion]:
        sct = self._get_sct()
        mon = sct.monitors[0]
        region = ScreenRegion(
            left=mon["left"],
            top=mon["top"],
            width=mon["width"],
            height=mon["height"],
        )
        raw = sct.grab(mon)
        return self.raw_to_image(raw), region
