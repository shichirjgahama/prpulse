"""Тема и палитра Tkinter-интерфейса."""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

BG = "#f1f5f9"
SURFACE = "#ffffff"
SURFACE_ALT = "#f8fafc"
BORDER = "#e2e8f0"
INK = "#0f172a"
MUTED = "#64748b"
ACCENT = "#0f766e"
ACCENT_DARK = "#115e59"
NAV_BG = "#0b1220"
NAV_ACTIVE = "#16324a"
NAV_TEXT = "#cbd5e1"
GREEN = "#16a34a"
YELLOW = "#d97706"
ORANGE = "#ea580c"
RED = "#dc2626"
BLUE = "#2563eb"
PURPLE = "#7c3aed"

SEVERITY = {"critical": RED, "warning": YELLOW, "info": BLUE}
SERIES_COLORS = ["#0f766e", "#2563eb", "#c2410c", "#7c3aed", "#be123c", "#0891b2"]


def font_family() -> str:
    try:
        families = set(tkfont.families())
        for candidate in ("Segoe UI", "Inter", "Arial"):
            if candidate in families:
                return candidate
    except tk.TclError:  # pragma: no cover - без дисплея
        pass
    return "TkDefaultFont"


def ui_font(size: int = 10, weight: str = "normal") -> tuple:
    return (font_family(), size, weight)


def mono_font(size: int = 9) -> tuple:
    try:
        families = set(tkfont.families())
        for candidate in ("Cascadia Mono", "Consolas", "Courier New"):
            if candidate in families:
                return (candidate, size)
    except tk.TclError:  # pragma: no cover
        pass
    return ("TkFixedFont", size)


def apply_theme(root: tk.Misc) -> None:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure(".", font=ui_font(10), background=BG, foreground=INK)
    style.configure("TFrame", background=BG)
    style.configure("Surface.TFrame", background=SURFACE)
    style.configure("TLabel", background=BG, foreground=INK)
    style.configure("Surface.TLabel", background=SURFACE, foreground=INK)
    style.configure("Muted.TLabel", background=BG, foreground=MUTED)
    style.configure("SurfaceMuted.TLabel", background=SURFACE, foreground=MUTED)
    style.configure("H1.TLabel", background=BG, foreground=INK, font=ui_font(22, "bold"))
    style.configure("H2.TLabel", background=SURFACE, foreground=INK, font=ui_font(14, "bold"))
    style.configure("H3.TLabel", background=SURFACE, foreground=INK, font=ui_font(10, "bold"))
    style.configure("Kpi.TLabel", background=SURFACE, foreground=INK, font=ui_font(19, "bold"))
    style.configure("KpiTitle.TLabel", background=SURFACE, foreground=MUTED, font=ui_font(8, "bold"))
    style.configure("TButton", padding=(12, 6), font=ui_font(9), background=SURFACE, foreground=INK)
    style.map(
        "TButton",
        background=[("active", "#e2e8f0"), ("disabled", "#f1f5f9")],
        foreground=[("disabled", "#94a3b8")],
    )
    style.configure("Accent.TButton", background=ACCENT, foreground="#ffffff", font=ui_font(9, "bold"))
    style.map(
        "Accent.TButton",
        background=[("active", ACCENT_DARK), ("disabled", "#94a3b8")],
        foreground=[("disabled", "#f8fafc")],
    )
    style.configure("Ghost.TButton", background=BG, foreground=MUTED)
    style.map("Ghost.TButton", background=[("active", "#e2e8f0")])
    style.configure("TEntry", padding=6, fieldbackground=SURFACE)
    style.configure("TCombobox", padding=5)
    style.configure("Treeview", background=SURFACE, fieldbackground=SURFACE, foreground=INK, rowheight=25, font=ui_font(9))
    style.configure("Treeview.Heading", font=ui_font(8, "bold"), background=SURFACE_ALT, foreground=MUTED)
    style.map("Treeview", background=[("selected", "#ccfbf1")], foreground=[("selected", INK)])
    style.configure("TNotebook", background=BG, borderwidth=0)
    style.configure("TNotebook.Tab", padding=(12, 6))
    style.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor=BORDER)
    style.configure("Card.TFrame", background=SURFACE, relief="flat", borderwidth=0)
    style.configure("Nav.TFrame", background=NAV_BG)
    style.configure("Status.TFrame", background=SURFACE_ALT)
    style.configure("Status.TLabel", background=SURFACE_ALT, foreground=MUTED, font=ui_font(8))
    style.configure("TLabelframe", background=SURFACE, bordercolor=BORDER)
    style.configure("TLabelframe.Label", background=SURFACE, foreground=INK, font=ui_font(9, "bold"))
    style.configure("TCheckbutton", background=SURFACE, foreground=INK)
    style.configure("TScale", background=SURFACE)


class Card(tk.Frame):
    """Карточка с тонкой рамкой и внутренним отступом."""

    def __init__(self, master, **kwargs) -> None:
        super().__init__(master, background=SURFACE, highlightbackground=BORDER, highlightthickness=1, **kwargs)
        self.body = tk.Frame(self, background=SURFACE)
        self.body.pack(fill="both", expand=True, padx=14, pady=12)


def section_title(master, text: str, subtitle: str = "") -> tk.Frame:
    frame = tk.Frame(master, background=SURFACE)
    tk.Label(frame, text=text, background=SURFACE, foreground=INK, font=ui_font(12, "bold"), anchor="w").pack(anchor="w")
    if subtitle:
        tk.Label(
            frame, text=subtitle, background=SURFACE, foreground=MUTED, font=ui_font(8), anchor="w"
        ).pack(anchor="w", pady=(2, 0))
    return frame
