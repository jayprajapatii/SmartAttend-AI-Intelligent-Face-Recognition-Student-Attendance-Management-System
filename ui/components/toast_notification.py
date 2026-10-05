"""
ui/components/toast_notification.py

Lightweight toast notification system: small floating messages that
appear in a corner of the app window and auto-dismiss after a delay.
Multiple toasts stack vertically; each has its own fade-out timer.

Setup (once, in app_window.py / SmartAttendApp.__init__):
    from ui.components.toast_notification import toast_manager
    toast_manager.attach(self)   # self = the root CTk window

Usage anywhere else in the app:
    from ui.components.toast_notification import toast_manager

    toast_manager.show("Attendance marked for Jay Prajapati.", kind="success")
    toast_manager.show("Camera disconnected.", kind="error")
    toast_manager.show("New system update available.", kind="info")
    toast_manager.show("Low attendance detected for 3 students.", kind="warning")
"""

import customtkinter as ctk

KIND_STYLES = {
    "success": {"bg": "#2ecc71", "icon": "✓"},
    "error":   {"bg": "#e74c3c", "icon": "✕"},
    "warning": {"bg": "#f39c12", "icon": "⚠"},
    "info":    {"bg": "#3b82f6", "icon": "ℹ"},
}

DEFAULT_DURATION_MS = 3500
TOAST_WIDTH = 320
TOAST_SPACING = 10
MARGIN_RIGHT = 20
MARGIN_BOTTOM = 20


class _Toast(ctk.CTkFrame):
    """A single toast bubble. Not used directly - created by ToastManager."""

    def __init__(self, master, message: str, kind: str, on_close):
        style = KIND_STYLES.get(kind, KIND_STYLES["info"])
        super().__init__(master, corner_radius=10, fg_color=style["bg"], width=TOAST_WIDTH)
        self.pack_propagate(False)
        self._on_close = on_close

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="both", expand=True, padx=14, pady=10)

        ctk.CTkLabel(
            row, text=style["icon"], text_color="white", font=ctk.CTkFont(size=15, weight="bold"),
        ).pack(side="left", padx=(0, 10))

        ctk.CTkLabel(
            row, text=message, text_color="white", font=ctk.CTkFont(size=12),
            wraplength=TOAST_WIDTH - 70, justify="left", anchor="w",
        ).pack(side="left", fill="x", expand=True)

        close_btn = ctk.CTkLabel(
            row, text="✕", text_color="white", font=ctk.CTkFont(size=11), cursor="hand2",
        )
        close_btn.pack(side="right")
        close_btn.bind("<Button-1>", lambda _e: self._on_close(self))


class ToastManager:
    """
    Singleton that manages a stack of toast notifications anchored to
    the bottom-right corner of the attached root window.
    """

    def __init__(self):
        self._root = None
        self._active_toasts = []

    def attach(self, root_window):
        """Call once at app startup with the root CTk window/Toplevel."""
        self._root = root_window

    def show(self, message: str, kind: str = "info", duration_ms: int = DEFAULT_DURATION_MS):
        """
        Show a toast. kind: 'success' | 'error' | 'warning' | 'info'
        Safe to call from any thread's scheduled `.after(0, ...)` callback,
        but must itself run on the main thread (Tkinter requirement).
        """
        if self._root is None:
            # No root attached yet (e.g. called before app_window finished
            # initializing) - fail silently rather than crash the caller.
            return

        toast = _Toast(self._root, message, kind, on_close=self._dismiss)
        self._active_toasts.append(toast)
        self._reposition()

        if duration_ms:
            self._root.after(duration_ms, lambda: self._dismiss(toast))

    def _dismiss(self, toast: "_Toast"):
        if toast not in self._active_toasts:
            return
        self._active_toasts.remove(toast)
        toast.place_forget()
        toast.destroy()
        self._reposition()

    def _reposition(self):
        """Stack toasts bottom-up in the bottom-right corner."""
        y_offset = MARGIN_BOTTOM
        for toast in reversed(self._active_toasts):
            toast.update_idletasks()
            height = toast.winfo_reqheight() or 50
            toast.place(
                relx=1.0, rely=1.0,
                x=-MARGIN_RIGHT, y=-y_offset,
                anchor="se",
            )
            y_offset += height + TOAST_SPACING

    def clear_all(self):
        for toast in list(self._active_toasts):
            self._dismiss(toast)


# Singleton instance - import this everywhere instead of instantiating directly
toast_manager = ToastManager()