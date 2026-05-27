from __future__ import annotations

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .base import BaseTab
from ..settings import ENV_FIELDS, ENV_PATH, load_env_values, write_env_values


class SettingsTab(BaseTab):
    TAB_LABEL = "設定"

    def __init__(self, parent, app):
        self._vars: dict[str, tk.StringVar] = {}
        super().__init__(parent, app)

    def _build(self) -> None:
        ttk.Label(self, text=".env 設定", font=("", 14, "bold")).pack(anchor=tk.W)
        ttk.Label(
            self,
            text=f"儲存後會更新 {ENV_PATH}，之後從 GUI 啟動的剪輯都會使用這些設定。",
            font=("", 9),
            foreground="gray",
            wraplength=560,
        ).pack(anchor=tk.W, pady=(2, 10))

        form = ttk.Frame(self)
        form.pack(fill=tk.X)
        form.columnconfigure(1, weight=1)

        values = load_env_values()
        for row, (key, label, default) in enumerate(ENV_FIELDS):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky=tk.W, padx=(0, 8), pady=4)
            var = tk.StringVar(value=values.get(key, default))
            self._vars[key] = var

            if key == "AUTOCUT_BACKEND":
                widget = ttk.Combobox(
                    form,
                    textvariable=var,
                    values=["local-api", "local", "qwen-cloud", "gemini"],
                    state="readonly",
                    width=18,
                )
                widget.grid(row=row, column=1, sticky=tk.W, pady=4)
            elif key == "AUTOCUT_VERBOSE":
                widget = ttk.Combobox(
                    form,
                    textvariable=var,
                    values=["true", "false"],
                    state="readonly",
                    width=10,
                )
                widget.grid(row=row, column=1, sticky=tk.W, pady=4)
            elif key == "AUTOCUT_OPENING_CAPTION_FONT":
                line = ttk.Frame(form)
                line.grid(row=row, column=1, sticky=tk.EW, pady=4)
                line.columnconfigure(0, weight=1)
                ttk.Entry(line, textvariable=var).grid(row=0, column=0, sticky=tk.EW)
                ttk.Button(line, text="選擇…", command=self._browse_font).grid(row=0, column=1, padx=(6, 0))
            else:
                ttk.Entry(form, textvariable=var).grid(row=row, column=1, sticky=tk.EW, pady=4)
            ttk.Label(form, text=key, foreground="gray", font=("Menlo", 9)).grid(
                row=row, column=2, sticky=tk.W, padx=(8, 0), pady=4
            )

        actions = ttk.Frame(self)
        actions.pack(fill=tk.X, pady=(12, 0))
        ttk.Button(actions, text="重新載入 .env", command=self.load_state).pack(side=tk.LEFT)
        ttk.Button(actions, text="儲存設定", command=self._save).pack(side=tk.LEFT, padx=(8, 0))

        ttk.Label(
            self,
            text=(
                "小提醒：一般剪輯/一鍵腳本頁籤的『後端』下拉選單仍可覆蓋預設後端；"
                "這裡主要設定 API 位址、模型、字幕秒數與詳細日誌。"
            ),
            font=("", 9),
            foreground="gray",
            wraplength=560,
        ).pack(fill=tk.X, pady=(10, 0))

    def load_state(self) -> None:
        values = load_env_values()
        for key, var in self._vars.items():
            var.set(values.get(key, ""))

    def save_state(self) -> None:
        # Deliberately no auto-save on window close; users choose when to update .env.
        return

    def set_run_button_state(self, state: str) -> None:
        return

    def reset_run_button(self) -> None:
        return

    def _browse_font(self) -> None:
        f = filedialog.askopenfilename(
            title="選擇字幕字型檔",
            filetypes=[("字型檔", "*.ttf *.ttc *.otf"), ("所有檔案", "*.*")],
        )
        if f:
            self._vars["AUTOCUT_OPENING_CAPTION_FONT"].set(f)

    def _save(self) -> None:
        values = {key: var.get().strip() for key, var in self._vars.items()}
        if values.get("AUTOCUT_CAPTION_DURATION_SECONDS"):
            try:
                if float(values["AUTOCUT_CAPTION_DURATION_SECONDS"]) <= 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("錯誤", "字幕秒數必須是正數")
                return
        if values.get("AUTOCUT_SCRIPT_API_MAX_TOKENS"):
            try:
                if int(values["AUTOCUT_SCRIPT_API_MAX_TOKENS"]) <= 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("錯誤", "腳本 Max Tokens 必須是正整數，或留空")
                return

        try:
            write_env_values(values)
        except Exception as exc:
            messagebox.showerror("錯誤", f"儲存 .env 失敗：{exc}")
            return
        self.app.log(f"✓ 已更新 .env: {ENV_PATH}")
        messagebox.showinfo("完成", ".env 設定已儲存")
