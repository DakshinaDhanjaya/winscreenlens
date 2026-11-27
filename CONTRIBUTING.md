# Contributing to WinScreenLens

Thank you for your interest in contributing to **WinScreenLens**! Contributions, bug reports, and feature ideas are always welcome.

---

## Getting Started

1. **Fork** this repository on GitHub.
2. **Clone** your fork locally:
   ```powershell
   git clone https://github.com/YOUR_USERNAME/winscreenlens.git
   cd winscreenlens
   ```
3. **Create a branch** for your work:
   ```powershell
   git checkout -b feature/your-feature-name
   ```
4. **Set up your development environment** (Windows 10/11, Python 3.10+):
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\activate
   pip install -r requirements.txt
   ```

---

## Running Tests

Always run the unit test suite before opening a Pull Request:

```powershell
python -m unittest discover -s tests -v
```

To simulate the headless GitHub Actions environment locally:

```powershell
$env:QT_QPA_PLATFORM="offscreen"
python -m unittest discover -s tests -v
```

---

## Code Guidelines

- Keep modules focused, readable, and consistent with existing type annotations (`from __future__ import annotations`).
- Avoid adding heavy runtime dependencies or eagerly loading large models/windows at startup — **Eco Mode** and low idle resource usage are core priorities.
- Never commit `.env` files, personal API keys, virtual environments (`.venv/`), or compiled binaries (`dist/`, `build/`).
- Add or update unit tests in `tests/test_core.py` for any new logic or bug fixes.

---

## Building Locally (Optional)

If your change affects packaging or installers, verify local builds with:

```powershell
pip install pyinstaller
python packaging\build_exe.py
python packaging\build_setup_exe.py
```

---

## Submitting a Pull Request

1. Push your branch to your fork:
   ```powershell
   git push origin feature/your-feature-name
   ```
2. Open a Pull Request against `main` using the PR template, describing what changed and confirming all unit tests pass.
