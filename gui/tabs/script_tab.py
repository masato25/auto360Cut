from __future__ import annotations

from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .base import BaseTab
from ..settings import is_verbose_enabled
from ..utils import bind_listbox_double_click_to_play, play_selected_listbox_video

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
        self.script_opening_caption = tk.StringVar(value="")
        self.script_closing_caption = tk.StringVar(value="")
        self.script_auto_music = tk.BooleanVar(value=False)
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
        bind_listbox_double_click_to_play(self.script_listbox, self.script_files)
        btn_frame = ttk.Frame(lrow)
        btn_frame.pack(side=tk.RIGHT, padx=(6, 0), fill=tk.Y)
        ttk.Button(btn_frame, text="新增影片…", command=self._add_files).pack(pady=(0, 4))
        ttk.Button(btn_frame, text="播放選取", command=self._play_selected).pack(pady=(0, 4))
        ttk.Button(btn_frame, text="移除選取", command=self._remove_selected).pack(pady=(0, 4))
        ttk.Button(btn_frame, text="清空", command=self._clear_files).pack()

        rp = ttk.Frame(self)
        rp.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(rp, text="腳本提示 (告訴 AI 你想編什麼故事)", font=("", 11, "bold")).pack(anchor=tk.W)
        self.script_prompt_entry = tk.Text(rp, height=3, wrap=tk.WORD, font=("", 11))
        self.script_prompt_entry.pack(fill=tk.X, pady=(4, 0))
        self.script_prompt_entry.insert("1.0", self.script_prompt.get())

        cap = ttk.Frame(self)
        cap.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(cap, text="開場字幕（可選）", font=("", 11, "bold")).grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(cap, textvariable=self.script_opening_caption).grid(row=1, column=0, sticky=tk.EW, pady=(4, 0))
        cap.columnconfigure(0, weight=1)

        ccap = ttk.Frame(self)
        ccap.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(ccap, text="閉場字幕（可選）", font=("", 11, "bold")).grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(ccap, textvariable=self.script_closing_caption).grid(row=1, column=0, sticky=tk.EW, pady=(4, 0))
        ccap.columnconfigure(0, weight=1)

        music = ttk.Frame(self)
        music.pack(fill=tk.X, pady=(0, 6))
        ttk.Checkbutton(
            music,
            text="自動選擇背景音樂（從設定的音樂資料夾）",
            variable=self.script_auto_music,
        ).pack(anchor=tk.W)
        ttk.Label(
            music,
            text="音樂資料夾與音量可在「設定」頁籤調整；未設定或找不到音樂時會略過。",
            font=("", 9), foreground="gray", wraplength=520,
        ).pack(anchor=tk.W, pady=(2, 0))

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

    def _play_selected(self) -> None:
        play_selected_listbox_video(self.script_listbox, self.script_files)

    def _remove_selected(self) -> None:
        sel = self.script_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        self.script_listbox.delete(idx)
        del self.script_files[idx]

    def _clear_files(self) -> None:
        self.script_files.clear()
        self.script_listbox.delete(0, tk.END)

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
        closing_caption = self.script_closing_caption.get().strip()

        output = self.script_output.get().strip()
        if not output:
            output = str(Path.home() / "Movies" / "script_output.mp4")
            self.script_output.set(output)

        args = [
            str(_ROOT / ".venv" / "bin" / "python"),
            str(_ROOT / "autocut_script.py"), "create",
            *self.script_files,
            "--prompt", prompt,
            "-o", output,
        ]
        if opening_caption:
            args.extend(["--opening-caption", opening_caption])
        if closing_caption:
            args.extend(["--closing-caption", closing_caption])
        if self.script_auto_music.get():
            args.append("--auto-music")
        verbose_enabled = is_verbose_enabled()
        if verbose_enabled:
            args.append("--verbose")

        self.app.clear_log()
        self.app.log(f"▶ 開始腳本剪輯: {len(self.script_files)} 部素材")
        for sf in self.script_files:
            self.app.log(f"    {Path(sf).name}")
        self.app.log(f"  Prompt: {prompt}")
        self.app.log("  Backend: from .env AUTOCUT_BACKEND")
        self.app.log(f"  Opening caption: {opening_caption or 'none'}")
        self.app.log(f"  Closing caption: {closing_caption or 'none'}")
        self.app.log("  Band: from .env AUTOCUT_BAND_TEXT")
        self.app.log(f"  Auto music: {'yes' if self.script_auto_music.get() else 'no'}")
        if opening_caption or closing_caption:
            self.app.log("  Caption duration: from .env AUTOCUT_CAPTION_DURATION_SECONDS (default 3s)")
        self.app.log(f"  Output: {output}")
        self.app.log("")

        self.app.run_job(
            args,
            status_text="腳本剪輯中…",
            success_msg="✓ 腳本剪輯完成！",
            active_button=self._run_btn,
        )
