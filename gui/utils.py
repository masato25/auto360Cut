import os
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox


def open_file_with_default_app(path: str) -> None:
    """Open a file with the OS default application."""
    if sys.platform == "darwin":
        subprocess.Popen(["open", path])
    elif os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", path])


def play_selected_listbox_video(listbox: tk.Listbox, files: list[str]) -> None:
    sel = listbox.curselection()
    if not sel:
        messagebox.showwarning("提示", "請先選取要播放的素材影片")
        return

    idx = sel[0]
    if idx < 0 or idx >= len(files):
        messagebox.showerror("錯誤", "清單資料不同步，請切換頁籤後重試")
        return

    path = files[idx]
    if not os.path.isfile(path):
        messagebox.showerror("錯誤", f"找不到影片檔案：\n{path}")
        return

    open_file_with_default_app(path)


def bind_listbox_double_click_to_play(listbox: tk.Listbox, files: list[str]) -> None:
    def _play(_event=None):
        play_selected_listbox_video(listbox, files)
        return "break"

    listbox.bind("<Double-Button-1>", _play)
    listbox.bind("<Return>", _play)


def bind_readonly_text_shortcuts(text_widget: tk.Text) -> None:
    def _select_all(_event=None):
        text_widget.tag_add(tk.SEL, "1.0", tk.END)
        text_widget.mark_set(tk.INSERT, "1.0")
        text_widget.see(tk.INSERT)
        return "break"

    def _copy(_event=None):
        try:
            selected = text_widget.get(tk.SEL_FIRST, tk.SEL_LAST)
        except tk.TclError:
            return "break"
        text_widget.clipboard_clear()
        text_widget.clipboard_append(selected)
        return "break"

    for sequence in ("<Control-a>", "<Control-A>", "<Command-a>", "<Command-A>"):
        text_widget.bind(sequence, _select_all)
    for sequence in ("<Control-c>", "<Control-C>", "<Command-c>", "<Command-C>"):
        text_widget.bind(sequence, _copy)
