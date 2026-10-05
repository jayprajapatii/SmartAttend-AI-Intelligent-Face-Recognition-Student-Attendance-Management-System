"""
ui/components/data_table.py

Reusable searchable, sortable data table built on ttk.Treeview,
matching the app's CTk look via a shared style. Centralizes the
Treeview boilerplate that student_registration_page.py,
faculty_management_page.py, attendance_dashboard_page.py, and
reports_page.py currently each hand-roll individually.

Usage:
    from ui.components.data_table import DataTable

    table = DataTable(
        parent,
        columns=[
            {"key": "roll_number", "header": "Roll No.", "width": 90},
            {"key": "full_name", "header": "Name", "width": 180},
            {"key": "department", "header": "Department", "width": 140},
        ],
        on_row_select=lambda row: print("Selected:", row),
        searchable=True,
        search_keys=["roll_number", "full_name"],  # None = search all columns
    )
    table.pack(fill="both", expand=True)

    table.set_data([
        {"roll_number": "101", "full_name": "Jay Prajapati", "department": "CS"},
        {"roll_number": "102", "full_name": "Aditi Shah", "department": "IT"},
    ])

    table.get_selected_row()   # -> dict or None
    table.clear_selection()
    table.refresh_row(row_id, updated_dict)
"""

import customtkinter as ctk
from tkinter import ttk

_STYLE_INITIALIZED = False


def _ensure_style():
    """Configure the ttk Treeview style once per process."""
    global _STYLE_INITIALIZED
    if _STYLE_INITIALIZED:
        return
    style = ttk.Style()
    style.theme_use("default")
    style.configure("SmartAttend.Treeview", rowheight=34, font=("Segoe UI", 10), background="#FFFFFF", foreground="#0F172A", fieldbackground="#FFFFFF", borderwidth=0)
    style.configure("SmartAttend.Treeview.Heading", font=("Segoe UI", 10, "bold"), background="#F1F5F9", foreground="#334155", relief="flat", padding=(8, 8))
    style.map("SmartAttend.Treeview", background=[("selected", "#2563EB")], foreground=[("selected", "#FFFFFF")])
    _STYLE_INITIALIZED = True


class DataTable(ctk.CTkFrame):
    """
    A CTkFrame wrapping a ttk.Treeview with optional built-in search,
    sortable column headers, and row-selection callbacks. Keeps the
    full source row dict alongside each Treeview item so callers get
    back real data, not just display strings.
    """

    def __init__(
        self,
        master,
        columns: list,
        on_row_select=None,
        on_row_double_click=None,
        searchable: bool = False,
        search_keys: list = None,
        search_placeholder: str = "Search...",
        height: int = None,
        **kwargs,
    ):
        """
        columns: list of dicts, each with:
            "key"    - dict key in each row (required)
            "header" - column header text (required)
            "width"  - pixel width (optional, default 120)
            "anchor" - "w" | "center" | "e" (optional, default "w")
        """
        super().__init__(master, fg_color="transparent", **kwargs)
        _ensure_style()

        self._columns = columns
        self._on_row_select = on_row_select
        self._on_row_double_click = on_row_double_click
        self._search_keys = search_keys or [c["key"] for c in columns]
        self._all_rows = []          # full unfiltered dataset (list of dicts)
        self._row_by_iid = {}        # tree iid -> source row dict
        self._sort_state = {}        # column key -> ascending bool

        if searchable:
            self._build_search_bar(search_placeholder)

        self._build_tree(height)

    # ------------------------------------------------------------
    # Search bar
    # ------------------------------------------------------------
    def _build_search_bar(self, placeholder: str):
        search_row = ctk.CTkFrame(self, fg_color="transparent")
        search_row.pack(fill="x", pady=(0, 8))

        self.search_entry = ctk.CTkEntry(search_row, placeholder_text=placeholder, height=40, corner_radius=10, border_width=1, border_color=("#E2E8F0", "#334155"))
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.search_entry.bind("<KeyRelease>", lambda _e: self._apply_search())

        ctk.CTkButton(
            search_row, text="Clear", width=70, fg_color="transparent", border_width=1,
            command=self._clear_search,
        ).pack(side="left")

    def _apply_search(self):
        keyword = self.search_entry.get().strip().lower()
        if not keyword:
            self._render_rows(self._all_rows)
            return

        filtered = [
            row for row in self._all_rows
            if any(keyword in str(row.get(k, "")).lower() for k in self._search_keys)
        ]
        self._render_rows(filtered)

    def _clear_search(self):
        self.search_entry.delete(0, "end")
        self._render_rows(self._all_rows)

    # ------------------------------------------------------------
    # Tree construction
    # ------------------------------------------------------------
    def _build_tree(self, height):
        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(fill="both", expand=True)

        col_keys = [c["key"] for c in self._columns]
        tree_kwargs = {"columns": col_keys, "show": "headings", "selectmode": "browse",
                        "style": "SmartAttend.Treeview"}
        if height:
            tree_kwargs["height"] = height

        self.tree = ttk.Treeview(container, **tree_kwargs)

        for col in self._columns:
            key = col["key"]
            self.tree.heading(key, text=col["header"], command=lambda k=key: self._sort_by(k))
            self.tree.column(key, width=col.get("width", 120), anchor=col.get("anchor", "w"))

        vsb = ttk.Scrollbar(container, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.tree.bind("<<TreeviewSelect>>", self._handle_select)
        if self._on_row_double_click:
            self.tree.bind("<Double-1>", self._handle_double_click)

        self.count_label = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=11), text_color="gray")
        self.count_label.pack(anchor="w", pady=(6, 0))

    # ------------------------------------------------------------
    # Sorting
    # ------------------------------------------------------------
    def _sort_by(self, key: str):
        ascending = self._sort_state.get(key, True)
        try:
            self._all_rows.sort(key=lambda r: (r.get(key) is None, r.get(key)), reverse=not ascending)
        except TypeError:
            self._all_rows.sort(key=lambda r: str(r.get(key, "")), reverse=not ascending)
        self._sort_state[key] = not ascending
        self._render_rows(self._all_rows)

    # ------------------------------------------------------------
    # Data in / out
    # ------------------------------------------------------------
    def set_data(self, rows: list, id_key: str = None):
        """
        rows: list of dicts. If id_key is given, that field's value is
        used as the Treeview item id (must be unique) - useful for
        get_selected_row() round-tripping with e.g. student_id.
        """
        self._id_key = id_key
        self._all_rows = list(rows)
        self._render_rows(self._all_rows)

    def _render_rows(self, rows: list):
        self.tree.delete(*self.tree.get_children())
        self._row_by_iid = {}

        for row in rows:
            values = [row.get(c["key"], "") if row.get(c["key"]) is not None else "-" for c in self._columns]
            iid = str(row[self._id_key]) if getattr(self, "_id_key", None) else None
            item_id = self.tree.insert("", "end", iid=iid, values=values)
            self._row_by_iid[item_id] = row

        self.count_label.configure(text=f"{len(rows)} row(s)")

    def get_selected_row(self) -> dict | None:
        selection = self.tree.selection()
        if not selection:
            return None
        return self._row_by_iid.get(selection[0])

    def clear_selection(self):
        for item in self.tree.selection():
            self.tree.selection_remove(item)

    def refresh_row(self, row_id, updated_row: dict):
        """Update a single row's displayed values in place (by id_key value)."""
        iid = str(row_id)
        if iid not in self._row_by_iid:
            return
        self._row_by_iid[iid] = updated_row
        values = [updated_row.get(c["key"], "") if updated_row.get(c["key"]) is not None else "-" for c in self._columns]
        self.tree.item(iid, values=values)

    def get_all_rows(self) -> list:
        return list(self._all_rows)

    # ------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------
    def _handle_select(self, _event):
        if self._on_row_select:
            row = self.get_selected_row()
            if row is not None:
                self._on_row_select(row)

    def _handle_double_click(self, _event):
        if self._on_row_double_click:
            row = self.get_selected_row()
            if row is not None:
                self._on_row_double_click(row)