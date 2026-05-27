from __future__ import annotations

from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .base import BaseTab

_ROOT = Path(__file__).resolve().parent.parent.parent

_DEFAULT_PROMPT = (
    "請根據素材編一支精華短片，優先挑最精彩、有資訊量、有人物表情或故事推進的片段；"
    "長度可自行決定，寧可短而精準，不要為了湊長度加入普通片段"
)


class ScriptTab(BaseTab):
    TAB_LABEL = "腳本模式"
    IDLE_LABEL = "▶ 開始腳本剪輯"

    def __init__(self, parent, app):
        self.script_files: list[str] = []
        self.script_prompt = tk.StringVar(value=_DEFAULT_PROMPT)
        self.script_backend = tk.StringVar(value="local-api")
        self.script_verbose = tk.BooleanVar(value=False)
        self.script_opening_caption = tk.StringVar(value="")
        self.script_opening_caption_duration = tk.StringVar(value="3")
        self.script_output = tk.StringVar()
        super().__init__(parent, app)

    def _build(self) -> None:
        vl = ttk.Frame(self)
        vl.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(vl, text="素材影片", font=("", 11, "bold")).pack(anchor=tk.W)
        lrow = ttk.Frame(vl)
        lrow.pack(fill=tk.X, pady=(4, 0))
        self.script_listbox = tk.Listbox(lrow, height=4, font=("Menlo", 10))
        self.script_listbox.pack(side=tk.LEFT, fill=tk.X, expand=True)
        btn_frame = ttk.Frame(lrow)
        btn_frame.pack(side=tk.RIGHT, padx=(6, 0), fill=tk.Y)
        ttk.Button(btn_frame, text="新增影片…", command=self._add_files).pack(pady=(0, 4))
        ttk.Button(btn_frame, text="移除選取", command=self._remove_selected).pack()

        rp = ttk.Frame(self)
        rp.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(rp, text="腳本提示 (告訴 AI 你想編什麼故事)", font=("", 11, "bold")).pack(anchor=tk.W)
        self.script_prompt_entry = tk.Text(rp, height=3, wrap=tk.WORD, font=("", 11))
        self.script_prompt_entry.pack(fill=tk.X, pady=(4, 0))
        self.script_prompt_entry.insert("1.0", self.script_prompt.get())

        sopts = ttk.Frame(self)
        sopts.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(sopts, text="後端").grid(row=0, column=0, sticky=tk.W, padx=(0, 4))
        ttk.Combobox(sopts, textvariable=self.script_backend,
                     values=["local-api", "local", "qwen-cloud", "gemini"],
                     state="readonly", width=12).grid(row=0, column=1, sticky=tk.W, padx=(0, 20))
        ttk.Checkbutton(sopts, text="詳細日誌",
                        variable=self.script_verbose).grid(row=0, column=2, sticky=tk.W)

        cap = ttk.Frame(self)
        cap.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(cap, text="開場字幕（可選）", font=("", 11, "bold")).grid(row=0, column=0, sticky=tk.W)
        ttk.Label(cap, text="秒數").grid(row=0, column=1, sticky=tk.E, padx=(12, 4))
        ttk.Entry(cap, textvariable=self.script_opening_caption_duration,
                  width=6).grid(row=0, column=2, sticky=tk.W)
        ttk.Entry(cap, textvariable=self.script_opening_caption).grid(row=1, column=0, columnspan=3, sticky=tk.EW, pady=(4, 0))
        cap.columnconfigure(0, weight=1)

        ro = ttk.Frame(self)
        ro.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(ro, text="輸出檔案", font=("", 11, "bold")).pack(anchor=tk.W)
        sorow = ttk.Frame(ro)
        sorow.pack(fill=tk.X, pady=(4, 0))
        ttk.Entry(sorow, textvariable=self.script_output).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(sorow, text="另存新檔…", command=self._browse_output).pack(side=tk.RIGHT, padx=(6, 0))

        self._run_btn = ttk.Button(self, text=self.IDLE_LABEL, command=self._run)
        self._run_btn.pack(pady=(6, 0))

    def _add_files(self) -> None:
        files = filedialog.askopenfilenames(
            title="選擇素材影片",
            filetypes=[("影片", "*.mp4 *.mov *.lrv *.insv"), ("所有檔案", "*.*")]
        )
        for f in files:
            if f not in self.script_files:
                self.script_files.append(f)
                self.script_listbox.insert(tk.END, Path(f).name)
        if len(self.script_files) == 1:
            stem = Path(self.script_files[0]).stem
            self.script_output.set(str(Path.home() / "Movies" / f"{stem}_script.mp4"))

    def _remove_selected(self) -> None:
        sel = self.script_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        self.script_listbox.delete(idx)
        del self.script_files[idx]

    def _browse_output(self) -> None:
        f = filedialog.asksaveasfilename(
            title="輸出檔案位置",
            defaultextension=".mp4",
            filetypes=[("MP4 影片", "*.mp4"), ("所有檔案", "*.*")]
        )
        if f:
            self.script_output.set(f)

    def _run(self) -> None:
        if self.app.is_running:
            return
        if not self.script_files:
            messagebox.showerror("錯誤", "請至少加入一部素材影片")
            return

        prompt = self.script_prompt_entry.get("1.0", tk.END).strip()
        if not prompt:
            messagebox.showerror("錯誤", "請輸入腳本提示")
            return

        opening_caption = self.script_opening_caption.get().strip()
        opening_caption_duration = self.script_opening_caption_duration.get().strip()
        if opening_caption:
            try:
                if float(opening_caption_duration or "3") <= 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("錯誤", "開場字幕秒數必須是正數")
                return

        output = self.script_output.get().strip()
        if not output:
            output = str(Path.home() / "Movies" / "script_output.mp4")
            self.script_output.set(output)

        args = [
            str(_ROOT / ".venv" / "bin" / "python"),
            str(_ROOT / "autocut_script.py"), "create",
            *self.script_files,
            "--prompt", prompt,
            "--backend", self.script_backend.get(),
            "-o", output,
        ]
        if opening_caption:
            args.extend(["--opening-caption", opening_caption])
            args.extend(["--opening-caption-duration", opening_caption_duration or "3"])
        if self.script_verbose.get():
            args.append("--verbose")

        self.app.clear_log()
        self.app.log(f"▶ 開始腳本剪輯: {len(self.script_files)} 部素材")
        for sf in self.script_files:
            self.app.log(f"    {Path(sf).name}")
        self.app.log(f"  Prompt: {prompt}")
        self.app.log(f"  Backend: {self.script_backend.get()}")
        self.app.log(f"  Opening caption: {opening_caption or 'none'}")
        if opening_caption:
            self.app.log(f"  Opening caption duration: {opening_caption_duration or '3'}s")
        self.app.log(f"  Output: {output}")
        self.app.log("")

        self.app.run_job(
            args,
            status_text="腳本剪輯中…",
            success_msg="✓ 腳本剪輯完成！",
            active_button=self._run_btn,
        )
