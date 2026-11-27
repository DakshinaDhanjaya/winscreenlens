"""Theme definitions and color palettes for WinScreenLens overlays and panels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from PySide6.QtGui import QColor


@dataclass(frozen=True)
class ThemeStyle:
    """Color and styling properties for overlays, cards, and floating action panels."""

    name: str
    display_name: str
    card_bg: QColor
    card_border: QColor
    text_color: QColor
    badge_color: QColor
    frame_color: QColor
    panel_css: str


THEMES: Dict[str, ThemeStyle] = {
    "deep_slate": ThemeStyle(
        name="deep_slate",
        display_name="Deep Slate (Default)",
        card_bg=QColor(15, 23, 42, 248),
        card_border=QColor(56, 189, 248, 175),
        text_color=QColor(254, 240, 138),
        badge_color=QColor(56, 189, 248),
        frame_color=QColor(56, 189, 248, 200),
        panel_css="""
            QWidget {
                background-color: #141824;
                color: #f1f5f9;
                font-family: 'Nirmala UI', 'Segoe UI';
                font-size: 13px;
                border: 1px solid #2d3748;
                border-radius: 16px;
            }
            QPushButton {
                background-color: #1e2433;
                color: #f8fafc;
                border: 1px solid #3b4559;
                border-radius: 10px;
                padding: 4px 12px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #1078e6;
                border-color: #1078e6;
            }
        """,
    ),
    "oled_black": ThemeStyle(
        name="oled_black",
        display_name="OLED Pure Black",
        card_bg=QColor(0, 0, 0, 255),
        card_border=QColor(255, 255, 255, 200),
        text_color=QColor(255, 255, 255),
        badge_color=QColor(203, 213, 225),
        frame_color=QColor(255, 255, 255, 210),
        panel_css="""
            QWidget {
                background-color: #000000;
                color: #ffffff;
                font-family: 'Nirmala UI', 'Segoe UI';
                font-size: 13px;
                border: 1px solid #3f3f46;
                border-radius: 16px;
            }
            QPushButton {
                background-color: #18181b;
                color: #ffffff;
                border: 1px solid #3f3f46;
                border-radius: 10px;
                padding: 4px 12px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #3f3f46;
                border-color: #71717a;
            }
        """,
    ),
    "cyberpunk": ThemeStyle(
        name="cyberpunk",
        display_name="Cyberpunk Neon",
        card_bg=QColor(24, 8, 40, 250),
        card_border=QColor(232, 121, 249, 220),
        text_color=QColor(250, 204, 21),
        badge_color=QColor(56, 189, 248),
        frame_color=QColor(232, 121, 249, 210),
        panel_css="""
            QWidget {
                background-color: #180828;
                color: #fdf4ff;
                font-family: 'Nirmala UI', 'Segoe UI';
                font-size: 13px;
                border: 1px solid #a21caf;
                border-radius: 16px;
            }
            QPushButton {
                background-color: #2e1045;
                color: #fdf4ff;
                border: 1px solid #c026d3;
                border-radius: 10px;
                padding: 4px 12px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #c026d3;
                border-color: #e879f9;
            }
        """,
    ),
    "frosted_glass": ThemeStyle(
        name="frosted_glass",
        display_name="Frosted Glass",
        card_bg=QColor(30, 41, 59, 210),
        card_border=QColor(226, 232, 240, 170),
        text_color=QColor(255, 255, 255),
        badge_color=QColor(148, 163, 184),
        frame_color=QColor(148, 163, 184, 180),
        panel_css="""
            QWidget {
                background-color: rgba(15, 23, 42, 215);
                color: #f8fafc;
                font-family: 'Nirmala UI', 'Segoe UI';
                font-size: 13px;
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 16px;
            }
            QPushButton {
                background-color: rgba(30, 41, 59, 0.85);
                color: #f8fafc;
                border: 1px solid rgba(255, 255, 255, 0.2);
                border-radius: 10px;
                padding: 4px 12px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: rgba(56, 189, 248, 0.8);
                border-color: #38bdf8;
            }
        """,
    ),
}


def get_theme(name: str = "deep_slate") -> ThemeStyle:
    """Return ThemeStyle by name, falling back to deep_slate."""
    return THEMES.get(name.lower(), THEMES["deep_slate"])
