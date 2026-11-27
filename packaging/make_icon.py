"""Generate high-resolution application icon (.ico and .png) for WinScreenLens."""

from __future__ import annotations

import os
from PIL import Image, ImageDraw


def create_app_icon(output_dir: str) -> str:
    os.makedirs(output_dir, exist_ok=True)
    ico_path = os.path.join(output_dir, "app_icon.ico")
    png_path = os.path.join(output_dir, "app_icon.png")

    sizes = [16, 32, 48, 64, 128, 256]
    images = []

    for size in sizes:
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        margin = max(1, size // 16)
        draw.ellipse(
            [margin, margin, size - margin, size - margin],
            fill=(18, 128, 240, 255),
            outline=(255, 255, 255, 200),
            width=max(1, size // 32),
        )

        inner_m = size // 4
        draw.ellipse(
            [inner_m, inner_m, size - inner_m, size - inner_m],
            fill=(10, 80, 180, 255),
            outline=(100, 200, 255, 220),
            width=max(1, size // 24),
        )

        center_m = size // 2 - max(1, size // 10)
        center_end = size // 2 + max(1, size // 10)
        draw.ellipse([center_m, center_m, center_end, center_end], fill=(255, 255, 255, 240))

        images.append(img)

    images[-1].save(png_path, format="PNG")
    images[-1].save(ico_path, format="ICO", sizes=[(s, s) for s in sizes])
    print(f"Generated icons:\n  {ico_path}\n  {png_path}")
    return ico_path


if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assets_dir = os.path.join(base_dir, "app", "assets")
    create_app_icon(assets_dir)
