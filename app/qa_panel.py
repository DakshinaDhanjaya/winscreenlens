"""Compact floating action bar for translated regions: Copy Sinhala, Slang/Indirect Meaning, and Close."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.capture import ScreenRegion
from app.theme_manager import get_theme
from app.win32_utils import exclude_window_from_capture


class CircleActionPanel(QWidget):
    """Sleek floating pill shown with translations: Copy Sinhala, Slang Meaning, Close."""

    close_requested = Signal()
    copy_requested = Signal()
    slang_requested = Signal()
    tts_requested = Signal(str, str)  # (text, lang)
    tts_stop_requested = Signal()
    language_changed = Signal(str)    # (new_lang)

    LANGUAGES = [
        ("Sinhala (සිංහල)", "Sinhala"),
        ("English", "English"),
        ("Tamil (தமிழ்)", "Tamil"),
        ("Japanese (日本語)", "Japanese"),
        ("German (Deutsch)", "German"),
        ("French (Français)", "French"),
        ("Spanish (Español)", "Spanish"),
        ("Hindi (हिन्दी)", "Hindi"),
        ("Chinese (中文)", "Chinese"),
        ("Russian (Русский)", "Russian"),
        ("Arabic (العربية)", "Arabic"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._current_text = ""
        self._current_lang = "Sinhala"
        self._current_theme = "deep_slate"
        self._tts_playing = False

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet(get_theme("deep_slate").panel_css)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(6)

        # Action button row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        btn_row.setContentsMargins(0, 0, 0, 0)

        self.combo_lang = QComboBox()
        for display, code in self.LANGUAGES:
            self.combo_lang.addItem(display, code)
        self.combo_lang.currentIndexChanged.connect(self._on_combo_lang_changed)

        self.btn_copy = QPushButton("📋 Copy")
        self.btn_tts = QPushButton("🔊 Listen")
        self.btn_slang = QPushButton("💡 Slang / සැබෑ අදහස")
        self.btn_slang.setObjectName("slangBtn")
        self.btn_close = QPushButton("✕ Close")
        self.btn_close.setObjectName("closeBtn")

        self.btn_copy.clicked.connect(self.copy_requested.emit)
        self.btn_tts.clicked.connect(self._on_tts_clicked)
        self.btn_slang.clicked.connect(self.slang_requested.emit)
        self.btn_close.clicked.connect(self.close_requested.emit)

        btn_row.addWidget(self.combo_lang)
        btn_row.addWidget(self.btn_copy)
        btn_row.addWidget(self.btn_tts)
        btn_row.addWidget(self.btn_slang)
        btn_row.addWidget(self.btn_close)
        root.addLayout(btn_row)

        # Collapsible explanation box for slang / indirect meaning
        self.explanation_box = QTextEdit()
        self.explanation_box.setReadOnly(True)
        self.explanation_box.setMaximumHeight(220)
        self.explanation_box.setMinimumWidth(400)
        self.explanation_box.hide()
        root.addWidget(self.explanation_box)

    def set_current_language(self, lang_name: str) -> None:
        """Update selected language in combo box without triggering re-translation loops."""
        self._current_lang = lang_name
        needle = lang_name.lower().split("(")[0].strip()
        for idx in range(self.combo_lang.count()):
            code_l = str(self.combo_lang.itemData(idx)).lower()
            disp_l = self.combo_lang.itemText(idx).lower().split("(")[0].strip()
            if code_l == needle or disp_l == needle or code_l == lang_name.lower():
                self.combo_lang.blockSignals(True)
                self.combo_lang.setCurrentIndex(idx)
                self.combo_lang.blockSignals(False)
                break

    def _on_combo_lang_changed(self, idx: int) -> None:
        lang_code = self.combo_lang.itemData(idx)
        if lang_code:
            self._current_lang = lang_code
            self.language_changed.emit(lang_code)

    def _on_tts_clicked(self) -> None:
        if self._tts_playing:
            self.tts_stop_requested.emit()
        elif self._current_text:
            self.tts_requested.emit(self._current_text, self._current_lang)

    def set_tts_playing(self, playing: bool) -> None:
        """Toggle Listen button between Play and instant Stop state."""
        self._tts_playing = bool(playing)
        if self._tts_playing:
            self.btn_tts.setText("⏹ Stop")
            self.btn_tts.setStyleSheet(
                "background-color: #991b1b; color: #fecaca; border: 1px solid #ef4444; "
                "border-radius: 10px; padding: 4px 12px; font-weight: bold;"
            )
        else:
            self.btn_tts.setText("🔊 Listen")
            self.btn_tts.setStyleSheet("")
        self.adjustSize()

    def apply_theme(self, theme_name: str) -> None:
        self._current_theme = theme_name
        style = get_theme(theme_name)
        self.setStyleSheet(style.panel_css)

    def set_feature_visibility(self, tts_enabled: bool = True, slang_enabled: bool = True) -> None:
        """Show or hide optional action buttons according to user feature selection."""
        self.btn_tts.setVisible(bool(tts_enabled))
        self.btn_slang.setVisible(bool(slang_enabled))
        if not slang_enabled:
            self.explanation_box.hide()
        self.adjustSize()

    def open_near(self, x: int, y: int, text: str = "", lang: str = "Sinhala") -> None:
        self._current_text = text
        self.set_current_language(lang)
        self.set_tts_playing(False)
        self.btn_copy.setText("📋 Copy")
        self.explanation_box.clear()
        self.explanation_box.hide()
        self.adjustSize()
        self.move(max(12, x), max(12, y))
        self.show()
        exclude_window_from_capture(int(self.winId()))

    def show_explanation(self, markdown_text: str) -> None:
        self.explanation_box.setMarkdown(markdown_text)
        self.explanation_box.show()
        self.adjustSize()

    def set_copied(self) -> None:
        self.btn_copy.setText("✓ Copied!")

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.close_requested.emit()
            event.accept()
        else:
            super().keyPressEvent(event)


class VideoSubtitleBar(QWidget):
    """Floating bar with Refresh, Style Mode, and Cut buttons for Video Subtitle Mode."""

    cut_requested = Signal()
    refresh_requested = Signal()
    style_changed = Signal(str)  # "auto", "cards", "inplace", "ribbon"

    STYLES = [
        ("✨ Style: Auto", "auto", "Automatically adapt: cards for movies, in-place badges for busy streams"),
        ("📍 Style: Cards", "cards", "Display translation cards below each text"),
        ("🪟 Style: In-Place", "inplace", "Display compact overlays directly over text (best for streams/games)"),
        ("🎬 Style: Ribbon", "ribbon", "Consolidate dialogue into a clean cinema ribbon at bottom"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._style_idx = 0
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        root = QWidget(self)
        root.setObjectName("videoBarRoot")
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(root)

        layout = QHBoxLayout(root)
        layout.setContentsMargins(12, 5, 12, 5)
        layout.setSpacing(8)

        self.label_info = QLabel("🎬 Subtitles")

        self.btn_style = QPushButton(self.STYLES[0][0])
        self.btn_style.setObjectName("styleBtn")
        self.btn_style.setToolTip(self.STYLES[0][2])
        self.btn_style.clicked.connect(self._cycle_style)

        self.btn_refresh = QPushButton("🔄 Refresh")
        self.btn_refresh.setObjectName("refreshBtn")
        self.btn_refresh.setToolTip("Force refresh subtitle translation immediately if stuck")
        self.btn_refresh.clicked.connect(self.refresh_requested.emit)

        self.btn_cut = QPushButton("✕ Cut")
        self.btn_cut.setObjectName("cutBtn")
        self.btn_cut.setToolTip("Stop video subtitle translation and close overlay (Esc / Ctrl+Shift+X)")
        self.btn_cut.clicked.connect(self.cut_requested.emit)

        layout.addWidget(self.label_info)
        layout.addWidget(self.btn_style)
        layout.addWidget(self.btn_refresh)
        layout.addWidget(self.btn_cut)
        self.apply_theme("deep_slate")

    def _cycle_style(self) -> None:
        self._style_idx = (self._style_idx + 1) % len(self.STYLES)
        label, key, tooltip = self.STYLES[self._style_idx]
        self.btn_style.setText(label)
        self.btn_style.setToolTip(tooltip)
        self.style_changed.emit(key)

    def apply_theme(self, theme_name: str) -> None:
        style = get_theme(theme_name)
        bg = style.card_bg
        border = style.card_border
        root_rgba = f"rgba({bg.red()}, {bg.green()}, {bg.blue()}, {bg.alpha()})"
        border_hex = border.name()
        self.setStyleSheet(
            f"""
            QWidget#videoBarRoot {{
                background-color: {root_rgba};
                border: 1px solid {border_hex};
                border-radius: 14px;
            }}
            QLabel {{
                color: #cbd5e1;
                font-family: 'Nirmala UI', 'Segoe UI';
                font-size: 12px;
                font-weight: 500;
                border: none;
                background: transparent;
            }}
            QPushButton#styleBtn {{
                background-color: #1e1b4b;
                color: #c7d2fe;
                border: 1px solid #4338ca;
                border-radius: 8px;
                padding: 4px 10px;
                font-family: 'Nirmala UI', 'Segoe UI';
                font-size: 12px;
                font-weight: 500;
            }}
            QPushButton#styleBtn:hover {{
                background-color: #4338ca;
                color: #ffffff;
                border-color: #6366f1;
            }}
            QPushButton#refreshBtn {{
                background-color: #0c2d48;
                color: #38bdf8;
                border: 1px solid #0284c7;
                border-radius: 8px;
                padding: 4px 12px;
                font-family: 'Nirmala UI', 'Segoe UI';
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton#refreshBtn:hover {{
                background-color: #0284c7;
                color: #ffffff;
                border-color: #38bdf8;
            }}
            QPushButton#cutBtn {{
                background-color: #7f1d1d;
                color: #fecaca;
                border: 1px solid #991b1b;
                border-radius: 8px;
                padding: 4px 14px;
                font-family: 'Nirmala UI', 'Segoe UI';
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton#cutBtn:hover {{
                background-color: #dc2626;
                color: #ffffff;
                border-color: #ef4444;
            }}
            """
        )

    def show_above(self, region: ScreenRegion) -> None:
        self.adjustSize()
        w = max(340, self.sizeHint().width())
        h = max(36, self.sizeHint().height())
        # Pin above top-right of subtitle box
        x = max(10, region.left + region.width - w)
        y = region.top - h - 6
        if y < 10:
            y = region.top + region.height + 6
        self.resize(w, h)
        self.move(x, y)
        self.show()
        exclude_window_from_capture(int(self.winId()))

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.cut_requested.emit()
            event.accept()
        else:
            super().keyPressEvent(event)



