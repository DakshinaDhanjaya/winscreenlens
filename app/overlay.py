"""Click-through transparent Windows overlay that renders translated text boxes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPolygon
from PySide6.QtWidgets import QApplication, QWidget

from app.capture import ScreenRegion
from app.theme_manager import get_theme
from app.win32_utils import exclude_window_from_capture, set_window_click_through


@dataclass(frozen=True)
class TranslatedBox:
    """Translated text paired with its virtual-desktop pixel rectangle."""

    x: int
    y: int
    width: int
    height: int
    original_text: str
    translated_text: str


@dataclass(frozen=True)
class LocalizedSubtitle:
    """Video subtitle block paired with screen coordinates for localized under-text preview."""

    x: int
    y: int
    width: int
    height: int
    original_text: str
    translated_text: str


class TranslationOverlay(QWidget):
    """Topmost, click-through overlay excluded from Windows screen capture."""

    def __init__(self, opacity: int = 220) -> None:
        super().__init__()
        self._boxes: list[TranslatedBox] = []
        self._live_region: Optional[ScreenRegion] = None
        self._subtitle_pairs: list[tuple[str, str]] = []
        self._localized_subtitles: list[LocalizedSubtitle] = []
        self._subtitle_region: Optional[ScreenRegion] = None
        self._preview_original: str = ""
        self._preview_translated: str = ""
        self._preview_region: Optional[ScreenRegion] = None
        self._preview_card_rect: Optional[QRect] = None
        self._preview_flipped_above: bool = False
        self._style_mode: str = "auto"
        self._opacity = max(80, min(255, opacity))
        self._theme_name: str = "deep_slate"

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        self._cover_virtual_desktop()

    def _cover_virtual_desktop(self) -> None:
        desktop_geo = QRect()
        for screen in QApplication.screens():
            desktop_geo = desktop_geo.united(screen.geometry())
        if not desktop_geo.isEmpty():
            self.setGeometry(desktop_geo)

    def _apply_win32_flags(self) -> None:
        hwnd = int(self.winId())
        exclude_window_from_capture(hwnd)
        set_window_click_through(hwnd, True)

    def _compute_preview_card_geometry(
        self,
        translated_text: str,
        region: ScreenRegion,
    ) -> tuple[QRect, bool]:
        """Compute the preview card QRect and whether it was flipped above the region."""
        origin = self.geometry().topLeft()
        dpr = max(1.0, self.devicePixelRatioF())
        rx = int(region.left / dpr) - origin.x()
        ry = int(region.top / dpr) - origin.y()
        rw = max(10, int(region.width / dpr))
        rh = max(10, int(region.height / dpr))

        si_font = QFont("Nirmala UI")
        si_font.setFamilies(["Nirmala UI", "Iskoola Pota", "Segoe UI"])
        si_font.setPointSize(12)
        si_font.setBold(True)
        si_fm = QFontMetrics(si_font)

        card_min_w = 320
        desktop_w = self.width() if self.width() > 100 else 1920
        desktop_h = self.height() if self.height() > 100 else 1080
        card_max_w = min(680, desktop_w - 40)
        card_w = max(card_min_w, min(rw + 30, card_max_w))
        inner_padding_x = 16
        inner_padding_y = 12
        text_avail_w = card_w - (inner_padding_x * 2)

        text_rect = si_fm.boundingRect(
            0,
            0,
            text_avail_w,
            2000,
            Qt.TextFlag.TextWordWrap,
            translated_text,
        )
        content_h = text_rect.height()
        header_h = 18
        card_h = inner_padding_y + header_h + 6 + content_h + inner_padding_y

        card_gap = 7
        card_x = rx
        if card_x + card_w > desktop_w - 16:
            card_x = desktop_w - card_w - 16
        if card_x < 16:
            card_x = 16

        card_y = ry + rh + card_gap
        flipped_above = False
        if card_y + card_h > desktop_h - 16:
            card_y = ry - card_h - card_gap
            flipped_above = True
            if card_y < 16:
                card_y = 16

        return QRect(card_x, card_y, card_w, card_h), flipped_above

    def show_sentence_preview(
        self,
        original_text: str,
        translated_text: str,
        region: ScreenRegion,
    ) -> None:
        """Render a clean highlight over the selected region and a cinema-quality Sinhala preview card just below it."""
        self._cover_virtual_desktop()
        self._preview_original = original_text.strip()
        self._preview_translated = translated_text.strip()
        self._preview_region = region
        self._preview_card_rect, self._preview_flipped_above = (
            self._compute_preview_card_geometry(self._preview_translated, region)
        )
        self._boxes = []
        self._subtitle_pairs = []
        self._localized_subtitles = []
        self._subtitle_region = None
        self._live_region = None
        if not self.isVisible():
            self.show()
        self._apply_win32_flags()
        self.update()

    def get_preview_card_rect(self) -> Optional[QRect]:
        """Return the calculated QRect of the current sentence preview card."""
        return self._preview_card_rect

    def get_preview_action_position(self) -> tuple[int, int]:
        """Return the ideal global screen (x, y) for the action bar below the preview card."""
        if self._preview_card_rect is None or self._preview_region is None:
            return 30, 30
        origin = self.geometry().topLeft()
        card_x = origin.x() + self._preview_card_rect.x()
        card_y = origin.y() + self._preview_card_rect.y()
        card_h = self._preview_card_rect.height()

        target_x = card_x
        target_y = card_y + card_h + 8

        desktop_h = self.height()
        if target_y + 45 > origin.y() + desktop_h:
            target_y = max(origin.y() + 10, card_y - 45)

        return target_x, target_y

    def set_style_mode(self, mode: str) -> None:
        """Switch video translation presentation style: 'auto', 'cards', 'inplace', or 'ribbon'."""
        self._style_mode = mode
        self.update()

    def set_theme(self, theme_name: str) -> None:
        """Apply a color theme style (deep_slate, oled_black, cyberpunk, frosted_glass)."""
        self._theme_name = theme_name
        self.update()

    def show_boxes(
        self,
        boxes: Sequence[TranslatedBox],
        live_region: Optional[ScreenRegion] = None,
    ) -> None:
        self._cover_virtual_desktop()
        self._boxes = list(boxes)
        self._live_region = live_region
        self._subtitle_pairs = []
        self._localized_subtitles = []
        self._subtitle_region = None
        self._preview_original = ""
        self._preview_translated = ""
        self._preview_region = None
        self._preview_card_rect = None
        if not self.isVisible():
            self.show()
        self._apply_win32_flags()
        self.update()

    def show_subtitle(
        self,
        subtitles: Sequence[LocalizedSubtitle] | Sequence[tuple[str, str]] | str,
        region: ScreenRegion,
    ) -> None:
        """Render localized video subtitle cards directly under each detected sentence on screen."""
        self._cover_virtual_desktop()
        self._subtitle_region = region
        self._boxes = []
        self._live_region = region
        self._preview_original = ""
        self._preview_translated = ""
        self._preview_region = None
        self._preview_card_rect = None
        self._localized_subtitles = []
        self._subtitle_pairs = []

        if isinstance(subtitles, str):
            if subtitles.strip():
                self._subtitle_pairs = [("", subtitles.strip())]
        elif subtitles:
            first = subtitles[0]
            if hasattr(first, "x") and hasattr(first, "translated_text"):
                self._localized_subtitles = list(subtitles)  # type: ignore
            else:
                self._subtitle_pairs = list(subtitles)  # type: ignore

        if not self.isVisible():
            self.show()
        self._apply_win32_flags()
        self.update()

    def clear_overlay(self) -> None:
        self._boxes = []
        self._live_region = None
        self._subtitle_pairs = []
        self._localized_subtitles = []
        self._subtitle_region = None
        self._preview_original = ""
        self._preview_translated = ""
        self._preview_region = None
        self._preview_card_rect = None
        self.hide()

    def _fit_font(self, text: str, max_width: int, max_height: int) -> QFont:
        font = QFont("Nirmala UI")
        font.setFamilies(["Nirmala UI", "Iskoola Pota", "Segoe UI"])
        for pt in range(min(22, max(9, int(max_height * 0.65))), 7, -1):
            font.setPointSize(pt)
            fm = QFontMetrics(font)
            bounds = fm.boundingRect(
                0,
                0,
                max(20, max_width),
                max(20, max_height * 3),
                Qt.TextFlag.TextWordWrap,
                text,
            )
            if bounds.height() <= max_height + 8 and bounds.width() <= max_width + 10:
                return font
        font.setPointSize(8)
        return font

    def _draw_subtitle_ribbon(
        self,
        painter: QPainter,
        theme,
        rx: int,
        ry: int,
        rw: int,
        rh: int,
        pairs: Sequence[tuple[str, str]],
    ) -> None:
        """Render bilingual English + translated subtitle banner at bottom of region."""
        if not pairs:
            return

        en_font = QFont("Segoe UI")
        en_font.setFamilies(["Segoe UI", "Arial", "Nirmala UI"])
        en_font.setPointSize(11)

        si_font = QFont("Nirmala UI")
        si_font.setFamilies(["Nirmala UI", "Iskoola Pota", "Segoe UI"])
        si_font.setBold(True)
        si_font.setPointSize(11)

        en_fm = QFontMetrics(en_font)
        si_fm = QFontMetrics(si_font)
        max_text_w = max(60, rw - 36)

        pair_layouts: list[dict] = []
        total_content_h = 0
        max_measured_w = 0

        for en_text, si_text in pairs:
            en_rect = QRect()
            if en_text:
                en_rect = en_fm.boundingRect(
                    0, 0, max_text_w, rh * 2,
                    Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignCenter,
                    en_text,
                )
                max_measured_w = max(max_measured_w, en_rect.width())

            si_rect = QRect()
            if si_text:
                si_rect = si_fm.boundingRect(
                    0, 0, max_text_w, rh * 2,
                    Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignCenter,
                    si_text,
                )
                max_measured_w = max(max_measured_w, si_rect.width())

            item_h = (en_rect.height() if en_text else 0) + (3 if en_text and si_text else 0) + (si_rect.height() if si_text else 0)
            pair_layouts.append({
                "en_text": en_text,
                "si_text": si_text,
                "en_rect": en_rect,
                "si_rect": si_rect,
            })
            total_content_h += item_h + 8

        if total_content_h > 0:
            total_content_h -= 8

        banner_w = min(rw - 12, max(100, max_measured_w + 32))
        banner_h = max(28, total_content_h + 12)
        banner_x = rx + (rw - banner_w) // 2
        banner_y = max(ry + 2, ry + rh - banner_h - 4)
        banner_rect = QRect(banner_x, banner_y, banner_w, banner_h)

        painter.setPen(QPen(theme.card_border, 1.5))
        painter.setBrush(theme.card_bg)
        painter.drawRoundedRect(banner_rect, 8, 8)

        cur_y = banner_y + 6
        for item in pair_layouts:
            en_text = item["en_text"]
            si_text = item["si_text"]
            if en_text:
                h = item["en_rect"].height()
                draw_box = QRect(banner_x + 16, cur_y, banner_w - 32, h)
                painter.setFont(en_font)
                painter.setPen(QColor(0, 0, 0, 210))
                painter.drawText(draw_box.adjusted(1, 1, 1, 1), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, en_text)
                painter.setPen(QColor(226, 232, 240, 255))
                painter.drawText(draw_box, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, en_text)
                cur_y += h + 3
            if si_text:
                h = item["si_rect"].height()
                draw_box = QRect(banner_x + 16, cur_y, banner_w - 32, h)
                painter.setFont(si_font)
                painter.setPen(QColor(0, 0, 0, 230))
                painter.drawText(draw_box.adjusted(1, 2, 1, 2), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, si_text)
                painter.setPen(theme.text_color)
                painter.drawText(draw_box, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, si_text)
                cur_y += h
            cur_y += 8

    def paintEvent(self, event) -> None:  # noqa: N802
        if (
            not self._boxes
            and self._live_region is None
            and not self._subtitle_pairs
            and not self._localized_subtitles
            and not (self._preview_translated and self._preview_region is not None)
        ):
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        theme = get_theme(self._theme_name)
        origin = self.geometry().topLeft()
        dpr = max(1.0, self.devicePixelRatioF())

        # 1. Single Sentence Preview Mode (Selected text highlight + Sinhala card right below it)
        if self._preview_translated and self._preview_region is not None and self._preview_card_rect is not None:
            region = self._preview_region
            rx = int(region.left / dpr) - origin.x()
            ry = int(region.top / dpr) - origin.y()
            rw = max(10, int(region.width / dpr))
            rh = max(10, int(region.height / dpr))

            # 1a. Highlight frame over the selected text (unobtrusive, readable)
            painter.setPen(QPen(theme.frame_color, 1.5, Qt.PenStyle.SolidLine))
            painter.setBrush(QColor(theme.frame_color.red(), theme.frame_color.green(), theme.frame_color.blue(), 18))
            painter.drawRoundedRect(QRect(rx, ry, rw, rh), 4, 4)

            # 1b. Sinhala Translation Preview Card right below the text ("tika yatin")
            card_rect = self._preview_card_rect
            card_x = card_rect.x()
            card_y = card_rect.y()
            card_w = card_rect.width()
            card_h = card_rect.height()
            inner_padding_x = 16
            inner_padding_y = 12
            text_avail_w = card_w - (inner_padding_x * 2)

            # Draw card drop shadow
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 90))
            painter.drawRoundedRect(card_rect.adjusted(2, 3, 2, 3), 10, 10)

            # Draw card background according to theme
            painter.setPen(QPen(theme.card_border, 1.5))
            painter.setBrush(theme.card_bg)
            painter.drawRoundedRect(card_rect, 10, 10)

            # Draw pointer notch connecting card to selected text
            notch_x = min(card_x + card_w - 24, max(card_x + 20, rx + min(30, rw // 2)))
            notch_pen = QPen(theme.card_border, 1.5)
            painter.setPen(notch_pen)
            painter.setBrush(theme.card_bg)
            if not self._preview_flipped_above:
                triangle = QPolygon([
                    QPoint(notch_x - 6, card_y),
                    QPoint(notch_x, card_y - 6),
                    QPoint(notch_x + 6, card_y),
                ])
            else:
                triangle = QPolygon([
                    QPoint(notch_x - 6, card_y + card_h),
                    QPoint(notch_x, card_y + card_h + 6),
                    QPoint(notch_x + 6, card_y + card_h),
                ])
            painter.drawPolygon(triangle)

            # 1c. Header badge: 🇱 සිංහල පරිවර්තනය (Sinhala Preview)
            header_font = QFont("Segoe UI")
            header_font.setFamilies(["Segoe UI", "Arial", "Nirmala UI"])
            header_font.setPointSize(9)
            header_font.setBold(True)
            header_h = 18

            cur_draw_y = card_y + inner_padding_y
            painter.setFont(header_font)
            painter.setPen(theme.badge_color)
            header_rect = QRect(card_x + inner_padding_x, cur_draw_y, text_avail_w, header_h)
            painter.drawText(
                header_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                "🇱 සිංහල පරිවර්තනය (Sinhala Preview)",
            )
            cur_draw_y += header_h + 6

            # 1d. Sinhala text: crystal clear, readable typography
            si_font = QFont("Nirmala UI")
            si_font.setFamilies(["Nirmala UI", "Iskoola Pota", "Segoe UI"])
            si_font.setPointSize(12)
            si_font.setBold(True)
            si_fm = QFontMetrics(si_font)
            text_rect = si_fm.boundingRect(
                0, 0, text_avail_w, 2000,
                Qt.TextFlag.TextWordWrap,
                self._preview_translated,
            )
            draw_text_box = QRect(card_x + inner_padding_x, cur_draw_y, text_avail_w, text_rect.height() + 4)
            painter.setFont(si_font)

            # Drop shadow for text
            painter.setPen(QColor(0, 0, 0, 220))
            painter.drawText(
                draw_text_box.adjusted(1, 1, 1, 1),
                Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap,
                self._preview_translated,
            )

            # High-contrast radiant text
            text_color = (
                theme.text_color
                if len(self._preview_translated) < 40
                else QColor(248, 250, 252, 255)
            )
            painter.setPen(text_color)
            painter.drawText(
                draw_text_box,
                Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap,
                self._preview_translated,
            )

            painter.end()
            return

        # 2. Localized Video Subtitle Mode (Preview cards directly below each detected sentence on screen!)
        if self._localized_subtitles and self._subtitle_region is not None:
            rx = int(self._subtitle_region.left / dpr) - origin.x()
            ry = int(self._subtitle_region.top / dpr) - origin.y()
            rw = int(self._subtitle_region.width / dpr)
            rh = int(self._subtitle_region.height / dpr)

            # Subtle dashed boundary showing active video monitoring zone
            painter.setPen(QPen(theme.frame_color, 1.2, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRect(rx, ry, rw, rh), 6, 6)

            desktop_w = self.width() if self.width() > 100 else 1920
            desktop_h = self.height() if self.height() > 100 else 1080

            # Dynamic presentation decision:
            # Detect whether this video is a dense/multi-zone stream (gaming, live casino, chat, UI-rich)
            # or a clean movie/YouTube video with isolated subtitles
            use_inplace = False
            use_ribbon = False

            if self._style_mode == "inplace":
                use_inplace = True
            elif self._style_mode == "ribbon":
                use_ribbon = True
            elif self._style_mode == "cards":
                use_inplace = False
            else:
                # "auto": Automatically decide based on density and proximity
                # 1. If 4 or more text blocks detected across the screen -> Dense Stream!
                if len(self._localized_subtitles) >= 4:
                    use_inplace = True
                else:
                    # 2. Check if any two text blocks are vertically stacked with small gap (< 25px)
                    for i in range(len(self._localized_subtitles)):
                        for j in range(i + 1, len(self._localized_subtitles)):
                            s1 = self._localized_subtitles[i]
                            s2 = self._localized_subtitles[j]
                            h_overlap = not (s1.x > s2.x + s2.width or s2.x > s1.x + s1.width)
                            if h_overlap and abs(s1.y - s2.y) < max(s1.height, s2.height) + 25:
                                use_inplace = True
                                break
                        if use_inplace:
                            break

            if use_ribbon:
                pairs = [
                    (sub.original_text, sub.translated_text)
                    for sub in self._localized_subtitles
                    if sub.translated_text
                ]
                self._draw_subtitle_ribbon(painter, theme, rx, ry, rw, rh, pairs)
                painter.end()
                return

            # A. Smart In-Place Minimal Badges (For dense streams, live casino, gaming, and chat overlays)
            if use_inplace:
                for sub in self._localized_subtitles:
                    if not sub.translated_text:
                        continue
                    sx = int(sub.x / dpr) - origin.x()
                    sy = int(sub.y / dpr) - origin.y()
                    sw = max(16, int(sub.width / dpr))
                    sh = max(14, int(sub.height / dpr))

                    pill_rect = QRect(sx - 3, sy - 2, sw + 6, sh + 4)

                    # In-place pill directly over text according to theme
                    painter.setPen(QPen(theme.card_border, 1))
                    painter.setBrush(theme.card_bg)
                    painter.drawRoundedRect(pill_rect, 4, 4)

                    font = self._fit_font(sub.translated_text, sw + 4, sh)
                    painter.setFont(font)
                    painter.setPen(QColor(0, 0, 0, 220))
                    painter.drawText(
                        pill_rect.adjusted(3, 1, -2, -1),
                        Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                        sub.translated_text,
                    )
                    # Themed radiant text
                    painter.setPen(
                        theme.text_color
                        if len(sub.translated_text) < 30
                        else QColor(248, 250, 252, 255)
                    )
                    painter.drawText(
                        pill_rect.adjusted(2, 0, -2, 0),
                        Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                        sub.translated_text,
                    )

                painter.end()
                return

            # B. Localized Under-Text Preview Cards (For clean movies, YouTube tutorials, and isolated subtitles)
            si_font = QFont("Nirmala UI")
            si_font.setFamilies(["Nirmala UI", "Iskoola Pota", "Segoe UI"])
            si_font.setPointSize(11.5)
            si_font.setBold(True)
            si_fm = QFontMetrics(si_font)

            for sub in self._localized_subtitles:
                if not sub.translated_text:
                    continue

                # 2a. Coordinate conversion
                sx = int(sub.x / dpr) - origin.x()
                sy = int(sub.y / dpr) - origin.y()
                sw = max(10, int(sub.width / dpr))
                sh = max(10, int(sub.height / dpr))

                # Highlight frame over detected English sentence
                painter.setPen(QPen(theme.frame_color, 1.2, Qt.PenStyle.SolidLine))
                painter.setBrush(QColor(theme.frame_color.red(), theme.frame_color.green(), theme.frame_color.blue(), 14))
                painter.drawRoundedRect(QRect(sx, sy, sw, sh), 4, 4)

                # 2b. Compute Card dimensions directly below THAT sentence ("eka yatin")
                inner_padding_x = 14
                inner_padding_y = 7
                card_min_w = 180
                card_max_w = min(680, desktop_w - 40)
                card_w = max(card_min_w, min(sw + 28, card_max_w))
                text_avail_w = card_w - (inner_padding_x * 2)

                text_bounds = si_fm.boundingRect(
                    0,
                    0,
                    text_avail_w,
                    2000,
                    Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignCenter,
                    sub.translated_text,
                )
                card_h = inner_padding_y + text_bounds.height() + inner_padding_y

                # Center horizontally under the detected sentence
                card_x = (sx + sw // 2) - (card_w // 2)
                if card_x + card_w > desktop_w - 12:
                    card_x = desktop_w - card_w - 12
                if card_x < 12:
                    card_x = 12

                # Position directly below the detected sentence ("eka yatin")
                card_gap = 5
                card_y = sy + sh + card_gap
                flipped_above = False
                # If too close to bottom of screen, flip directly above the sentence
                if card_y + card_h > desktop_h - 12:
                    card_y = sy - card_h - card_gap
                    flipped_above = True
                    if card_y < 12:
                        card_y = 12

                card_rect = QRect(card_x, card_y, card_w, card_h)

                # 2c. Render Card drop shadow
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(0, 0, 0, 95))
                painter.drawRoundedRect(card_rect.adjusted(2, 3, 2, 3), 8, 8)

                # 2d. Render Themed Card Background with theme border
                painter.setPen(QPen(theme.card_border, 1.2))
                painter.setBrush(theme.card_bg)
                painter.drawRoundedRect(card_rect, 8, 8)

                # 2e. Render Pointer Notch connecting card to the detected sentence
                notch_x = min(card_x + card_w - 20, max(card_x + 20, sx + sw // 2))
                notch_pen = QPen(theme.card_border, 1.2)
                painter.setPen(notch_pen)
                painter.setBrush(theme.card_bg)
                if not flipped_above:
                    triangle = QPolygon([
                        QPoint(notch_x - 5, card_y),
                        QPoint(notch_x, card_y - 5),
                        QPoint(notch_x + 5, card_y),
                    ])
                else:
                    triangle = QPolygon([
                        QPoint(notch_x - 5, card_y + card_h),
                        QPoint(notch_x, card_y + card_h + 5),
                        QPoint(notch_x + 5, card_y + card_h),
                    ])
                painter.drawPolygon(triangle)

                # 2f. Render Translated Sinhala Text
                draw_text_rect = QRect(
                    card_x + inner_padding_x,
                    card_y + inner_padding_y,
                    text_avail_w,
                    text_bounds.height() + 2,
                )
                painter.setFont(si_font)
                # Drop shadow
                painter.setPen(QColor(0, 0, 0, 230))
                painter.drawText(
                    draw_text_rect.adjusted(1, 1, 1, 1),
                    Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                    sub.translated_text,
                )
                # Themed text color
                painter.setPen(theme.text_color)
                painter.drawText(
                    draw_text_rect,
                    Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                    sub.translated_text,
                )

            painter.end()
            return

        # 3. Fallback Cinema Video Subtitle Ribbon (Bilingual: English on top, Sinhala at bottom)
        if self._subtitle_pairs and self._subtitle_region is not None:
            rx = int(self._subtitle_region.left / dpr) - origin.x()
            ry = int(self._subtitle_region.top / dpr) - origin.y()
            rw = int(self._subtitle_region.width / dpr)
            rh = int(self._subtitle_region.height / dpr)

            # Subtle frame so user knows the active video subtitle zone
            painter.setPen(QPen(theme.frame_color, 1.5, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRect(rx, ry, rw, rh), 6, 6)

            self._draw_subtitle_ribbon(painter, theme, rx, ry, rw, rh, self._subtitle_pairs)
            painter.end()
            return

        # 2. Standard In-Place Box Mode

        # Draw subtle live-watch frame so the user knows which area is monitored
        if self._live_region is not None:
            rx = int(self._live_region.left / dpr) - origin.x()
            ry = int(self._live_region.top / dpr) - origin.y()
            rw = int(self._live_region.width / dpr)
            rh = int(self._live_region.height / dpr)
            pen = QPen(theme.frame_color, 2, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRect(rx, ry, rw, rh), 8, 8)

        bg_color = theme.card_bg
        border_color = theme.card_border
        text_color = theme.text_color

        for box in self._boxes:
            lx = int(box.x / dpr) - origin.x()
            ly = int(box.y / dpr) - origin.y()
            lw = max(24, int(box.width / dpr))
            lh = max(18, int(box.height / dpr))

            rect = QRect(lx - 3, ly - 2, lw + 6, lh + 4)
            painter.setPen(QPen(border_color, 1))
            painter.setBrush(bg_color)
            painter.drawRoundedRect(rect, 5, 5)

            font = self._fit_font(box.translated_text, lw, lh)
            painter.setFont(font)
            painter.setPen(text_color)
            painter.drawText(
                rect.adjusted(4, 1, -4, -1),
                Qt.AlignmentFlag.AlignLeft
                | Qt.AlignmentFlag.AlignVCenter
                | Qt.TextFlag.TextWordWrap,
                box.translated_text,
            )

        painter.end()
