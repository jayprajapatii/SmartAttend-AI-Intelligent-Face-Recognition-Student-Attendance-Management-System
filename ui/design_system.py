"""SmartAttend AI shared visual design system.
All UI pages use this module for consistent colors, typography and spacing.
"""

import customtkinter as ctk

# Adaptive light/dark palette
BG = ("#F5F7FB", "#0B1220")
SURFACE = ("#FFFFFF", "#111827")
SURFACE_2 = ("#F8FAFC", "#1F2937")
BORDER = ("#E2E8F0", "#334155")
TEXT = ("#0F172A", "#F8FAFC")
MUTED = ("#64748B", "#94A3B8")
PRIMARY = "#2563EB"
PRIMARY_HOVER = "#1D4ED8"
SUCCESS = "#16A34A"
WARNING = "#D97706"
DANGER = "#DC2626"
DANGER_HOVER = "#B91C1C"
INFO = "#0891B2"

FONT_FAMILY = "Segoe UI"

TITLE_FONT = (FONT_FAMILY, 24, "bold")
SECTION_FONT = (FONT_FAMILY, 16, "bold")
BODY_FONT = (FONT_FAMILY, 13)
SMALL_FONT = (FONT_FAMILY, 11)
BUTTON_FONT = (FONT_FAMILY, 12, "bold")

RADIUS = 14
CONTROL_HEIGHT = 40


def primary_button(master, text, command=None, width=140, **kwargs):
    return ctk.CTkButton(
        master, text=text, command=command, width=width,
        height=CONTROL_HEIGHT, corner_radius=10,
        fg_color=PRIMARY, hover_color=PRIMARY_HOVER,
        text_color="#FFFFFF", font=BUTTON_FONT, **kwargs
    )


def secondary_button(master, text, command=None, width=120, **kwargs):
    return ctk.CTkButton(
        master, text=text, command=command, width=width,
        height=CONTROL_HEIGHT, corner_radius=10,
        fg_color=SURFACE_2, hover_color=("#E2E8F0", "#334155"),
        border_width=1, border_color=BORDER,
        text_color=TEXT, font=BUTTON_FONT, **kwargs
    )


def danger_button(master, text, command=None, width=140, **kwargs):
    return ctk.CTkButton(
        master, text=text, command=command, width=width,
        height=CONTROL_HEIGHT, corner_radius=10,
        fg_color=DANGER, hover_color=DANGER_HOVER,
        text_color="#FFFFFF", font=BUTTON_FONT, **kwargs
    )


def card(master, **kwargs):
    return ctk.CTkFrame(
        master, fg_color=SURFACE, border_color=BORDER,
        border_width=1, corner_radius=RADIUS, **kwargs
    )


def entry(master, **kwargs):
    return ctk.CTkEntry(
        master, height=CONTROL_HEIGHT, corner_radius=10,
        fg_color=SURFACE, border_color=BORDER,
        text_color=TEXT, placeholder_text_color=MUTED,
        font=BODY_FONT, **kwargs
    )


def page_title(master, title, subtitle=None):
    wrap = ctk.CTkFrame(master, fg_color="transparent")
    ctk.CTkLabel(wrap, text=title, font=TITLE_FONT, text_color=TEXT).pack(anchor="w")
    if subtitle:
        ctk.CTkLabel(wrap, text=subtitle, font=SMALL_FONT, text_color=MUTED).pack(
            anchor="w", pady=(3, 0)
        )
    return wrap
