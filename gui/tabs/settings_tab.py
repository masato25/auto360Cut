from __future__ import annotations

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

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

        quick = ttk.LabelFrame(self, text="快速套用")
        quick.pack(fill=tk.X, pady=(0, 10))
        ttk.Button(quick, text="llama.cpp/local-api + 自架 LLM", command=self._apply_local_self_hosted).pack(side=tk.LEFT, padx=(8, 4), pady=8)
        ttk.Button(quick, text="Gemini VLM + DeepSeek LLM", command=self._apply_gemini_deepseek).pack(side=tk.LEFT, padx=4, pady=8)
        ttk.Button(quick, text="只套用自架 LLM 腳本設定", command=self._apply_self_hosted_script).pack(side=tk.LEFT, padx=4, pady=8)
        ttk.Button(quick, text="只套用 DeepSeek 腳本設定", command=self._apply_deepseek_script).pack(side=tk.LEFT, padx=4, pady=8)

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
            elif key in {"AUTOCUT_SCRIPT_API_KEY", "GEMINI_API_KEY"}:
                ttk.Entry(form, textvariable=var, show="•").grid(row=row, column=1, sticky=tk.EW, pady=4)
            elif key in {"AUTOCUT_OPENING_CAPTION_FONT", "AUTOCUT_MUSIC_DIR"}:
                line = ttk.Frame(form)
                line.grid(row=row, column=1, sticky=tk.EW, pady=4)
                line.columnconfigure(0, weight=1)
                ttk.Entry(line, textvariable=var).grid(row=0, column=0, sticky=tk.EW)
                browse = self._browse_font if key == "AUTOCUT_OPENING_CAPTION_FONT" else self._browse_music_dir
                ttk.Button(line, text="選擇…", command=browse).grid(row=0, column=1, padx=(6, 0))
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
                "小提醒：AUTOCUT_BACKEND=local-api 時使用 LOCAL_API_BASE/MODEL 做本地 VLM/embedding；設為 gemini 時使用 GEMINI_API_KEY。"
                "腳本生成固定看 AUTOCUT_SCRIPT_API_*：local-api 模式可填你自架的 OpenAI-compatible LLM，"
                "Gemini VLM 模式則可用 DeepSeek（https://api.deepseek.com/v1 + deepseek-chat）。一般剪輯與索引頁籤仍可用下拉選單臨時覆蓋後端。"
            ),
            font=("", 9),
            foreground="gray",
            wraplength=620,
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

    def _set_if_empty(self, key: str, value: str) -> None:
        if key in self._vars and not self._vars[key].get().strip():
            self._vars[key].set(value)

    def _apply_self_hosted_script(self) -> None:
        self._vars["AUTOCUT_SCRIPT_API_BASE"].set("http://0.0.0.0:8080/v1")
        self._vars["AUTOCUT_SCRIPT_API_MODEL"].set("your-openai-compatible-llm")
        if self._vars["AUTOCUT_SCRIPT_API_KEY"].get().strip() in {"", "your-deepseek-api-key", "your-api-key"}:
            self._vars["AUTOCUT_SCRIPT_API_KEY"].set("not-needed")

    def _apply_deepseek_script(self) -> None:
        self._vars["AUTOCUT_SCRIPT_API_BASE"].set("https://api.deepseek.com/v1")
        self._vars["AUTOCUT_SCRIPT_API_MODEL"].set("deepseek-chat")
        if self._vars["AUTOCUT_SCRIPT_API_KEY"].get().strip() in {"", "not-needed", "your-api-key"}:
            self._vars["AUTOCUT_SCRIPT_API_KEY"].set("your-deepseek-api-key")

    def _apply_local_self_hosted(self) -> None:
        self._vars["AUTOCUT_BACKEND"].set("local-api")
        self._set_if_empty("LOCAL_API_BASE", "http://0.0.0.0:8080")
        self._apply_self_hosted_script()

    def _apply_gemini_deepseek(self) -> None:
        self._vars["AUTOCUT_BACKEND"].set("gemini")
        self._set_if_empty("GEMINI_API_KEY", "your-gemini-api-key")
        self._apply_deepseek_script()

    def _browse_font(self) -> None:
        f = filedialog.askopenfilename(
            title="選擇字幕字型檔",
            filetypes=[("字型檔", "*.ttf *.ttc *.otf"), ("所有檔案", "*.*")],
        )
        if f:
            self._vars["AUTOCUT_OPENING_CAPTION_FONT"].set(f)

    def _browse_music_dir(self) -> None:
        d = filedialog.askdirectory(title="選擇背景音樂資料夾")
        if d:
            self._vars["AUTOCUT_MUSIC_DIR"].set(d)

    def _save(self) -> None:
        values = {key: var.get().strip() for key, var in self._vars.items()}
        if values.get("AUTOCUT_CAPTION_DURATION_SECONDS"):
            try:
                if float(values["AUTOCUT_CAPTION_DURATION_SECONDS"]) <= 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("錯誤", "字幕秒數必須是正數")
                return
        if values.get("AUTOCUT_BAND_BOX_COLOR") and not values["AUTOCUT_BAND_BOX_COLOR"].strip():
            messagebox.showerror("錯誤", "Band 背景色不可只填空白；可留空使用預設 black@1.0")
            return
        if values.get("AUTOCUT_BACKEND") == "gemini" and values.get("GEMINI_API_KEY") in {"", "your-gemini-api-key"}:
            messagebox.showerror("錯誤", "使用 Gemini 後端時請填入 GEMINI_API_KEY")
            return
        if values.get("AUTOCUT_SCRIPT_API_KEY") in {"your-deepseek-api-key", "your-api-key"}:
            messagebox.showerror("錯誤", "請將腳本 API Key 換成實際金鑰，或留空給本機 API 使用")
            return
        if values.get("AUTOCUT_SCRIPT_API_MAX_TOKENS"):
            try:
                if int(values["AUTOCUT_SCRIPT_API_MAX_TOKENS"]) <= 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("錯誤", "腳本 Max Tokens 必須是正整數，或留空")
                return
        if values.get("AUTOCUT_MUSIC_VOLUME"):
            try:
                if float(values["AUTOCUT_MUSIC_VOLUME"]) < 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("錯誤", "背景音樂音量必須是 0 或正數")
                return
        if values.get("AUTOCUT_MUSIC_DIR") and not Path(values["AUTOCUT_MUSIC_DIR"]).expanduser().is_dir():
            messagebox.showerror("錯誤", "音樂資料夾不存在")
            return

        try:
            write_env_values(values)
        except Exception as exc:
            messagebox.showerror("錯誤", f"儲存 .env 失敗：{exc}")
            return
        self.app.log(f"✓ 已更新 .env: {ENV_PATH}")
        messagebox.showinfo("完成", ".env 設定已儲存")
