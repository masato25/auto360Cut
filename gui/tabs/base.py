from __future__ import annotations

from tkinter import ttk


class BaseTab(ttk.Frame):
    TAB_LABEL = ""
    IDLE_LABEL = "▶ Run"

    def __init__(self, parent, app):
        super().__init__(parent, padding=12)
        self.app = app
        self._run_btn: ttk.Button | None = None
        self._build()

    def _build(self) -> None:
        raise NotImplementedError

    def set_run_button_state(self, state: str) -> None:
        if self._run_btn:
            self._run_btn.configure(state=state)

    def reset_run_button(self) -> None:
        if self._run_btn:
            self._run_btn.configure(text=self.IDLE_LABEL)
