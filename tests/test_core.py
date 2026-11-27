"""Unit tests for core capture, OCR normalization, and cached batch translation."""

from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from PIL import Image, ImageDraw

from app.capture import (
    ScreenRegion,
    compute_frame_signature,
    compute_subtitle_signature,
    frame_diff_score,
)
from app.live_worker import reconstruct_reading_order_text
from app.ocr_engine import TextBox, normalize_rapidocr_output, polygon_to_rect
from app.overlay import LocalizedSubtitle, TranslationOverlay
from app.qa_panel import VideoSubtitleBar
from app.text_filter import (
    clean_subtitle_text,
    extract_meaningful_sentences,
    group_into_localized_subtitles,
    is_meaningful_text,
)
from app.translator import (
    HybridTranslator,
    OpenAIRestClient,
    TranslationCache,
    parse_batch_translation_json,
)


class FakeModels:
    def __init__(self) -> None:
        self.calls = 0

    def generate_content(self, model, contents, config=None):
        self.calls += 1
        if isinstance(contents, list):
            return SimpleNamespace(text="This screenshot shows a settings dialog.")
        marker = "Input JSON:\n"
        if marker in contents:
            arr = json.loads(contents.split(marker, 1)[1])
            translated = [f"[ES] {item}" for item in arr]
            return SimpleNamespace(text=json.dumps({"translations": translated}))
        return SimpleNamespace(text="* Ghosted: මඟහැරියා (ignored and broke contact)")


class FakeClient:
    def __init__(self) -> None:
        self.models = FakeModels()


class TestWinScreenLensCore(unittest.TestCase):
    def test_frame_diff_detects_visual_change(self) -> None:
        img1 = Image.new("RGB", (200, 100), color=(20, 20, 20))
        img2 = Image.new("RGB", (200, 100), color=(20, 20, 20))
        img3 = Image.new("RGB", (200, 100), color=(20, 20, 20))
        ImageDraw.Draw(img3).rectangle([20, 20, 180, 80], fill=(240, 240, 240))

        sig1 = compute_frame_signature(img1)
        sig2 = compute_frame_signature(img2)
        sig3 = compute_frame_signature(img3)

        self.assertAlmostEqual(frame_diff_score(sig1, sig2), 0.0, places=5)
        self.assertGreater(frame_diff_score(sig1, sig3), 0.2)

    def test_subtitle_signature_ignores_dark_background(self) -> None:
        img1 = Image.new("RGB", (200, 100), color=(30, 30, 30))
        img2 = Image.new("RGB", (200, 100), color=(60, 60, 60))
        sig1 = compute_subtitle_signature(img1)
        sig2 = compute_subtitle_signature(img2)
        self.assertEqual(frame_diff_score(sig1, sig2), 0.0)

        img3 = Image.new("RGB", (200, 100), color=(30, 30, 30))
        ImageDraw.Draw(img3).rectangle([20, 20, 180, 80], fill=(255, 255, 255))
        sig3 = compute_subtitle_signature(img3)
        self.assertGreater(frame_diff_score(sig1, sig3), 0.05)

    def test_polygon_to_rect_and_rapidocr_v2_v1_normalization(self) -> None:
        poly = [[10.2, 20.4], [110.8, 20.1], [110.5, 45.9], [10.0, 46.0]]
        self.assertEqual(polygon_to_rect(poly), (10, 20, 101, 26))

        # RapidOCR >= 2.x object output
        v2_out = SimpleNamespace(
            boxes=[poly, poly],
            txts=["Hello", "LowConf"],
            scores=[0.95, 0.20],
        )
        boxes_v2 = normalize_rapidocr_output(v2_out, min_confidence=0.45)
        self.assertEqual(len(boxes_v2), 1)
        self.assertEqual(boxes_v2[0].text, "Hello")

        # RapidOCR 1.x tuple output
        v1_out = ([[poly, "World", 0.88]], [0.05])
        boxes_v1 = normalize_rapidocr_output(v1_out, min_confidence=0.45)
        self.assertEqual(len(boxes_v1), 1)
        self.assertEqual(boxes_v1[0].text, "World")

    def test_translation_cache_and_batch_dedup(self) -> None:
        fake = FakeClient()
        translator = HybridTranslator(api_key="test", client=fake)

        first = translator.translate_batch(["Settings", "Save"], "Spanish")
        self.assertEqual(first, ["[ES] Settings", "[ES] Save"])
        self.assertEqual(fake.models.calls, 1)

        # Second call with one cached string and one new string should only translate the new one
        second = translator.translate_batch(["Settings", "Cancel"], "Spanish")
        self.assertEqual(second, ["[ES] Settings", "[ES] Cancel"])
        self.assertEqual(fake.models.calls, 2)

        # Third call fully cached should not invoke API
        third = translator.translate_batch(["Save", "Cancel"], "Spanish")
        self.assertEqual(third, ["[ES] Save", "[ES] Cancel"])
        self.assertEqual(fake.models.calls, 2)

    def test_parse_fenced_json_response(self) -> None:
        raw = '```json\n{"translations": ["Hola", "Mundo"]}\n```'
        self.assertEqual(parse_batch_translation_json(raw, 2), ["Hola", "Mundo"])

    def test_lru_cache_eviction(self) -> None:
        cache = TranslationCache(max_entries=10)
        for i in range(12):
            cache.set("English", f"k{i}", f"v{i}")
        self.assertEqual(len(cache), 10)
        self.assertIsNone(cache.get("English", "k0"))
        self.assertEqual(cache.get("English", "k11"), "v11")

    def test_screen_region_validation(self) -> None:
        self.assertTrue(ScreenRegion(0, 0, 100, 50).is_valid())
        self.assertFalse(ScreenRegion(0, 0, 4, 4).is_valid())

    def test_explain_slang_and_indirect_meaning(self) -> None:
        fake = FakeClient()
        translator = HybridTranslator(api_key="test", client=fake)
        result = translator.explain_slang_and_indirect_meaning("He ghosted her", target_language="Sinhala")
        self.assertIn("Ghosted", result)
        self.assertEqual(fake.models.calls, 1)

    def test_explain_slang_fallback_on_gemini_failure(self) -> None:
        class FailingModels:
            def generate_content(self, *args, **kwargs):
                raise TimeoutError("Simulated Gemini timeout")

        fake = SimpleNamespace(models=FailingModels())
        translator = HybridTranslator(api_key="test", client=fake)
        result = translator.explain_slang_and_indirect_meaning("ghosted", target_language="Sinhala")
        self.assertTrue(len(result) > 10)
        self.assertNotIn("Gemini API request failed", result)

        # Contractions and pronouns like "I'm" should not be falsely extracted as slang
        result_common = translator.explain_slang_and_indirect_meaning("I'm going home", target_language="Sinhala")
        self.assertNotIn("I'm**", result_common)

    def test_clean_subtitle_text_and_meaningful_filtering(self) -> None:
        # Sound tags and speaker markers removed
        self.assertEqual(clean_subtitle_text("[Music] >> Hello world!"), "Hello world!")
        self.assertEqual(clean_subtitle_text("(Laughter) - Where are you?"), "Where are you?")
        self.assertEqual(clean_subtitle_text("♪♪ Background song ♪♪"), "")

        # Meaningful checks
        self.assertTrue(is_meaningful_text("Hello"))
        self.assertTrue(is_meaningful_text("What are you doing?"))
        self.assertTrue(is_meaningful_text("I will go"))
        self.assertTrue(is_meaningful_text("A"))

        # Non-meaningful OCR noise
        self.assertFalse(is_meaningful_text(""))
        self.assertFalse(is_meaningful_text(">>"))
        self.assertFalse(is_meaningful_text("---"))
        self.assertFalse(is_meaningful_text("12:34"))
        self.assertFalse(is_meaningful_text("01:23 / 45:00"))
        self.assertFalse(is_meaningful_text("[Music]"))
        self.assertFalse(is_meaningful_text("HD"))
        self.assertFalse(is_meaningful_text("|"))

    def test_extract_meaningful_sentences_joins_and_splits(self) -> None:
        # Multi-line single sentence
        raw = ["I have been looking for you", "all morning."]
        extracted = extract_meaningful_sentences(raw)
        self.assertEqual(extracted, ["I have been looking for you all morning."])

        # Two distinct sentences
        raw_two = ["Hurry up!", "We don't have much time."]
        extracted_two = extract_meaningful_sentences(raw_two)
        self.assertEqual(extracted_two, ["Hurry up!", "We don't have much time."])

        # Noise with dialogue
        raw_noise = ["[Music]", ">> Sit down please.", "1080p"]
        extracted_clean = extract_meaningful_sentences(raw_noise)
        self.assertEqual(extracted_clean, ["Sit down please."])

        # Pure noise produces empty list
        self.assertEqual(extract_meaningful_sentences(["[Music]", "12:34", ">>"]), [])

    def test_video_subtitle_bar_and_bilingual_overlay(self) -> None:
        import sys
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication(sys.argv)
        bar = VideoSubtitleBar()
        cut_called = []
        refresh_called = []
        style_called = []
        bar.cut_requested.connect(lambda: cut_called.append(True))
        bar.refresh_requested.connect(lambda: refresh_called.append(True))
        bar.style_changed.connect(lambda s: style_called.append(s))
        bar.btn_cut.click()
        bar.btn_refresh.click()
        bar.btn_style.click()
        self.assertEqual(len(cut_called), 1)
        self.assertEqual(len(refresh_called), 1)
        self.assertEqual(style_called, ["cards"])

        region = ScreenRegion(100, 100, 600, 120)
        bar.show_above(region)
        self.assertTrue(bar.isVisible())
        bar.hide()
        self.assertFalse(bar.isVisible())

        # Test overlay bilingual subtitle data acceptance
        overlay = TranslationOverlay()
        overlay.show_subtitle([("Where are you?", "ඔයා කොහෙද ඉන්නේ?")], region)
        self.assertEqual(len(overlay._subtitle_pairs), 1)
        self.assertEqual(overlay._subtitle_pairs[0], ("Where are you?", "ඔයා කොහෙද ඉන්නේ?"))
        overlay.clear_overlay()
        self.assertEqual(len(overlay._subtitle_pairs), 0)


    def test_openai_rest_client_and_groq_routing(self) -> None:
        translator = HybridTranslator(
            api_key="gsk_test12345",
            ai_provider="groq",
            model="llama-3.3-70b-versatile",
        )
        client = translator._ensure_client()
        self.assertIsInstance(client, OpenAIRestClient)
        self.assertEqual(client.endpoint, "https://api.groq.com/openai/v1/chat/completions")

        # OpenRouter routing
        tr_or = HybridTranslator(
            api_key="sk-or-test12345",
            ai_provider="openrouter",
        )
        client_or = tr_or._ensure_client()
        self.assertIsInstance(client_or, OpenAIRestClient)
        self.assertEqual(client_or.endpoint, "https://openrouter.ai/api/v1/chat/completions")

    def test_reconstruct_reading_order_text(self) -> None:
        # Multi-box across 2 lines in jumbled order
        boxes = [
            TextBox(x=120, y=10, width=50, height=20, text="brown"),
            TextBox(x=10, y=10, width=40, height=20, text="The"),
            TextBox(x=60, y=10, width=50, height=20, text="quick"),
            TextBox(x=10, y=40, width=40, height=20, text="fox"),
            TextBox(x=60, y=40, width=60, height=20, text="jumps."),
        ]
        sentence = reconstruct_reading_order_text(boxes)
        self.assertEqual(sentence, "The quick brown fox jumps.")

    def test_show_sentence_preview_and_card_geometry(self) -> None:
        import sys
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication(sys.argv)
        overlay = TranslationOverlay()
        region = ScreenRegion(200, 200, 400, 50)
        overlay.show_sentence_preview(
            original_text="The quick brown fox jumps.",
            translated_text="ක්ෂණික දුඹුරු හිවලා පනියි.",
            region=region,
        )

        card_rect = overlay.get_preview_card_rect()
        self.assertIsNotNone(card_rect)
        # Card should be positioned just below the region (y >= 250)
        self.assertGreaterEqual(card_rect.y(), 250)
        self.assertGreaterEqual(card_rect.width(), 320)

        # Action bar position should be under the card
        action_x, action_y = overlay.get_preview_action_position()
        self.assertEqual(action_x, card_rect.x())
        self.assertGreater(action_y, card_rect.y())

        overlay.clear_overlay()
        self.assertEqual(overlay._preview_translated, "")
        self.assertIsNone(overlay.get_preview_card_rect())

    def test_group_into_localized_subtitles_merges_lines_and_separates_distant_blocks(self) -> None:
        boxes = [
            # Top title
            TextBox(x=50, y=30, width=150, height=20, text="EPISODE 1: PILOT"),
            # Bottom multi-line dialogue (line 1 & line 2 close together)
            TextBox(x=200, y=400, width=120, height=22, text="Where are you going?"),
            TextBox(x=200, y=426, width=110, height=22, text="To the station."),
        ]
        blocks = group_into_localized_subtitles(boxes, region_left=100, region_top=50)

        # Should produce exactly 2 localized blocks: one for the top title, one for the bottom dialogue!
        self.assertEqual(len(blocks), 2)
        top_block = blocks[0]
        bottom_block = blocks[1]

        # Top block
        self.assertEqual(top_block.text, "EPISODE 1: PILOT")
        self.assertEqual(top_block.x, 150)
        self.assertEqual(top_block.y, 80)

        # Bottom block (merged dialogue lines)
        self.assertEqual(bottom_block.text, "Where are you going? To the station.")
        self.assertEqual(bottom_block.x, 300)
        self.assertEqual(bottom_block.y, 450)
        self.assertEqual(bottom_block.height, 48)  # Spans from y=400 to y=448

    def test_localized_subtitles_overlay_rendering(self) -> None:
        import sys
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication(sys.argv)
        overlay = TranslationOverlay()
        region = ScreenRegion(0, 0, 800, 600)
        localized = [
            LocalizedSubtitle(
                x=100,
                y=80,
                width=150,
                height=25,
                original_text="EPISODE 1: PILOT",
                translated_text="1 වන කථාංගය: නියමු",
            ),
            LocalizedSubtitle(
                x=250,
                y=500,
                width=300,
                height=40,
                original_text="Where are you going?",
                translated_text="ඔබ කොහෙද යන්නේ?",
            ),
        ]
        overlay.show_subtitle(localized, region)
        self.assertEqual(len(overlay._localized_subtitles), 2)
        self.assertEqual(overlay._localized_subtitles[0].translated_text, "1 වන කථාංගය: නියමු")
        self.assertEqual(overlay._localized_subtitles[1].translated_text, "ඔබ කොහෙද යන්නේ?")

        overlay.clear_overlay()
        self.assertEqual(len(overlay._localized_subtitles), 0)

    def test_user_screenshot_multiline_sentence_merging(self) -> None:
        # Exact boxes from user's uploaded image with overlapping y bounds
        b1 = TextBox(
            x=1,
            y=0,
            width=997,
            height=68,
            text="He doesn't have a copy of it. Well, we listened to",
        )
        b2 = TextBox(
            x=0,
            y=61,
            width=1019,
            height=54,
            text="the podcast where you're talking about it instead.",
        )
        blocks = group_into_localized_subtitles([b1, b2])
        self.assertEqual(len(blocks), 1)
        self.assertEqual(
            blocks[0].text,
            "He doesn't have a copy of it. Well, we listened to the podcast where you're talking about it instead.",
        )
        self.assertEqual(blocks[0].width, 1019)
        self.assertEqual(blocks[0].height, 115)

    def test_auto_density_and_inplace_stream_mode(self) -> None:
        import sys
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication(sys.argv)
        overlay = TranslationOverlay()
        region = ScreenRegion(0, 0, 1280, 720)

        # 5 scattered stream boxes (like user's live stream)
        subs = [
            LocalizedSubtitle(x=100, y=100, width=150, height=20, original_text="chat text 1", translated_text="චැට් 1"),
            LocalizedSubtitle(x=100, y=120, width=150, height=20, original_text="chat text 2", translated_text="චැට් 2"),
            LocalizedSubtitle(x=500, y=200, width=200, height=30, original_text="MAKE YOUR DECISION", translated_text="ඔබේ තීරණය"),
            LocalizedSubtitle(x=450, y=300, width=80, height=30, original_text="DOUBLE", translated_text="දෙගුණ"),
            LocalizedSubtitle(x=550, y=300, width=80, height=30, original_text="STAND", translated_text="නවත්වන්න"),
        ]

        overlay.show_subtitle(subs, region)
        self.assertEqual(len(overlay._localized_subtitles), 5)
        self.assertEqual(overlay._style_mode, "auto")

        # Test switching modes
        overlay.set_style_mode("inplace")
        self.assertEqual(overlay._style_mode, "inplace")
        overlay.set_style_mode("cards")
        self.assertEqual(overlay._style_mode, "cards")
        overlay.set_style_mode("ribbon")
        self.assertEqual(overlay._style_mode, "ribbon")

        overlay.clear_overlay()
        self.assertEqual(len(overlay._localized_subtitles), 0)

    def test_app_config_themes_and_autostart(self) -> None:
        from app.config import AppConfig

        cfg = AppConfig.from_env()
        self.assertEqual(cfg.theme, "deep_slate")
        self.assertIsInstance(cfg.auto_start, bool)

    def test_theme_manager_styles(self) -> None:
        from app.theme_manager import THEMES, get_theme

        for name in ("deep_slate", "oled_black", "cyberpunk", "frosted_glass"):
            self.assertIn(name, THEMES)
            theme = get_theme(name)
            self.assertEqual(theme.name, name)
            self.assertTrue(theme.card_bg.isValid())
            self.assertTrue(theme.card_border.isValid())
            self.assertTrue(theme.text_color.isValid())

        # Fallback test
        fallback = get_theme("unknown_theme")
        self.assertEqual(fallback.name, "deep_slate")

    def test_win32_window_rect_and_autostart_registry(self) -> None:
        from app.win32_utils import get_auto_start_registry, get_window_rect_at_point

        # Auto-start query should return a bool without throwing
        val = get_auto_start_registry()
        self.assertIsInstance(val, bool)

        # Window rect at point
        rect = get_window_rect_at_point(100, 100)
        if rect is not None:
            self.assertEqual(len(rect), 4)
            self.assertGreater(rect[2], 0)
            self.assertGreater(rect[3], 0)

    def test_circle_action_panel_tts_and_language(self) -> None:
        import sys
        from PySide6.QtWidgets import QApplication
        from app.qa_panel import CircleActionPanel

        app = QApplication.instance() or QApplication(sys.argv)
        panel = CircleActionPanel()

        received_tts = []
        received_lang = []
        panel.tts_requested.connect(lambda text, lang: received_tts.append((text, lang)))
        panel.language_changed.connect(lambda lang: received_lang.append(lang))

        panel.open_near(50, 50, text="සතුටින් ඉන්න", lang="Sinhala")
        self.assertEqual(panel._current_text, "සතුටින් ඉන්න")
        self.assertEqual(panel._current_lang, "Sinhala")

        # Test TTS trigger
        panel.btn_tts.click()
        self.assertEqual(len(received_tts), 1)
        self.assertEqual(received_tts[0], ("සතුටින් ඉන්න", "Sinhala"))

        # Test language switch
        panel.set_current_language("Tamil")
        self.assertEqual(panel._current_lang, "Tamil")

        # Test theme apply
        panel.apply_theme("cyberpunk")
        self.assertEqual(panel._current_theme, "cyberpunk")

        panel.hide()

    def test_tts_player_graceful_handling(self) -> None:
        import sys
        from PySide6.QtWidgets import QApplication
        from app.qa_panel import CircleActionPanel
        from app.tts_player import TextToSpeechPlayer, split_tts_chunks

        states: list[bool] = []
        tts = TextToSpeechPlayer(on_state_changed=states.append)
        # Empty text should safely no-op
        tts.speak_async("")
        tts.speak_async("   ")
        tts.stop()
        self.assertFalse(tts.is_speaking)

        # Chunking splits long paragraphs cleanly at <= 90 chars per chunk
        chunks = split_tts_chunks(
            "Hello there, welcome to WinScreenLens. This is a fast sentence-aware TTS chunking test.",
            max_chars=45,
        )
        self.assertGreaterEqual(len(chunks), 2)
        self.assertTrue(all(len(c) <= 45 for c in chunks))

        # CircleActionPanel TTS Play/Stop toggle
        app = QApplication.instance() or QApplication(sys.argv)
        panel = CircleActionPanel()
        stop_clicks: list[bool] = []
        panel.tts_stop_requested.connect(lambda: stop_clicks.append(True))
        panel.set_tts_playing(True)
        self.assertIn("Stop", panel.btn_tts.text())
        panel.btn_tts.click()
        self.assertEqual(len(stop_clicks), 1)
        panel.set_tts_playing(False)
        self.assertIn("Listen", panel.btn_tts.text())

    def test_bgra_zero_copy_signatures_and_ribbon_theme(self) -> None:
        import sys
        import numpy as np
        from PySide6.QtWidgets import QApplication
        from app.capture import compute_signatures_from_bgra

        # Synthetic dark BGRA frame with a bright subtitle stripe
        h, w = 64, 192
        arr = np.full((h, w, 4), 25, dtype=np.uint8)
        arr[:, :, 3] = 255
        mode_dark, raw_dark = compute_signatures_from_bgra(arr.tobytes(), w, h, subtitle_mode=True)
        self.assertEqual(float(np.sum(mode_dark)), 0.0)

        arr[20:40, 40:150, :3] = 240
        mode_sub, raw_sub = compute_signatures_from_bgra(arr.tobytes(), w, h, subtitle_mode=True)
        self.assertGreater(frame_diff_score(mode_dark, mode_sub), 0.1)
        self.assertGreater(frame_diff_score(raw_dark, raw_sub), 0.1)

        # VideoSubtitleBar.apply_theme must preserve cutBtn/videoBarRoot rules
        app = QApplication.instance() or QApplication(sys.argv)
        bar = VideoSubtitleBar()
        bar.apply_theme("cyberpunk")
        self.assertIn("QPushButton#cutBtn", bar.styleSheet())
        self.assertIn("QWidget#videoBarRoot", bar.styleSheet())

        # Ribbon mode rendering must not crash
        overlay = TranslationOverlay()
        overlay.set_style_mode("ribbon")
        region = ScreenRegion(0, 0, 800, 400)
        overlay.show_subtitle(
            [LocalizedSubtitle(100, 300, 200, 30, "Hello", "හෙලෝ")],
            region,
        )
        overlay.clear_overlay()

    def test_config_save_and_load_roundtrip(self) -> None:
        import os
        import tempfile
        from unittest.mock import patch
        from app.config import AppConfig

        with tempfile.TemporaryDirectory() as tmp:
            fake_path = os.path.join(tmp, "settings.json")
            with patch("app.config.get_settings_path", return_value=fake_path):
                cfg = AppConfig.from_env()
                cfg.target_language = "Japanese"
                cfg.theme = "oled_black"
                cfg.live_interval_ms = 300
                self.assertTrue(cfg.save())

                loaded = AppConfig.load()
                self.assertEqual(loaded.target_language, "Japanese")
                self.assertEqual(loaded.theme, "oled_black")
                self.assertEqual(loaded.live_interval_ms, 300)

                # Feature toggles persistence
                cfg.feature_video_subtitles = False
                cfg.feature_tts = False
                cfg.low_resource_mode = True
                self.assertTrue(cfg.save())
                loaded2 = AppConfig.load()
                self.assertFalse(loaded2.feature_video_subtitles)
                self.assertFalse(loaded2.feature_tts)
                self.assertTrue(loaded2.low_resource_mode)

    def test_lazy_app_init_and_feature_visibility(self) -> None:
        import sys
        from unittest.mock import patch
        from PySide6.QtWidgets import QApplication
        from app.main_app import WinScreenLensApp
        from app.ocr_engine import LocalOCREngine
        from app.qa_panel import CircleActionPanel

        app = QApplication.instance() or QApplication(sys.argv)
        with patch.object(WinScreenLensApp, "_start_global_hotkeys", return_value=None):
            controller = WinScreenLensApp(app)
            # Heavy components must remain lazy (None) at startup!
            self.assertIsNone(controller._overlay)
            self.assertIsNone(controller._selector)
            self.assertIsNone(controller._qa_panel)
            self.assertIsNone(controller._video_bar)
            self.assertIsNone(controller._ocr)
            controller.shutdown()

        # Feature visibility toggles on CircleActionPanel
        panel = CircleActionPanel()
        panel.set_feature_visibility(tts_enabled=False, slang_enabled=False)
        self.assertTrue(panel.btn_tts.isHidden())
        self.assertTrue(panel.btn_slang.isHidden())
        panel.set_feature_visibility(tts_enabled=True, slang_enabled=True)
        self.assertFalse(panel.btn_tts.isHidden())
        self.assertFalse(panel.btn_slang.isHidden())

        # LocalOCREngine.unload releases engine safely
        ocr = LocalOCREngine()
        ocr._engine = object()
        self.assertTrue(ocr.is_loaded)
        self.assertTrue(ocr.unload())
        self.assertFalse(ocr.is_loaded)


if __name__ == "__main__":
    unittest.main()
