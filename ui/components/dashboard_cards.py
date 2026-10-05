"""
ui/components/dashboard_cards.py

Reusable card widgets for dashboards and summary panels:
    - StatCard: title + big value + optional subtitle/trend/icon
    - IconStatCard: StatCard variant with an icon from assets/icons
    - MiniStatRow: compact horizontal grid of StatCards (auto-columns)

Used by dashboard_page.py, attendance_dashboard_page.py, and
analytics_page.py so every metric card in the app looks consistent.
"""

import customtkinter as ctk


class StatCard(ctk.CTkFrame):
    """
    A single metric card: small gray title, large bold value, optional
    subtitle, and an optional trend indicator (e.g. "+4.2%" in green/red).

    Usage:
        card = StatCard(parent, title="Present Today", value="128",
                         subtitle="of 150 students", accent="#2ecc71")
        card.pack(...)  # or .grid(...)

        # Update later without rebuilding:
        card.set_value("130")
        card.set_trend("+2 since yesterday", positive=True)
    """

    def __init__(
        self,
        master,
        title: str,
        value: str,
        subtitle: str = "",
        accent: str = None,
        trend_text: str = "",
        trend_positive: bool = True,
        on_click=None,
        **kwargs,
    ):
        super().__init__(master, corner_radius=14, border_width=1, border_color=("#E2E8F0", "#334155"), **kwargs)

        if on_click:
            self.configure(cursor="hand2")
            self.bind("<Button-1>", lambda _e: on_click())

        self.title_label = ctk.CTkLabel(
            self, text=title, font=ctk.CTkFont(size=12), text_color=("#64748B", "#94A3B8"), anchor="w"
        )
        self.title_label.pack(anchor="w", padx=18, pady=(16, 2), fill="x")

        self.value_label = ctk.CTkLabel(
            self, text=value, font=ctk.CTkFont(size=28, weight="bold"),
            text_color=accent, anchor="w",
        )
        self.value_label.pack(anchor="w", padx=18, fill="x")

        self.subtitle_label = ctk.CTkLabel(
            self, text=subtitle, font=ctk.CTkFont(size=11), text_color=("#64748B", "#94A3B8"), anchor="w"
        )
        if subtitle:
            self.subtitle_label.pack(anchor="w", padx=18, pady=(2, 0), fill="x")

        self.trend_label = ctk.CTkLabel(
            self, text="", font=ctk.CTkFont(size=11, weight="bold"), anchor="w"
        )
        if trend_text:
            self.set_trend(trend_text, trend_positive)
            self.trend_label.pack(anchor="w", padx=18, pady=(2, 0), fill="x")

        # Bottom spacer so cards have consistent padding regardless of
        # whether subtitle/trend are present.
        ctk.CTkLabel(self, text="", height=1).pack(pady=(0, 12))

        if on_click:
            for widget in (self.title_label, self.value_label, self.subtitle_label, self.trend_label):
                widget.bind("<Button-1>", lambda _e: on_click())

    def set_value(self, value: str):
        self.value_label.configure(text=value)

    def set_subtitle(self, subtitle: str):
        if subtitle and not self.subtitle_label.winfo_ismapped():
            self.subtitle_label.pack(anchor="w", padx=18, pady=(2, 0), fill="x")
        self.subtitle_label.configure(text=subtitle)

    def set_trend(self, text: str, positive: bool = True):
        color = "#2ecc71" if positive else "#e74c3c"
        arrow = "▲" if positive else "▼"
        self.trend_label.configure(text=f"{arrow} {text}", text_color=color)
        if not self.trend_label.winfo_ismapped():
            self.trend_label.pack(anchor="w", padx=18, pady=(2, 0), fill="x")


class IconStatCard(StatCard):
    """
    StatCard variant with a small icon (from utils.asset_manager)
    displayed next to the title.

    Usage:
        IconStatCard(parent, title="Total Students", value="342",
                     icon_filename="students.png")
    """

    def __init__(self, master, title: str, value: str, icon_filename: str = None, **kwargs):
        super().__init__(master, title=title, value=value, **kwargs)

        if icon_filename:
            try:
                from utils.asset_manager import assets
                icon_image = assets.get_icon(icon_filename, size=(18, 18))
                icon_label = ctk.CTkLabel(self, image=icon_image, text="")
                icon_label.place(relx=1.0, rely=0.0, anchor="ne", x=-14, y=14)
            except Exception:
                pass  # icon is decorative - fail silently if assets aren't available


class MiniStatRow(ctk.CTkFrame):
    """
    A horizontal row of StatCards that auto-distributes evenly across
    columns. Useful for compact secondary metric rows.

    Usage:
        row = MiniStatRow(parent, cards=[
            {"title": "Departments", "value": "6"},
            {"title": "Courses", "value": "18"},
            {"title": "DB Status", "value": "Connected", "accent": "#2ecc71"},
        ])
        row.pack(fill="x")
    """

    def __init__(self, master, cards: list, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)

        for i in range(len(cards)):
            self.grid_columnconfigure(i, weight=1, uniform="ministat")

        self.cards = []
        for i, card_kwargs in enumerate(cards):
            card = StatCard(self, **card_kwargs)
            card.grid(row=0, column=i, sticky="nsew", padx=6)
            self.cards.append(card)

    def get_card(self, index: int) -> StatCard:
        return self.cards[index]