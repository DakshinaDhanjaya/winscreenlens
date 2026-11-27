"""Circle-to-Search style full-screen snipping overlay (rectangle or freehand circle)."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QWidget

from app.capture import ScreenRegion
from app.win32_utils import exclude_window_from_capture, get_window_rect_at_point


class SnipSelector(QWidget):
    """Translucent overlay letting the user drag a box or circle an area."""

    region_selected = Signal(object, str)  # (ScreenRegion, mode)
    cancelled = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._mode = "snip"
        self._dragging = False
        self._freehand = False
        self._start = QPoint()
        self._end = QPoint()
        self._points: list[QPoint] = []
        self._hovered_window_rect: Optional[QRect] = None
        self._press_pos: Optional[QPoint] = None
        self._last_hover_probe = QPoint(-9999, -9999)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def begin_selection(self, mode: str = "snip") -> None:
        """Show selector across all monitors for 'snip' or 'live' mode."""
        self._mode = mode
        self._dragging = False
        self._freehand = False
        self._points.clear()
        self._hovered_window_rect = None
        self._press_pos = None

        desktop_geo = QRect()
        for screen in QApplication.screens():
            desktop_geo = desktop_geo.united(screen.geometry())
        self.setGeometry(desktop_geo)
        self.show()
        exclude_window_from_capture(int(self.winId()))
        self.activateWindow()
        self.raise_()
        self.update()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            self.cancelled.emit()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            self._dragging = True
            self._press_pos = event.position().toPoint()
            # Right-drag or Alt+Left-drag draws a freehand Circle-to-Search lasso
            self._freehand = (
                event.button() == Qt.MouseButton.RightButton
                or bool(event.modifiers() & Qt.KeyboardModifier.AltModifier)
            )
            self._start = self._press_pos
            self._end = self._start
            self._points = [self._start]
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pt = event.position().toPoint()
        if not self._dragging:
            if (pt - self._last_hover_probe).manhattanLength() < 8:
                return
            self._last_hover_probe = pt
            origin = self.geometry().topLeft()
            gx = pt.x() + origin.x()
            gy = pt.y() + origin.y()
            rect_tuple = get_window_rect_at_point(gx, gy, ignore_hwnds={int(self.winId())})
            new_rect = (
                QRect(rect_tuple[0] - origin.x(), rect_tuple[1] - origin.y(), rect_tuple[2], rect_tuple[3])
                if rect_tuple
                else None
            )
            if new_rect != self._hovered_window_rect:
                self._hovered_window_rect = new_rect
                self.update()
            return

        self._end = pt
        if self._freehand:
            self._points.append(pt)
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if not self._dragging:
            return
        self._dragging = False
        self.hide()

        rel_pt = event.position().toPoint()
        click_distance = (rel_pt - (self._press_pos or rel_pt)).manhattanLength()
        # If user did a single click on a detected window/player, snap to whole window!
        if click_distance < 8 and self._hovered_window_rect is not None:
            rect = self._hovered_window_rect
        else:
            rect = self._selection_rect()

        if rect.width() < 12 or rect.height() < 12:
            self.cancelled.emit()
            return

        origin = self.geometry().topLeft()
        dpr = max(1.0, self.devicePixelRatioF())
        region = ScreenRegion(
            left=int((rect.left() + origin.x()) * dpr),
            top=int((rect.top() + origin.y()) * dpr),
            width=int(rect.width() * dpr),
            height=int(rect.height() * dpr),
        )
        self.region_selected.emit(region, self._mode)

    def _selection_rect(self) -> QRect:
        if self._freehand and self._points:
            xs = [p.x() for p in self._points]
            ys = [p.y() for p in self._points]
            return QRect(
                QPoint(min(xs), min(ys)),
                QPoint(max(xs), max(ys)),
            ).normalized()
        return QRect(self._start, self._end).normalized()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Dim the screen subtly like Android Circle to Search
        painter.fillRect(self.rect(), QColor(10, 14, 24, 95))

        # Top instruction pill
        if self._mode == "video":
            hint = "Drag a strip across the video subtitle area (සිංහල උපසිරැසි)  •  Esc to cancel"
        elif self._mode == "live":
            hint = "Drag to pin a live real-time translation region (සිංහල)  •  Esc to cancel"
        else:
            hint = "Select any screen area to translate to Sinhala (සිංහල)  •  Esc to cancel"
        pill_w = min(660, self.width() - 40)
        pill_rect = QRect((self.width() - pill_w) // 2, 24, pill_w, 36)
        painter.setPen(QPen(QColor(138, 180, 248, 170), 1))
        painter.setBrush(QColor(20, 24, 34, 225))
        painter.drawRoundedRect(pill_rect, 18, 18)
        font = painter.font()
        font.setFamilies(["Nirmala UI", "Segoe UI"])
        font.setPointSize(11)
        painter.setFont(font)
        painter.setPen(QColor(240, 244, 252))
        painter.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, hint)

        # Smart Window / Video Player magnetic snap highlight
        if not self._dragging and self._hovered_window_rect is not None:
            w_rect = self._hovered_window_rect
            painter.setPen(QPen(QColor(56, 189, 248, 220), 2.5, Qt.PenStyle.DashLine))
            painter.setBrush(QColor(56, 189, 248, 22))
            painter.drawRoundedRect(w_rect, 6, 6)

            badge_w = 260
            badge_rect = QRect(w_rect.x() + 8, max(68, w_rect.y() + 8), badge_w, 26)
            painter.setPen(QPen(QColor(56, 189, 248, 200), 1))
            painter.setBrush(QColor(15, 23, 42, 230))
            painter.drawRoundedRect(badge_rect, 6, 6)
            font_badge = painter.font()
            font_badge.setPointSize(9)
            font_badge.setBold(True)
            painter.setFont(font_badge)
            painter.setPen(QColor(248, 250, 252))
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, "🪟 Click to snap window / player")

        if self._dragging:
            sel_rect = self._selection_rect()
            if self._freehand and len(self._points) > 1:
                path = QPainterPath(self._points[0])
                for pt in self._points[1:]:
                    path.lineTo(pt)
                painter.setPen(QPen(QColor(138, 180, 248, 245), 3.5))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(path)

            painter.setPen(QPen(QColor(66, 133, 244, 240), 2))
            painter.setBrush(QColor(66, 133, 244, 32))
            painter.drawRoundedRect(sel_rect, 8, 8)

        painter.end()
