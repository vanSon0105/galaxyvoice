from __future__ import annotations

from tkinter import ttk


def build_stories_workspace_editor(host, notebook: ttk.Notebook) -> None:
    host._build_editable_longform_tab(notebook, "stories")
