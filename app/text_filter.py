"""Text sanitization and meaningful sentence filtering for OCR video subtitles."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Sequence

from app.ocr_engine import TextBox

# Common video player / streaming UI tags that are not dialogue
PLAYER_UI_TAGS = {
    "hd", "4k", "720p", "1080p", "cc", "auto", "sub", "live", "off", "on",
    "speed", "subtitles", "settings", "audio", "full screen", "fullscreen"
}

# Regex to strip sound effects and ambient tags: [Music], (Applause), [Laughter], ♪, etc.
SOUND_TAGS_PATTERN = re.compile(
    r"\[.*?\]|\(.*?\)|♪+[^♪]*♪*|[\u266a\u266b]+",
    re.IGNORECASE,
)

# Regex to strip leading speaker markers or subtitle prefixes: ">> ", "- ", "— ", "* "
PREFIX_PATTERN = re.compile(r"^(?:>>|>|—|-|\*|\s)+")

# Timestamp pattern: e.g. "01:23", "12:34 / 45:00", "00:01:20"
TIMESTAMP_PATTERN = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?(?:\s*/\s*\d{1,2}:\d{2}(?::\d{2})?)?$")


def clean_subtitle_text(text: str) -> str:
    """Strip OCR artifacts, subtitle speaker markers, and sound effect tags."""
    if not text:
        return ""
    # Strip [Music], (Laughter), ♪♪
    cleaned = SOUND_TAGS_PATTERN.sub("", text)
    # Strip leading speaker prefixes (">> ", "- ")
    cleaned = PREFIX_PATTERN.sub("", cleaned.strip())
    # Strip excessive whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def is_meaningful_text(text: str) -> bool:
    """Return True if text contains meaningful words/sentences rather than OCR noise."""
    cleaned = clean_subtitle_text(text)
    if len(cleaned) < 2:
        # Only accept single character if it's a valid standalone English word "I" or "A"
        if cleaned.upper() not in {"I", "A"}:
            return False

    # Check for timestamps (e.g. 10:24)
    if TIMESTAMP_PATTERN.match(cleaned):
        return False

    # Check for pure symbols/digits without words (e.g. "...", "123", "---")
    letters = re.findall(r"[A-Za-z\u00C0-\u024F\u0D80-\u0DFF]", cleaned)
    if len(letters) < 2 and cleaned.upper() not in {"I", "A"}:
        return False

    # Extract words
    words = re.findall(r"\b[A-Za-z\u00C0-\u024F\u0D80-\u0DFF]+(?:\'[A-Za-z]+)?\b", cleaned)
    if not words:
        return False

    # If the only word is a video player tag (like "HD" or "4K" or "CC"), ignore
    if len(words) == 1 and words[0].lower() in PLAYER_UI_TAGS:
        return False

    return True


def extract_meaningful_sentences(texts: Sequence[str]) -> list[str]:
    """Combine detected OCR text fragments into clean, meaningful dialogue sentences.

    Filters out noise, joins multi-line fragments, and splits into distinct sentences.
    """
    valid_fragments: list[str] = []
    for raw in texts:
        cleaned = clean_subtitle_text(raw)
        if is_meaningful_text(cleaned):
            valid_fragments.append(cleaned)

    if not valid_fragments:
        return []

    # Join fragments into coherent subtitle dialogue block
    joined = " ".join(valid_fragments)
    joined = re.sub(r"\s+", " ", joined).strip()

    # Split by sentence boundaries if multiple distinct sentences exist (.!? followed by space)
    candidates = [
        s.strip()
        for s in re.split(r"(?<=[.!?])\s+", joined)
        if s.strip() and is_meaningful_text(s)
    ]

    return candidates if candidates else [joined]


@dataclass(frozen=True)
class RawSubtitleBlock:
    """Localized subtitle block before translation with pixel coordinates."""

    x: int
    y: int
    width: int
    height: int
    text: str


def cluster_boxes_into_lines(boxes: Sequence[TextBox]) -> list[list[TextBox]]:
    """Cluster bounding boxes into lines based on vertical overlap and center proximity,

    then sort each line strictly from left to right.
    """
    if not boxes:
        return []

    # Sort primarily by vertical position (top to bottom), secondarily by x
    by_y = sorted(boxes, key=lambda b: (b.y, b.x))
    lines: list[list[TextBox]] = []

    for b in by_y:
        assigned = False
        if lines:
            last_line = lines[-1]
            line_y_min = min(item.y for item in last_line)
            line_y_max = max(item.y + item.height for item in last_line)
            line_h = max(1, line_y_max - line_y_min)

            box_mid_y = b.y + b.height / 2.0
            line_mid_y = (line_y_min + line_y_max) / 2.0

            # Vertical overlap
            overlap = min(b.y + b.height, line_y_max) - max(b.y, line_y_min)
            is_same_line = (overlap > 0.35 * min(b.height, line_h)) or (
                abs(box_mid_y - line_mid_y) <= 0.45 * line_h
            )

            if is_same_line:
                last_line.append(b)
                assigned = True

        if not assigned:
            lines.append([b])

    # Sort each line strictly by x (left to right)
    for line in lines:
        line.sort(key=lambda b: b.x)

    return lines


def group_into_localized_subtitles(
    boxes: Sequence[TextBox],
    region_left: int = 0,
    region_top: int = 0,
) -> list[RawSubtitleBlock]:
    """Group detected OCR text boxes into localized sentence blocks preserving screen coordinates.

    Words on the same line or vertically adjacent subtitle lines are merged into a single
    block with an aggregated bounding rectangle. Distant text blocks (e.g., top title vs bottom dialogue)
    remain separated so each can be translated and previewed directly under its respective source text.
    """
    if not boxes:
        return []

    # 1. Filter out noise and UI tags
    valid_boxes: list[TextBox] = []
    for b in boxes:
        cleaned = clean_subtitle_text(b.text)
        if is_meaningful_text(cleaned):
            valid_boxes.append(
                TextBox(
                    x=b.x,
                    y=b.y,
                    width=b.width,
                    height=b.height,
                    text=cleaned,
                    confidence=b.confidence,
                )
            )

    if not valid_boxes:
        return []

    # 2. Cluster into lines using geometric overlap
    lines = cluster_boxes_into_lines(valid_boxes)

    # 3. Turn each line into a line block
    line_blocks: list[RawSubtitleBlock] = []
    for line in lines:
        lx = min(b.x for b in line)
        ly = min(b.y for b in line)
        lw = max(b.x + b.width for b in line) - lx
        lh = max(b.y + b.height for b in line) - ly
        ltxt = " ".join(b.text.strip() for b in line if b.text.strip()).strip()
        if ltxt and is_meaningful_text(ltxt):
            line_blocks.append(RawSubtitleBlock(x=lx, y=ly, width=lw, height=lh, text=ltxt))

    if not line_blocks:
        return []

    # 4. Merge vertically adjacent lines that belong to the same subtitle event/sentence
    avg_h = sum(lb.height for lb in line_blocks) / max(1, len(line_blocks))
    merged_blocks: list[RawSubtitleBlock] = []
    current_block: Optional[RawSubtitleBlock] = None

    for lb in line_blocks:
        if current_block is None:
            current_block = lb
            continue

        ref_h = max(current_block.height, lb.height, avg_h)
        vertical_gap = lb.y - (current_block.y + current_block.height)

        # Allow slight vertical overlap up to 70% of line height, and gaps up to 1.8x line height
        min_allowed_gap = -int(ref_h * 0.7)
        max_allowed_gap = max(24, int(ref_h * 1.8))

        # Sentence continuity check: Does current_block end without terminal punctuation?
        ends_with_terminal = current_block.text.rstrip().endswith((".", "!", "?", '."', "!'", '?"'))
        starts_with_lower = bool(lb.text.lstrip() and lb.text.lstrip()[0].islower())
        is_sentence_continuation = (not ends_with_terminal) or starts_with_lower

        # Horizontal proximity
        overlap_or_close = not (
            lb.x > current_block.x + current_block.width + 140
            or current_block.x > lb.x + lb.width + 140
        )

        is_adjacent = (min_allowed_gap <= vertical_gap <= max_allowed_gap) or (
            is_sentence_continuation and vertical_gap <= max(40, int(ref_h * 2.4))
        )

        if is_adjacent and overlap_or_close:
            new_x = min(current_block.x, lb.x)
            new_y = min(current_block.y, lb.y)
            new_w = max(current_block.x + current_block.width, lb.x + lb.width) - new_x
            new_h = max(current_block.y + current_block.height, lb.y + lb.height) - new_y
            new_text = f"{current_block.text} {lb.text}".strip()
            current_block = RawSubtitleBlock(
                x=new_x, y=new_y, width=new_w, height=new_h, text=new_text
            )
            continue

        merged_blocks.append(current_block)
        current_block = lb

    if current_block is not None:
        merged_blocks.append(current_block)

    # 5. Offset by region_left and region_top to get global screen coordinates
    return [
        RawSubtitleBlock(
            x=b.x + region_left,
            y=b.y + region_top,
            width=b.width,
            height=b.height,
            text=b.text,
        )
        for b in merged_blocks
    ]
