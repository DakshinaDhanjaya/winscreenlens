"""Runtime configuration loaded from .env and persistent user settings."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional in bare test environments
    load_dotenv = None


def get_app_base_dir() -> str:
    """Return the application directory (works both frozen .exe and source script)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_user_config_dir() -> str:
    """Return writable user configuration directory (%LOCALAPPDATA%\\WinScreenLens)."""
    local_app_data = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
    cfg_dir = os.path.join(local_app_data, "WinScreenLens")
    try:
        os.makedirs(cfg_dir, exist_ok=True)
        return cfg_dir
    except OSError:
        return get_app_base_dir()


def get_settings_path() -> str:
    return os.path.join(get_user_config_dir(), "settings.json")


@dataclass
class AppConfig:
    """User-configurable settings for WinScreenLens."""

    target_language: str = "Sinhala"
    translation_engine: str = "google"
    ai_provider: str = "gemini"  # 'gemini', 'groq', 'openrouter', 'openai'
    ai_api_key: str = ""
    ai_model: str = "gemini-3-flash-preview"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3-flash-preview"
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    openrouter_api_key: str = ""
    openrouter_model: str = "meta-llama/llama-3.3-70b-instruct:free"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    live_interval_ms: int = 450
    frame_diff_threshold: float = 0.015
    overlay_opacity: int = 220
    cache_max_entries: int = 1500
    ocr_min_confidence: float = 0.45
    theme: str = "deep_slate"
    auto_start: bool = False
    low_resource_mode: bool = True
    feature_snip: bool = True
    feature_word_lookup: bool = True
    feature_video_subtitles: bool = True
    feature_fullscreen: bool = True
    feature_live_region: bool = True
    feature_tts: bool = True
    feature_slang: bool = True

    @classmethod
    def from_env(cls) -> "AppConfig":
        if load_dotenv is not None:
            env_path = os.path.join(get_app_base_dir(), ".env")
            if os.path.isfile(env_path):
                load_dotenv(env_path)
            else:
                load_dotenv()

        def _int(name: str, default: int) -> int:
            try:
                return int(os.getenv(name, str(default)))
            except ValueError:
                return default

        def _float(name: str, default: float) -> float:
            try:
                return float(os.getenv(name, str(default)))
            except ValueError:
                return default

        provider = os.getenv("AI_PROVIDER", "").strip().lower()
        gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
        groq_key = os.getenv("GROQ_API_KEY", "").strip()
        openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        openai_key = os.getenv("OPENAI_API_KEY", "").strip()

        # Auto-detect provider if not explicitly specified
        if not provider:
            if groq_key:
                provider = "groq"
            elif openrouter_key:
                provider = "openrouter"
            elif openai_key:
                provider = "openai"
            elif gemini_key:
                provider = "gemini"
            else:
                provider = "groq"

        # Active key & model based on chosen provider
        if provider == "groq":
            active_key = groq_key or os.getenv("AI_API_KEY", "").strip()
            active_model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip()
        elif provider == "openrouter":
            active_key = openrouter_key or os.getenv("AI_API_KEY", "").strip()
            active_model = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free").strip()
        elif provider == "openai":
            active_key = openai_key or os.getenv("AI_API_KEY", "").strip()
            active_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
        else:  # gemini
            active_key = gemini_key or os.getenv("AI_API_KEY", "").strip()
            active_model = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview").strip()

        return cls(
            target_language=os.getenv("TARGET_LANGUAGE", "Sinhala").strip() or "Sinhala",
            translation_engine=os.getenv("TRANSLATION_ENGINE", "google").strip() or "google",
            ai_provider=provider,
            ai_api_key=active_key,
            ai_model=active_model,
            gemini_api_key=gemini_key,
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-3-flash-preview").strip() or "gemini-3-flash-preview",
            groq_api_key=groq_key,
            groq_model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip() or "llama-3.3-70b-versatile",
            openrouter_api_key=openrouter_key,
            openrouter_model=os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free").strip(),
            openai_api_key=openai_key,
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini",
            live_interval_ms=max(150, _int("LIVE_INTERVAL_MS", 450)),
            frame_diff_threshold=max(0.001, min(0.5, _float("FRAME_DIFF_THRESHOLD", 0.015))),
            overlay_opacity=max(80, min(255, _int("OVERLAY_OPACITY", 220))),
            cache_max_entries=max(100, _int("CACHE_MAX_ENTRIES", 1500)),
            ocr_min_confidence=max(0.0, min(1.0, _float("OCR_MIN_CONFIDENCE", 0.45))),
            theme=os.getenv("THEME", "deep_slate").strip().lower() or "deep_slate",
            auto_start=os.getenv("AUTO_START", "false").strip().lower() in ("1", "true", "yes"),
        )

    @classmethod
    def load(cls) -> "AppConfig":
        """Load baseline .env configuration and apply persisted user settings.json."""
        cfg = cls.from_env()
        settings_path = get_settings_path()
        if os.path.isfile(settings_path):
            try:
                with open(settings_path, "r", encoding="utf-8") as fh:
                    saved = json.load(fh)
                if isinstance(saved, dict):
                    for field_name in (
                        "target_language",
                        "translation_engine",
                        "ai_provider",
                        "ai_api_key",
                        "ai_model",
                        "gemini_api_key",
                        "gemini_model",
                        "groq_api_key",
                        "groq_model",
                        "openrouter_api_key",
                        "openrouter_model",
                        "openai_api_key",
                        "openai_model",
                        "theme",
                    ):
                        val = saved.get(field_name)
                        if isinstance(val, str) and val.strip():
                            setattr(cfg, field_name, val.strip())
                    if "live_interval_ms" in saved:
                        cfg.live_interval_ms = max(100, min(5000, int(saved["live_interval_ms"])))
                    for bool_field in (
                        "auto_start",
                        "low_resource_mode",
                        "feature_snip",
                        "feature_word_lookup",
                        "feature_video_subtitles",
                        "feature_fullscreen",
                        "feature_live_region",
                        "feature_tts",
                        "feature_slang",
                    ):
                        if bool_field in saved:
                            setattr(cfg, bool_field, bool(saved[bool_field]))
            except Exception:
                pass
        return cfg

    def save(self) -> bool:
        """Persist user configuration safely to %LOCALAPPDATA%\\WinScreenLens\\settings.json."""
        settings_path = get_settings_path()
        tmp_path = f"{settings_path}.tmp"
        try:
            os.makedirs(os.path.dirname(settings_path), exist_ok=True)
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(asdict(self), fh, indent=2, ensure_ascii=False)
            os.replace(tmp_path, settings_path)
            return True
        except Exception:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass
            return False
