"""Main system-tray application, modular global hotkeys, lazy UI/OCR, and settings."""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLineEdit,
    QMenu,
    QSpinBox,
    QSystemTrayIcon,
    QVBoxLayout,
)

from app.config import AppConfig
from app.win32_utils import (
    enable_per_monitor_dpi_awareness,
    get_auto_start_registry,
    set_auto_start_registry,
)

if TYPE_CHECKING:
    from PIL import Image
    from app.capture import ScreenCapturer, ScreenRegion
    from app.live_worker import (
        LiveTranslateWorker,
        OneShotTranslateWorker,
        SlangExplainWorker,
        VisionQAWorker,
    )
    from app.ocr_engine import LocalOCREngine
    from app.overlay import TranslatedBox, TranslationOverlay
    from app.qa_panel import CircleActionPanel, VideoSubtitleBar
    from app.snip_selector import SnipSelector
    from app.translator import HybridTranslator
    from app.tts_player import TextToSpeechPlayer


LANGUAGE_CHOICES = [
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

FEATURE_DEFINITIONS = [
    ("feature_word_lookup", "Quick Word Lookup at Cursor (Alt+W)", "Alt+W / Ctrl+Alt+W"),
    ("feature_snip", "Region Snip Translate (Ctrl+Shift+S)", "Ctrl+Shift+S"),
    ("feature_video_subtitles", "Live Video Subtitles (Ctrl+Shift+V)", "Ctrl+Shift+V"),
    ("feature_fullscreen", "Full-Screen Translate (Ctrl+Shift+F)", "Ctrl+Shift+F"),
    ("feature_live_region", "Live Region Monitor (Ctrl+Shift+L)", "Ctrl+Shift+L"),
    ("feature_tts", "Audio Pronunciation (Listen / TTS)", ""),
    ("feature_slang", "Slang & Indirect Meaning Analysis", ""),
]


class HotkeyBridge(QObject):
    """Bridges pynput background thread callbacks safely into the Qt main thread."""

    snip_triggered = Signal()
    video_triggered = Signal()
    live_triggered = Signal()
    fullscreen_triggered = Signal()
    clear_triggered = Signal()
    hover_word_triggered = Signal()
    esc_triggered = Signal()
    tts_state_changed = Signal(bool)


class SettingsDialog(QDialog):
    """Settings dialog for language, features, Eco Mode, AI provider, theme, and startup."""

    PROVIDERS = {
        "Groq (Free & Ultra-Fast)": ("groq", "llama-3.3-70b-versatile"),
        "Google Gemini": ("gemini", "gemini-3-flash-preview"),
        "OpenRouter (Free Models)": ("openrouter", "meta-llama/llama-3.3-70b-instruct:free"),
        "OpenAI (ChatGPT)": ("openai", "gpt-4o-mini"),
    }

    LANGUAGES = [
        "Sinhala",
        "English",
        "Tamil",
        "Japanese",
        "Simplified Chinese",
        "Traditional Chinese",
        "Korean",
        "Spanish",
        "French",
        "German",
        "Russian",
        "Arabic",
        "Hindi",
    ]

    THEMES_CHOICES = [
        ("Deep Slate (Default)", "deep_slate"),
        ("OLED Pure Black", "oled_black"),
        ("Cyberpunk Neon", "cyberpunk"),
        ("Frosted Glass", "frosted_glass"),
    ]

    def __init__(self, config: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("WinScreenLens Settings")
        self.setMinimumWidth(440)

        layout = QFormLayout(self)

        self.lang_combo = QComboBox()
        self.lang_combo.setEditable(True)
        self.lang_combo.addItems(self.LANGUAGES)
        self.lang_combo.setCurrentText(config.target_language)

        self.theme_combo = QComboBox()
        for disp, t_id in self.THEMES_CHOICES:
            self.theme_combo.addItem(disp, t_id)
        for idx in range(self.theme_combo.count()):
            if self.theme_combo.itemData(idx) == config.theme:
                self.theme_combo.setCurrentIndex(idx)
                break

        # Active Features Selector
        features_box = QGroupBox("Active Features (Uncheck unused features to save resources)")
        feat_layout = QVBoxLayout(features_box)
        feat_layout.setSpacing(4)
        self.feature_cbs: dict[str, QCheckBox] = {}
        for attr, label, _ in FEATURE_DEFINITIONS:
            cb = QCheckBox(label)
            cb.setChecked(bool(getattr(config, attr, True)))
            feat_layout.addWidget(cb)
            self.feature_cbs[attr] = cb

        self.eco_cb = QCheckBox("Eco Mode — Minimum Idle RAM (load on demand, auto-free after idle)")
        self.eco_cb.setChecked(bool(config.low_resource_mode))

        self.provider_combo = QComboBox()
        self.provider_combo.addItems(list(self.PROVIDERS.keys()))

        cur_prov = config.ai_provider.lower()
        for idx, (label, (p_id, _)) in enumerate(self.PROVIDERS.items()):
            if p_id == cur_prov:
                self.provider_combo.setCurrentIndex(idx)
                break

        active_key = config.ai_api_key or config.gemini_api_key or config.groq_api_key
        self.api_key_edit = QLineEdit(active_key)
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("Paste API key here...")

        active_model = config.ai_model or config.groq_model or config.gemini_model
        self.model_edit = QLineEdit(active_model)

        def _on_provider_change(idx: int) -> None:
            label = self.provider_combo.currentText()
            _, default_m = self.PROVIDERS.get(label, ("groq", "llama-3.3-70b-versatile"))
            self.model_edit.setText(default_m)

        self.provider_combo.currentIndexChanged.connect(_on_provider_change)

        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(100, 5000)
        self.interval_spin.setSingleStep(50)
        self.interval_spin.setSuffix(" ms")
        self.interval_spin.setValue(config.live_interval_ms)

        self.autostart_cb = QCheckBox("Start WinScreenLens with Windows (Auto-start)")
        self.autostart_cb.setChecked(get_auto_start_registry())

        layout.addRow("Target language:", self.lang_combo)
        layout.addRow("Appearance Theme:", self.theme_combo)
        layout.addRow(features_box)
        layout.addRow("Performance:", self.eco_cb)
        layout.addRow("AI Provider:", self.provider_combo)
        layout.addRow("API Key:", self.api_key_edit)
        layout.addRow("AI Model:", self.model_edit)
        layout.addRow("Live poll interval:", self.interval_spin)
        layout.addRow("Startup:", self.autostart_cb)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def apply_to(self, config: AppConfig) -> None:
        config.target_language = self.lang_combo.currentText().strip() or "English"
        config.theme = self.theme_combo.itemData(self.theme_combo.currentIndex()) or "deep_slate"
        for attr, cb in self.feature_cbs.items():
            setattr(config, attr, cb.isChecked())
        config.low_resource_mode = self.eco_cb.isChecked()

        label = self.provider_combo.currentText()
        p_id, default_m = self.PROVIDERS.get(label, ("groq", "llama-3.3-70b-versatile"))
        config.ai_provider = p_id
        config.ai_api_key = self.api_key_edit.text().strip()
        config.ai_model = self.model_edit.text().strip() or default_m
        if p_id == "gemini":
            config.gemini_api_key = config.ai_api_key
            config.gemini_model = config.ai_model
        elif p_id == "groq":
            config.groq_api_key = config.ai_api_key
            config.groq_model = config.ai_model
        elif p_id == "openrouter":
            config.openrouter_api_key = config.ai_api_key
            config.openrouter_model = config.ai_model
        elif p_id == "openai":
            config.openai_api_key = config.ai_api_key
            config.openai_model = config.ai_model
        config.live_interval_ms = self.interval_spin.value()
        config.auto_start = self.autostart_cb.isChecked()
        set_auto_start_registry(config.auto_start)
        config.save()


def _safe_log(msg: str) -> None:
    """Print log line safely even when running without console (frozen .exe / pythonw)."""
    stream = sys.stdout
    if stream is not None:
        try:
            stream.write(msg + "\n")
            stream.flush()
        except Exception:
            pass


def _create_tray_icon() -> QIcon:
    pix = QPixmap(64, 64)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setBrush(QColor(16, 120, 230))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(4, 4, 56, 56, 16, 16)
    painter.setPen(QColor(255, 255, 255))
    font = painter.font()
    font.setFamilies(["Nirmala UI", "Iskoola Pota", "Segoe UI"])
    font.setPointSize(24)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "සි")
    painter.end()
    return QIcon(pix)


class WinScreenLensApp:
    """Coordinates system tray, modular global hotkeys, and lazy-loaded UI/OCR components."""

    IDLE_HIBERNATE_MS = 600_000  # Auto-release ONNX OCR after 10 min of complete inactivity

    def __init__(self, qt_app: QApplication) -> None:
        self.qt_app = qt_app
        self.config = AppConfig.load()

        # Lazy-loaded heavy components (zero memory cost until actually triggered)
        self._capturer: Optional[ScreenCapturer] = None
        self._ocr: Optional[LocalOCREngine] = None
        self._translator: Optional[HybridTranslator] = None
        self._overlay: Optional[TranslationOverlay] = None
        self._selector: Optional[SnipSelector] = None
        self._qa_panel: Optional[CircleActionPanel] = None
        self._video_bar: Optional[VideoSubtitleBar] = None
        self._tts: Optional[TextToSpeechPlayer] = None

        self._last_snip_image: Optional[Image.Image] = None
        self._last_snip_region: Optional[ScreenRegion] = None
        self._last_ocr_text: str = ""
        self._last_sinhala_text: str = ""
        self._oneshot_worker: Optional[OneShotTranslateWorker] = None
        self._qa_worker: Optional[VisionQAWorker] = None
        self._slang_worker: Optional[SlangExplainWorker] = None
        self._live_worker: Optional[LiveTranslateWorker] = None
        self._active_workers: set = set()
        self._hotkey_listener = None

        self._mode_actions: dict[str, QAction] = {}
        self._feature_actions: dict[str, QAction] = {}
        self._eco_action: Optional[QAction] = None
        self._lang_actions: list[tuple[str, QAction]] = []
        self._theme_actions: list[tuple[str, QAction]] = []
        self._autostart_action: Optional[QAction] = None

        # Single-shot timer to auto-unload OCR & trim idle RAM (0% CPU while idle)
        self._idle_timer = QTimer(self.qt_app)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.timeout.connect(self._on_idle_timeout)

        self.bridge = HotkeyBridge()
        self._wire_bridge_signals()
        self._setup_tray()
        self._start_global_hotkeys()

        if not self.config.low_resource_mode:
            self._start_background_warmup()

    # ------------------------------------------------------------------
    # Lazy component accessors (keeps startup instant & idle RAM minimal)
    # ------------------------------------------------------------------

    def _get_capturer(self) -> ScreenCapturer:
        if self._capturer is None:
            from app.capture import ScreenCapturer

            self._capturer = ScreenCapturer()
        return self._capturer

    def _get_ocr(self) -> LocalOCREngine:
        if self._ocr is None:
            from app.ocr_engine import LocalOCREngine

            self._ocr = LocalOCREngine(min_confidence=self.config.ocr_min_confidence)
        return self._ocr

    def _get_translator(self) -> HybridTranslator:
        if self._translator is None:
            from app.translator import HybridTranslator

            self._translator = HybridTranslator(
                api_key=self.config.ai_api_key or self.config.gemini_api_key or self.config.groq_api_key,
                model=self.config.ai_model or self.config.groq_model or self.config.gemini_model,
                cache_max_entries=self.config.cache_max_entries,
                engine=self.config.translation_engine,
                ai_provider=self.config.ai_provider,
            )
        return self._translator

    def _get_overlay(self) -> TranslationOverlay:
        if self._overlay is None:
            from app.overlay import TranslationOverlay

            self._overlay = TranslationOverlay(opacity=self.config.overlay_opacity)
            self._overlay.set_theme(self.config.theme)
        return self._overlay

    def _get_selector(self) -> SnipSelector:
        if self._selector is None:
            from app.snip_selector import SnipSelector

            self._selector = SnipSelector()
            self._selector.region_selected.connect(self._on_region_selected)
        return self._selector

    def _get_qa_panel(self) -> CircleActionPanel:
        if self._qa_panel is None:
            from app.qa_panel import CircleActionPanel

            self._qa_panel = CircleActionPanel()
            self._qa_panel.apply_theme(self.config.theme)
            self._qa_panel.set_current_language(self.config.target_language)
            self._qa_panel.set_feature_visibility(
                tts_enabled=self.config.feature_tts,
                slang_enabled=self.config.feature_slang,
            )
            self._qa_panel.close_requested.connect(self.clear_all)
            self._qa_panel.copy_requested.connect(self._copy_sinhala_text)
            self._qa_panel.slang_requested.connect(self._explain_last_snip_slang)
            self._qa_panel.tts_requested.connect(self._speak_text)
            self._qa_panel.tts_stop_requested.connect(self.stop_speaking)
            self._qa_panel.language_changed.connect(self.switch_target_language)
        return self._qa_panel

    def _get_video_bar(self) -> VideoSubtitleBar:
        if self._video_bar is None:
            from app.qa_panel import VideoSubtitleBar

            self._video_bar = VideoSubtitleBar()
            self._video_bar.apply_theme(self.config.theme)
            self._video_bar.cut_requested.connect(self.clear_all)
            self._video_bar.refresh_requested.connect(self.refresh_video_subtitles)
            if self._overlay is not None:
                self._video_bar.style_changed.connect(self._overlay.set_style_mode)
            else:
                self._video_bar.style_changed.connect(lambda m: self._get_overlay().set_style_mode(m))
        return self._video_bar

    def _get_tts(self) -> TextToSpeechPlayer:
        if self._tts is None:
            from app.tts_player import TextToSpeechPlayer

            self._tts = TextToSpeechPlayer(on_state_changed=self.bridge.tts_state_changed.emit)
        return self._tts

    def _track_worker(self, worker) -> None:
        """Keep QThread alive cleanly until finished so Qt never crashes destroying active threads."""
        self._active_workers.add(worker)

        def _cleanup():
            self._active_workers.discard(worker)
            worker.deleteLater()

        worker.finished.connect(_cleanup)

    def _start_background_warmup(self) -> None:
        import threading

        ocr = self._get_ocr()
        threading.Thread(target=ocr.warmup, daemon=True, name="OCRWarmup").start()

    def _schedule_idle_trim(self) -> None:
        if not self.config.low_resource_mode:
            return
        if self._live_worker is not None:
            return
        self._idle_timer.start(self.IDLE_HIBERNATE_MS)

    def _on_idle_timeout(self) -> None:
        """Free heavy OCR ONNX memory & trim working set once user finishes translating."""
        if not self.config.low_resource_mode:
            return
        if (
            self._live_worker is not None
            or self._active_workers
            or (self._overlay is not None and self._overlay.isVisible())
            or (self._qa_panel is not None and self._qa_panel.isVisible())
            or (self._video_bar is not None and self._video_bar.isVisible())
            or (self._selector is not None and self._selector.isVisible())
        ):
            return
        unloaded = self._ocr.unload() if self._ocr is not None else False
        if unloaded:
            _safe_log("[Eco Mode] Released idle OCR memory to OS.")

    def _wire_bridge_signals(self) -> None:
        self.bridge.snip_triggered.connect(lambda: self.start_snip("snip"))
        self.bridge.hover_word_triggered.connect(self.lookup_word_at_cursor)
        self.bridge.video_triggered.connect(lambda: self.start_snip("video"))
        self.bridge.live_triggered.connect(lambda: self.start_snip("live"))
        self.bridge.fullscreen_triggered.connect(self.translate_fullscreen)
        self.bridge.clear_triggered.connect(self.clear_all)
        self.bridge.esc_triggered.connect(self._on_esc_pressed)
        self.bridge.tts_state_changed.connect(self._on_tts_state_changed)

    def _setup_tray(self) -> None:
        self.tray = QSystemTrayIcon(_create_tray_icon(), self.qt_app)
        self.tray.setToolTip(f"WinScreenLens — Screen Translator ({self.config.target_language})")

        menu = QMenu()
        act_snip = QAction("Translate Region (Ctrl+Shift+S)", menu)
        act_hover = QAction("Quick Word Lookup at Cursor (Alt+W)", menu)
        act_video = QAction("Translate Video Subtitles (Ctrl+Shift+V)", menu)
        act_full = QAction("Translate Full Screen (Ctrl+Shift+F)", menu)
        act_live = QAction("Live Region Translation (Ctrl+Shift+L)", menu)
        act_clear = QAction("Clear / Stop Overlay (Esc / Ctrl+Shift+X)", menu)

        act_snip.triggered.connect(lambda: self.start_snip("snip"))
        act_hover.triggered.connect(self.lookup_word_at_cursor)
        act_video.triggered.connect(lambda: self.start_snip("video"))
        act_full.triggered.connect(self.translate_fullscreen)
        act_live.triggered.connect(lambda: self.start_snip("live"))
        act_clear.triggered.connect(self.clear_all)

        self._mode_actions = {
            "feature_snip": act_snip,
            "feature_word_lookup": act_hover,
            "feature_video_subtitles": act_video,
            "feature_fullscreen": act_full,
            "feature_live_region": act_live,
        }

        for action in (act_hover, act_snip, act_video, act_full, act_live, act_clear):
            menu.addAction(action)

        menu.addSeparator()

        # Modular Active Features Submenu (user picks only the features they need)
        feat_menu = QMenu("⚡ Enabled Features", menu)
        self._feature_actions.clear()
        for attr, label, _ in FEATURE_DEFINITIONS:
            act_f = QAction(label, feat_menu)
            act_f.setCheckable(True)
            act_f.setChecked(bool(getattr(self.config, attr, True)))
            act_f.triggered.connect(lambda checked, a=attr: self.toggle_feature(a, checked))
            feat_menu.addAction(act_f)
            self._feature_actions[attr] = act_f

        feat_menu.addSeparator()
        act_eco = QAction("🌿 Eco Mode (Minimum Idle RAM)", feat_menu)
        act_eco.setCheckable(True)
        act_eco.setChecked(self.config.low_resource_mode)
        act_eco.triggered.connect(self.toggle_eco_mode)
        feat_menu.addAction(act_eco)
        self._eco_action = act_eco
        menu.addMenu(feat_menu)

        # Multi-Language Submenu
        self._lang_actions.clear()
        lang_menu = QMenu("🌐 Target Language", menu)
        for disp, code in LANGUAGE_CHOICES:
            act_l = QAction(disp, lang_menu)
            act_l.setCheckable(True)
            act_l.setChecked(code.lower() == self.config.target_language.lower())
            act_l.triggered.connect(lambda _, c=code: self.switch_target_language(c))
            lang_menu.addAction(act_l)
            self._lang_actions.append((code, act_l))
        menu.addMenu(lang_menu)

        # Theme Appearance Submenu
        self._theme_actions.clear()
        theme_menu = QMenu("🎨 Theme / Appearance", menu)
        for disp, t_code in SettingsDialog.THEMES_CHOICES:
            act_t = QAction(disp, theme_menu)
            act_t.setCheckable(True)
            act_t.setChecked(t_code == self.config.theme)
            act_t.triggered.connect(lambda _, t=t_code: self.switch_theme(t))
            theme_menu.addAction(act_t)
            self._theme_actions.append((t_code, act_t))
        menu.addMenu(theme_menu)

        # Start with Windows checkable action
        act_autostart = QAction("📦 Start with Windows", menu)
        act_autostart.setCheckable(True)
        act_autostart.setChecked(get_auto_start_registry())
        act_autostart.triggered.connect(self.toggle_autostart)
        self._autostart_action = act_autostart
        menu.addAction(act_autostart)

        menu.aboutToShow.connect(self._sync_tray_checkmarks)

        menu.addSeparator()
        act_settings = QAction("⚙️ Settings...", menu)
        act_quit = QAction("✕ Quit", menu)
        act_settings.triggered.connect(self.open_settings)
        act_quit.triggered.connect(self.shutdown)
        menu.addAction(act_settings)
        menu.addAction(act_quit)

        self.tray.setContextMenu(menu)
        self.tray.show()
        self._sync_tray_checkmarks()

        enabled_keys = [
            hk for attr, _, hk in FEATURE_DEFINITIONS if hk and getattr(self.config, attr, True)
        ]
        summary = " | ".join(enabled_keys) if enabled_keys else "Use Tray Menu to trigger"
        self._notify("WinScreenLens Ready (Eco Mode)", summary)

    def _sync_tray_checkmarks(self) -> None:
        for attr, act in self._mode_actions.items():
            act.setVisible(bool(getattr(self.config, attr, True)))
        for attr, act in self._feature_actions.items():
            act.setChecked(bool(getattr(self.config, attr, True)))
        if self._eco_action is not None:
            self._eco_action.setChecked(self.config.low_resource_mode)

        cur_lang = self.config.target_language.lower()
        for code, act in self._lang_actions:
            act.setChecked(code.lower() == cur_lang)
        cur_theme = self.config.theme.lower()
        for t_code, act in self._theme_actions:
            act.setChecked(t_code.lower() == cur_theme)
        if self._autostart_action is not None:
            self._autostart_action.setChecked(get_auto_start_registry())

    def _stop_global_hotkeys(self) -> None:
        if self._hotkey_listener is not None:
            try:
                self._hotkey_listener.stop()
            except Exception:
                pass
            self._hotkey_listener = None

    def _start_global_hotkeys(self) -> None:
        """Register ONLY the global hotkeys for features enabled by the user."""
        self._stop_global_hotkeys()

        hotkeys: dict[str, object] = {}
        if self.config.feature_snip:
            hotkeys["<ctrl>+<shift>+s"] = self.bridge.snip_triggered.emit
        if self.config.feature_word_lookup:
            hotkeys["<ctrl>+<alt>+w"] = self.bridge.hover_word_triggered.emit
            hotkeys["<alt>+w"] = self.bridge.hover_word_triggered.emit
        if self.config.feature_video_subtitles:
            hotkeys["<ctrl>+<shift>+v"] = self.bridge.video_triggered.emit
        if self.config.feature_live_region:
            hotkeys["<ctrl>+<shift>+l"] = self.bridge.live_triggered.emit
        if self.config.feature_fullscreen:
            hotkeys["<ctrl>+<shift>+f"] = self.bridge.fullscreen_triggered.emit

        if hotkeys:
            hotkeys["<ctrl>+<shift>+x"] = self.bridge.clear_triggered.emit
            hotkeys["<esc>"] = self.bridge.esc_triggered.emit
        else:
            # All hotkeys disabled by user -> 0 keyboard hook overhead
            return

        try:
            from pynput import keyboard  # type: ignore

            self._hotkey_listener = keyboard.GlobalHotKeys(hotkeys)
            self._hotkey_listener.start()
        except Exception as exc:
            self._notify("Hotkey Warning", f"Could not register global hotkeys: {exc}")

    def toggle_feature(self, attr: str, enable: bool) -> None:
        """Enable or disable a single feature on the fly without restart."""
        setattr(self.config, attr, bool(enable))
        self.config.save()

        if attr == "feature_live_region" or attr == "feature_video_subtitles":
            if not enable and self._live_worker is not None:
                self.clear_all()

        if self._qa_panel is not None:
            self._qa_panel.set_feature_visibility(
                tts_enabled=self.config.feature_tts,
                slang_enabled=self.config.feature_slang,
            )

        self._start_global_hotkeys()
        self._sync_tray_checkmarks()
        state = "enabled" if enable else "disabled"
        pretty = attr.replace("feature_", "").replace("_", " ").title()
        self._notify("Feature Updated", f"{pretty} {state}.")

    def toggle_eco_mode(self, enable: bool) -> None:
        self.config.low_resource_mode = bool(enable)
        self.config.save()
        if enable:
            self._schedule_idle_trim()
            self._notify("Eco Mode Enabled", "Minimum idle RAM mode active.")
        else:
            self._idle_timer.stop()
            self._start_background_warmup()
            self._notify("Instant Mode Enabled", "Keeping OCR preloaded for instant snips.")

    def _notify(self, title: str, message: str) -> None:
        _safe_log(f"[{title}] {message}")
        if self.tray.isSystemTrayAvailable():
            self.tray.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, 2500)

    def start_snip(self, mode: str = "snip") -> None:
        self._idle_timer.stop()
        self.stop_speaking()
        if self._qa_panel is not None:
            self._qa_panel.hide()
        self._get_selector().begin_selection(mode=mode)

    def _on_region_selected(self, region: ScreenRegion, mode: str) -> None:
        self._idle_timer.stop()
        self.stop_speaking()
        if mode == "video":
            self.start_video_subtitle_mode(region)
            return
        if mode == "live":
            self.start_live_region(region)
            return

        try:
            img = self._get_capturer().capture_region(region)
        except Exception as exc:
            self._notify("Capture Failed", str(exc))
            self._schedule_idle_trim()
            return

        self._last_snip_image = img
        self._last_snip_region = region
        self._last_ocr_text = ""
        self._translate_last_snip()

    def _translate_last_snip(self) -> None:
        if self._last_snip_image is None or self._last_snip_region is None:
            return
        from app.live_worker import OneShotTranslateWorker

        self.stop_live_worker()
        _safe_log(f"[WinScreenLens] Translating selection to {self.config.target_language}...")
        self._oneshot_worker = OneShotTranslateWorker(
            image=self._last_snip_image,
            region=self._last_snip_region,
            ocr=self._get_ocr(),
            translator=self._get_translator(),
            target_language=self.config.target_language,
        )
        self._track_worker(self._oneshot_worker)
        self._oneshot_worker.finished_sentence.connect(self._on_oneshot_sentence_done)
        self._oneshot_worker.failed.connect(self._on_worker_error)
        self._oneshot_worker.start()

    def _on_oneshot_sentence_done(
        self, original_text: str, translated_text: str, region: ScreenRegion
    ) -> None:
        self._last_ocr_text = original_text
        self._last_sinhala_text = translated_text
        if translated_text:
            overlay = self._get_overlay()
            overlay.show_sentence_preview(original_text, translated_text, region)
            px, py = overlay.get_preview_action_position()
            panel = self._get_qa_panel()
            panel.set_feature_visibility(self.config.feature_tts, self.config.feature_slang)
            panel.open_near(px, py, text=translated_text, lang=self.config.target_language)
            self._notify(
                "WinScreenLens",
                f"Sentence translated to {self.config.target_language}.",
            )
        else:
            self._notify("WinScreenLens", "No text detected in selected area.")
            self._schedule_idle_trim()

    def _copy_sinhala_text(self) -> None:
        text_to_copy = self._last_sinhala_text
        if not text_to_copy and self._overlay is not None and self._overlay._boxes:
            text_to_copy = "\n".join([b.translated_text for b in self._overlay._boxes])
        if text_to_copy:
            self.qt_app.clipboard().setText(text_to_copy)
            if self._qa_panel is not None:
                self._qa_panel.set_copied()
            self._notify("Copied", "Translation copied to clipboard.")

    def _explain_last_snip_slang(self) -> None:
        if not self.config.feature_slang:
            return
        panel = self._get_qa_panel()
        if not self._last_ocr_text:
            panel.show_explanation("විශ්ලේෂණය කිරීමට පෙළක් හමු නොවීය. (No text detected to analyze.)")
            return

        from app.live_worker import SlangExplainWorker

        panel.show_explanation("🔍 **ව්‍යංගාර්ථය සහ Slang තේරුම විශ්ලේෂණය කරමින්...**\n\nකරුණාකර මොහොතක් රැඳී සිටින්න...")
        self._slang_worker = SlangExplainWorker(
            text=self._last_ocr_text,
            translator=self._get_translator(),
            target_language=self.config.target_language,
        )
        self._track_worker(self._slang_worker)
        self._slang_worker.explained.connect(panel.show_explanation)
        self._slang_worker.failed.connect(lambda err: panel.show_explanation(f"⚠️ දෝෂයක් සිදු විය: {err}"))
        self._slang_worker.start()

    def translate_fullscreen(self) -> None:
        from app.live_worker import OneShotTranslateWorker

        self._idle_timer.stop()
        self.stop_live_worker()
        if self._qa_panel is not None:
            self._qa_panel.hide()
        if self._overlay is not None:
            self._overlay.clear_overlay()
        try:
            img, region = self._get_capturer().capture_primary_monitor()
        except Exception as exc:
            self._notify("Capture Failed", str(exc))
            self._schedule_idle_trim()
            return

        self._oneshot_worker = OneShotTranslateWorker(
            image=img,
            region=region,
            ocr=self._get_ocr(),
            translator=self._get_translator(),
            target_language=self.config.target_language,
        )
        self._track_worker(self._oneshot_worker)
        self._oneshot_worker.finished_boxes.connect(self._on_fullscreen_done)
        self._oneshot_worker.failed.connect(self._on_worker_error)
        self._oneshot_worker.start()

    def _on_fullscreen_done(self, boxes: list[TranslatedBox], raw_ocr: str) -> None:
        self._last_ocr_text = raw_ocr
        if boxes:
            self._get_overlay().show_boxes(boxes)
            panel = self._get_qa_panel()
            panel.set_feature_visibility(self.config.feature_tts, self.config.feature_slang)
            panel.open_near(30, 30, text=raw_ocr, lang=self.config.target_language)
            self._notify(
                "Full-Screen Translate",
                f"Translated {len(boxes)} text box(es) to {self.config.target_language}.",
            )
        else:
            self._notify("Full-Screen Translate", "No text detected on primary monitor.")
            self._schedule_idle_trim()

    def refresh_video_subtitles(self) -> None:
        """Force an immediate refresh of video subtitles if playback changes or pauses."""
        if self._live_worker is not None:
            self._live_worker.force_refresh()

    def start_video_subtitle_mode(self, region: ScreenRegion) -> None:
        """Start cinema subtitle monitoring and translation over pinned video area."""
        from app.live_worker import LiveTranslateWorker

        self._idle_timer.stop()
        self.stop_live_worker()
        overlay = self._get_overlay()
        overlay.show_subtitle(
            [("Detecting subtitles...", "උපසිරැසි හඳුනාගනිමින්...")], region
        )
        self._get_video_bar().show_above(region)
        self._live_worker = LiveTranslateWorker(
            region=region,
            capturer=self._get_capturer(),
            ocr=self._get_ocr(),
            translator=self._get_translator(),
            target_language=self.config.target_language,
            interval_ms=100,
            diff_threshold=0.005,
            mode="subtitle",
        )
        self._track_worker(self._live_worker)
        self._live_worker.subtitle_updated.connect(overlay.show_subtitle)
        self._live_worker.failed.connect(self._on_worker_error)
        self._live_worker.start()
        self._notify(
            "Video Subtitles Active",
            "Translating video subtitles in real-time. Press Esc or click '✕ Cut' to stop.",
        )

    def start_live_region(self, region: ScreenRegion) -> None:
        from app.live_worker import LiveTranslateWorker

        self._idle_timer.stop()
        self.stop_live_worker()
        overlay = self._get_overlay()
        overlay.show_boxes([], live_region=region)
        self._live_worker = LiveTranslateWorker(
            region=region,
            capturer=self._get_capturer(),
            ocr=self._get_ocr(),
            translator=self._get_translator(),
            target_language=self.config.target_language,
            interval_ms=self.config.live_interval_ms,
            diff_threshold=self.config.frame_diff_threshold,
        )
        self._track_worker(self._live_worker)
        self._live_worker.boxes_updated.connect(overlay.show_boxes)
        self._live_worker.failed.connect(self._on_worker_error)
        self._live_worker.start()
        self._notify("Live Overlay Active", "Press Esc or Ctrl+Shift+X to stop live translation.")

    def stop_live_worker(self) -> None:
        if self._live_worker is not None:
            self._live_worker.stop()
            self._live_worker.wait(1500)
            self._live_worker = None

    def clear_all(self) -> None:
        self.stop_speaking()
        self.stop_live_worker()
        if self._slang_worker is not None and self._slang_worker.isRunning():
            self._slang_worker.wait(500)
        self._slang_worker = None
        if self._overlay is not None:
            self._overlay.clear_overlay()
        if self._qa_panel is not None:
            self._qa_panel.hide()
        if self._video_bar is not None:
            self._video_bar.hide()
        self._last_sinhala_text = ""
        self._last_ocr_text = ""
        self._last_snip_image = None
        self._last_snip_region = None
        self._schedule_idle_trim()

    def _on_esc_pressed(self) -> None:
        """When Esc is pressed globally, dismiss any active overlays, subtitles, or action panels."""
        is_active = (
            (self._overlay is not None and self._overlay.isVisible())
            or (self._qa_panel is not None and self._qa_panel.isVisible())
            or (self._video_bar is not None and self._video_bar.isVisible())
            or self._live_worker is not None
        )
        if is_active:
            self.clear_all()

    def _on_worker_error(self, message: str) -> None:
        if self._qa_panel is not None and self._qa_panel.isVisible():
            self._qa_panel.show_explanation(f"Error: {message}")
        else:
            self._notify("WinScreenLens Error", message)
        self._schedule_idle_trim()

    def lookup_word_at_cursor(self) -> None:
        """Instant hover/word lookup directly under the mouse pointer without dragging."""
        from app.capture import ScreenRegion

        try:
            from PySide6.QtGui import QCursor

            pos = QCursor.pos()
            gx, gy = pos.x(), pos.y()
        except Exception:
            gx, gy = 400, 300

        w, h = 260, 80
        region = ScreenRegion(
            left=max(0, gx - (w // 2)),
            top=max(0, gy - 20),
            width=w,
            height=h,
        )
        self._on_region_selected(region, "snip")

    def switch_target_language(self, new_lang: str) -> None:
        self.config.target_language = new_lang
        self.config.save()
        self.tray.setToolTip(f"WinScreenLens — Screen Translator ({new_lang})")
        if self._qa_panel is not None:
            self._qa_panel.set_current_language(new_lang)
        self._notify("Language Switched", f"Now translating to {new_lang}.")
        if self._last_snip_image is not None and self._last_snip_region is not None:
            self._translate_last_snip()

    def switch_theme(self, theme_name: str) -> None:
        self.config.theme = theme_name
        self.config.save()
        if self._overlay is not None:
            self._overlay.set_theme(theme_name)
        if self._qa_panel is not None:
            self._qa_panel.apply_theme(theme_name)
        if self._video_bar is not None:
            self._video_bar.apply_theme(theme_name)
        self._notify("Theme Changed", f"Theme set to {theme_name.replace('_', ' ').title()}.")

    def toggle_autostart(self, enable: bool) -> None:
        set_auto_start_registry(enable)
        self.config.auto_start = enable
        self.config.save()
        status = "enabled" if enable else "disabled"
        self._notify("Startup", f"Start with Windows {status}.")

    def _speak_text(self, text: str, lang: str) -> None:
        if not self.config.feature_tts:
            return
        self._get_tts().speak_async(text, lang)

    def stop_speaking(self) -> None:
        if self._tts is not None:
            self._tts.stop()
        if self._qa_panel is not None:
            self._qa_panel.set_tts_playing(False)

    def _on_tts_state_changed(self, playing: bool) -> None:
        if self._qa_panel is not None:
            self._qa_panel.set_tts_playing(playing)

    def open_settings(self) -> None:
        dlg = SettingsDialog(self.config)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            dlg.apply_to(self.config)
            if self._overlay is not None:
                self._overlay.set_theme(self.config.theme)
            if self._qa_panel is not None:
                self._qa_panel.apply_theme(self.config.theme)
                self._qa_panel.set_current_language(self.config.target_language)
                self._qa_panel.set_feature_visibility(
                    self.config.feature_tts, self.config.feature_slang
                )
            if self._video_bar is not None:
                self._video_bar.apply_theme(self.config.theme)

            self.tray.setToolTip(f"WinScreenLens — Screen Translator ({self.config.target_language})")
            self._translator = None  # Re-init lazily with updated keys/model on next use
            self._start_global_hotkeys()
            self._sync_tray_checkmarks()
            if self.config.low_resource_mode:
                self._schedule_idle_trim()
            else:
                self._idle_timer.stop()
                self._start_background_warmup()

            self._notify(
                "Settings Saved",
                f"Theme: {self.config.theme} | Target: {self.config.target_language}",
            )

    def shutdown(self) -> None:
        self._idle_timer.stop()
        self.clear_all()
        self._stop_global_hotkeys()
        if self._ocr is not None:
            self._ocr.unload()
        self.tray.hide()
        self.qt_app.quit()


def _acquire_single_instance_mutex():
    """Ensure only one instance of WinScreenLens runs at a time on Windows."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        mutex = kernel32.CreateMutexW(None, False, "WinScreenLens_SingleInstance_Mutex_v2")
        ERROR_ALREADY_EXISTS = 183
        if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            ctypes.windll.user32.MessageBoxW(
                0,
                "WinScreenLens is already running in your Windows System Tray (bottom-right).\n"
                "Right-click the blue 'සි' tray icon to configure features or quit.",
                "WinScreenLens Already Running",
                0x40,
            )
            return False
        return mutex
    except Exception:
        return None


def main() -> None:
    import signal

    _mutex_handle = _acquire_single_instance_mutex()
    if _mutex_handle is False:
        sys.exit(0)

    enable_per_monitor_dpi_awareness()
    qt_app = QApplication(sys.argv)
    qt_app.setQuitOnLastWindowClosed(False)

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(os.path.abspath(sys.executable))
    for icon_cand in (
        os.path.join(base_dir, "app", "assets", "app_icon.ico"),
        os.path.join(base_dir, "_internal", "app", "assets", "app_icon.ico"),
    ):
        if os.path.isfile(icon_cand):
            qt_app.setWindowIcon(QIcon(icon_cand))
            break

    # Only poll Ctrl+C when attached to an interactive console (0% idle wakeup in GUI mode)
    sig_timer = None
    if sys.stdin is not None and not getattr(sys, "frozen", False):
        try:
            if sys.stdin.isatty():
                sig_timer = QTimer()
                sig_timer.timeout.connect(lambda: None)
                sig_timer.start(500)
                signal.signal(signal.SIGINT, lambda *args: qt_app.quit())
        except Exception:
            pass

    _safe_log("=" * 64)
    _safe_log(" WinScreenLens — Screen Translator (Low-Resource Modular Edition)")
    _safe_log("=" * 64)
    _safe_log(" Right-click the blue 'සි' tray icon -> Enabled Features to choose features.")
    _safe_log("=" * 64)

    _controller = WinScreenLensApp(qt_app)
    sys.exit(qt_app.exec())
