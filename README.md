# WinScreenLens

[![Windows CI](https://github.com/DakshinaDhanjaya/winscreenlens/actions/workflows/ci.yml/badge.svg)](https://github.com/DakshinaDhanjaya/winscreenlens/actions/workflows/ci.yml)
![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%2F%2011-0078D6?logo=windows)
![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python)
![License](https://img.shields.io/badge/License-MIT-green)

**WinScreenLens** is a lightweight, low-resource Windows desktop utility built with **Python + PySide6** and **RapidOCR (ONNX Runtime)**. It delivers instant cursor word/sentence lookup, real-time bilingual video subtitle translation, screen region snipping, audio pronunciation (TTS), and slang/idiom explanations with native **Sinhala (සිංහල)** and multi-language support.

---

## Key Features

- **Low-Resource Eco Mode & Lazy Loading:** Loads UI windows and RapidOCR ONNX models strictly on demand, caps ONNX threads, uses zero-copy BGRA frame-diffing for paused video (0% idle OCR CPU), and automatically releases OCR models + trims idle working-set RAM after 90 seconds of inactivity.
- **Modular Feature Toggles:** Enable or disable individual features anytime from the System Tray (**⚡ Enabled Features**) or **Settings** — unused hotkeys and UI buttons are dynamically unregistered without restarting.
- **Instant Cursor Lookup (`Alt + W`):** Translates the word or sentence right under your mouse pointer without dragging.
- **Smart Region Snip (`Ctrl + Shift + S`):** Drag a box, lasso (`Right-drag` / `Alt + drag`), or single-click a window to magnetically snap and translate with Copy, TTS Listen, and **Slang / Indirect Meaning** breakdown.
- **Live Video Subtitle Mode (`Ctrl + Shift + V`):** Pin across any video player or stream with dynamic layout styles (**Auto**, **Cards**, **In-Place**, and **Cinema Ribbon**) plus floating **Refresh** and **Cut** controls.
- **Full-Screen & Live Monitor:** Translate an entire monitor (`Ctrl + Shift + F`) or pin any live-updating screen region (`Ctrl + Shift + L`).
- **Invisible to Screen Capture:** Uses Windows `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)` and `WS_EX_TRANSPARENT` click-through flags so overlays never interfere with mouse clicks or trigger self-OCR loops.
- **Multi-Language & 4 Themes:** Supports Sinhala, English, Tamil, Japanese, German, French, Spanish, Hindi, Chinese, Korean, Russian, and Arabic across **Deep Slate**, **OLED Pure Black**, **Cyberpunk Neon**, and **Frosted Glass** themes.

---

## Global Hotkeys

| Hotkey | Mode | Description |
| :--- | :--- | :--- |
| **`Alt + W`** or **`Ctrl + Alt + W`** | **Cursor Lookup** | Translate the word or sentence directly under the mouse cursor |
| **`Ctrl + Shift + S`** | **Region Snip** | Select an area (or click a window) to translate + Copy / TTS / Slang |
| **`Ctrl + Shift + V`** | **Video Subtitles** | Live bilingual subtitle overlay for videos and streams |
| **`Ctrl + Shift + F`** | **Full-Screen OCR** | Translate all detected text on the primary monitor |
| **`Ctrl + Shift + L`** | **Live Region** | Continuously watch and translate a pinned region |
| **`Esc`** or **`Ctrl + Shift + X`** | **Cut / Dismiss** | Immediately close overlays, panels, or stop live watchers |

---

## Quick Start

### 1. Run from Source (Windows 10 / 11)

```powershell
git clone https://github.com/DakshinaDhanjaya/winscreenlens.git
cd winscreenlens

python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt

# Optional: configure an AI key for advanced slang/Q&A (Google Translate works out of the box with zero key)
copy .env.example .env

python run.py
```

Or double-click **`Launch_WinScreenLens.vbs`** to run silently in the background via `pythonw.exe` (no console window), or **`Install_WinScreenLens.bat`** to install Desktop & Start Menu shortcuts.

---

## Building the Standalone Executable & Installer

1. **Build the lean standalone app (`dist\WinScreenLens\WinScreenLens.exe`):**
   ```powershell
   pip install pyinstaller
   python packaging\build_exe.py
   ```
2. **Package the single-file GUI Setup Installer (`dist\WinScreenLens_Setup.exe`):**
   ```powershell
   python packaging\build_setup_exe.py
   ```
   > **Note on Windows 11 Smart App Control:** Locally compiled unsigned `.exe` binaries will be blocked by Windows Smart App Control if it is set to *On*. Switch **Windows Security ➔ App & browser control ➔ Smart App Control settings** to **Off** to run locally built `.exe` installers, or launch via `Launch_WinScreenLens.vbs`.

---

## Project Structure

```text
winscreenlens/
├── .github/
│   └── workflows/
│       └── ci.yml                  # Automated Windows CI tests
├── app/                            # Core application package
│   ├── assets/                     # App icon (.ico / .png)
│   ├── capture.py                  # mss capture & zero-copy BGRA frame-diffing
│   ├── config.py                   # .env + persistent settings.json
│   ├── live_worker.py              # Background QThread workers
│   ├── main_app.py                 # System tray app, lazy loader, Eco Mode & hotkeys
│   ├── ocr_engine.py               # Thread-safe RapidOCR ONNX wrapper with unload()
│   ├── overlay.py                  # Click-through capture-excluded Qt overlay
│   ├── qa_panel.py                 # Floating action bar & video subtitle controls
│   ├── snip_selector.py            # Snipping, lasso & window-snap selector
│   ├── text_filter.py              # Subtitle cleanup & sentence grouping
│   ├── theme_manager.py            # 4 built-in color palettes
│   ├── translator.py               # LRU cache, Google Translate failover & AI clients
│   ├── tts_player.py               # Async Windows SAPI & Google TTS player
│   └── win32_utils.py              # Win32 DPI, display affinity & memory trimming
├── packaging/                      # Build & installer tooling
│   ├── build_exe.py                # Lean PyInstaller app builder
│   ├── build_setup_exe.py          # Single-file WinScreenLens_Setup.exe packager
│   ├── setup_wizard.py             # GUI Setup Wizard for WinScreenLens_Setup.exe
│   ├── installer.py                # Local shortcut & install helper
│   └── make_icon.py                # Icon asset generator
├── tests/
│   └── test_core.py                # Unit test suite (27 tests)
├── Install_WinScreenLens.bat       # 1-Click local installer
├── Launch_WinScreenLens.vbs        # 1-Click silent launcher (zero console)
├── run.py                          # Application entry point
├── requirements.txt
├── .env.example
└── LICENSE
```

---

## Running Unit Tests

```powershell
python -m unittest discover -s tests -v
```

---

## License

Released under the [MIT License](LICENSE).
