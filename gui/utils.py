import tkinter as tk


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
