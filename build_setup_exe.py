"""Build a single downloadable WinScreenLens_Setup.exe installer."""

from __future__ import annotations

import os
import subprocess
import sys
import zipfile


def main() -> None:
    root_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(root_dir)

    app_dist_dir = os.path.join(root_dir, "dist", "WinScreenLens")
    if not os.path.isfile(os.path.join(app_dist_dir, "WinScreenLens.exe")):
        print("[Error] dist\\WinScreenLens\\WinScreenLens.exe not found. Run build_exe.py first.")
        sys.exit(1)

    build_dir = os.path.join(root_dir, "build")
    os.makedirs(build_dir, exist_ok=True)
    payload_zip = os.path.join(build_dir, "WinScreenLens_payload.zip")

    print("[1/2] Compressing application payload...")
    with zipfile.ZipFile(payload_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for folder, _, files in os.walk(app_dist_dir):
            for fname in files:
                full_path = os.path.join(folder, fname)
                rel_path = os.path.relpath(full_path, app_dist_dir)
                zf.write(full_path, rel_path)

    zip_mb = os.path.getsize(payload_zip) / (1024 * 1024)
    print(f"      Payload size: {zip_mb:.1f} MB -> {payload_zip}")

    icon_file = os.path.join(root_dir, "app", "assets", "app_icon.ico")
    setup_script = os.path.join(root_dir, "setup_wizard.py")

    print("[2/2] Packaging single-file WinScreenLens_Setup.exe...")
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--noconsole",
        "--clean",
        "--noconfirm",
        "--name=WinScreenLens_Setup",
        f"--icon={icon_file}",
        f"--add-data={payload_zip};.",
        f"--add-data={icon_file};.",
        "--exclude-module=PySide6",
        "--exclude-module=cv2",
        "--exclude-module=numpy",
        "--exclude-module=onnxruntime",
        "--exclude-module=rapidocr",
        "--exclude-module=PIL",
        setup_script,
    ]
    subprocess.run(cmd, check=True)

    setup_exe = os.path.join(root_dir, "dist", "WinScreenLens_Setup.exe")
    exe_mb = os.path.getsize(setup_exe) / (1024 * 1024)
    print("\n" + "=" * 60)
    print(" Single-File Installer Built Successfully!")
    print(f" Installer: {setup_exe} ({exe_mb:.1f} MB)")
    print("=" * 60)


if __name__ == "__main__":
    main()
