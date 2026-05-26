from __future__ import annotations

import os
import subprocess
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .base import BaseTab

_ROOT = Path(__file__).resolve().parent.parent.parent

_DEFAULT_PROMPT = (
    "Prefer the viewport with a clearly visible main person, face, or full body. "
    "Avoid empty scenery, corridors, walls, or signs. "
    "Only if no clear person is visible, choose the most impressive or scenic foreground view."
)


class NormalTab(BaseTab):
    TAB_LABEL = "一般剪輯"
    IDLE_LABEL = "▶ 開始剪輯"

    def __init__(self, parent, app):
        self.video_path = tk.StringVar()
        self.prompt = tk.StringVar(value=_DEFAULT_PROMPT)
        self.count = tk.IntVar(value=3)
        self.backend = tk.StringVar(value="local-api")
        self.is_360 = tk.BooleanVar(value=False)
        self.output_path = tk.StringVar()
        self.face_path = tk.StringVar()
        self.verbose = tk.BooleanVar(value=False)
        self.force_reindex = tk.BooleanVar(value=False)
        self.view_angle = tk.StringVar(value="auto")
        super().__init__(parent, app)

    def _build(self) -> None:
        row0 = ttk.Frame(self)
        row0.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(row0, text="影片檔案", font=("", 11, "bold")).pack(anchor=tk.W)
        frow = ttk.Frame(row0)
        frow.pack(fill=tk.X, pady=(4, 0))
        ttk.Entry(frow, textvariable=self.video_path).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(frow, text="播放", command=self._play_video).pack(side=tk.RIGHT, padx=(2, 0))
        ttk.Button(frow, text="瀏覽…", command=self._browse_file).pack(side=tk.RIGHT, padx=(6, 0))

        row1 = ttk.Frame(self)
        row1.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(row1, text="搜尋提示 (Prompt)", font=("", 11, "bold")).pack(anchor=tk.W)
        self.prompt_entry = tk.Text(row1, height=3, wrap=tk.WORD, font=("", 11))
        self.prompt_entry.pack(fill=tk.X, pady=(4, 0))
        self.prompt_entry.insert("1.0", self.prompt.get())

        opts = ttk.Frame(self)
        opts.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(opts, text="剪輯數量").grid(row=0, column=0, sticky=tk.W, padx=(0, 4))
        ttk.Spinbox(opts, from_=1, to=20, textvariable=self.count,
                    width=4).grid(row=0, column=1, sticky=tk.W, padx=(0, 20))
        ttk.Label(opts, text="後端").grid(row=0, column=2, sticky=tk.W, padx=(0, 4))
        ttk.Combobox(opts, textvariable=self.backend,
                     values=["local-api", "local", "qwen-cloud", "gemini"],
                     state="readonly", width=12).grid(row=0, column=3, sticky=tk.W, padx=(0, 20))
        ttk.Checkbutton(opts, text="360 模式",
                        variable=self.is_360).grid(row=0, column=4, sticky=tk.W)
        ttk.Checkbutton(opts, text="詳細日誌",
                        variable=self.verbose).grid(row=0, column=5, sticky=tk.W, padx=(10, 0))
        ttk.Label(opts, text="360 角度").grid(row=1, column=0, sticky=tk.W, padx=(0, 4))
        ttk.Combobox(opts, textvariable=self.view_angle,
                     values=["auto", "front", "right", "back", "left"],
                     state="readonly", width=8).grid(row=1, column=1, sticky=tk.W, padx=(0, 20))
        ttk.Checkbutton(opts, text="強制重建索引",
                        variable=self.force_reindex).grid(row=1, column=2, columnspan=3,
                                                          sticky=tk.W, pady=(6, 0))

        row2 = ttk.Frame(self)
        row2.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(row2, text="參考臉部照片 (選填)", font=("", 11, "bold")).pack(anchor=tk.W)
        frow2 = ttk.Frame(row2)
        frow2.pack(fill=tk.X, pady=(4, 0))
        ttk.Entry(frow2, textvariable=self.face_path).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(frow2, text="選擇…", command=self._browse_face).pack(side=tk.RIGHT, padx=(6, 0))

        row3 = ttk.Frame(self)
        row3.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(row3, text="輸出檔案", font=("", 11, "bold")).pack(anchor=tk.W)
        orow = ttk.Frame(row3)
        orow.pack(fill=tk.X, pady=(4, 0))
        ttk.Entry(orow, textvariable=self.output_path).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(orow, text="另存新檔…", command=self._browse_output).pack(side=tk.RIGHT, padx=(6, 0))

        self._run_btn = ttk.Button(self, text=self.IDLE_LABEL, command=self._run)
        self._run_btn.pack(pady=(6, 0))

    def _play_video(self) -> None:
        path = self.video_path.get().strip()
        if not path or not os.path.isfile(path):
            messagebox.showwarning("提示", "請先選擇影片檔案")
            return
        subprocess.Popen(["open", path])

    def _browse_file(self) -> None:
        f = filedialog.askopenfilename(
            title="選擇影片檔案",
            filetypes=[("影片", "*.mp4 *.mov *.lrv *.insv"), ("所有檔案", "*.*")]
        )
        if f:
            self._set_video(f)

    def _browse_face(self) -> None:
        f = filedialog.askopenfilename(
            title="選擇參考臉部照片",
            filetypes=[("圖片", "*.jpg *.jpeg *.png *.webp"), ("所有檔案", "*.*")]
        )
        if f:
            self.face_path.set(f)

    def _browse_output(self) -> None:
        f = filedialog.asksaveasfilename(
            title="輸出檔案位置",
            defaultextension=".mp4",
            filetypes=[("MP4 影片", "*.mp4"), ("所有檔案", "*.*")]
        )
        if f:
            self.output_path.set(f)

    def _set_video(self, path: str) -> None:
        self.video_path.set(path)
        stem = Path(path).stem
        self.output_path.set(str(Path.home() / "Movies" / f"{stem}_autocut.mp4"))

    def _run(self) -> None:
        if self.app.is_running:
            return
        video = self.video_path.get().strip()
        if not video or not os.path.isfile(video):
            messagebox.showerror("錯誤", "請選擇有效的影片檔案")
            return

        prompt = self.prompt_entry.get("1.0", tk.END).strip()
        if not prompt:
            messagebox.showerror("錯誤", "請輸入搜尋提示")
            return

        output = self.output_path.get().strip()
        if not output:
            output = str(Path.home() / "Movies" / "autocut_output.mp4")
            self.output_path.set(output)

        args = [
            str(_ROOT / ".venv" / "bin" / "python"),
            str(_ROOT / "autocut.py"), "autocut", video,
            "--prompt", prompt,
            "--count", str(self.count.get()),
            "--backend", self.backend.get(),
            "-o", output,
        ]
        face = self.face_path.get().strip()
        if face and os.path.isfile(face):
            args.extend(["--face", face])
        if self.is_360.get():
            args.append("--360")
        view = self.view_angle.get()
        if view and view != "auto":
            args.extend(["--view", view])
        if self.force_reindex.get():
            args.append("--force-reindex")
        if self.verbose.get():
            args.append("--verbose")

        self.app.clear_log()
        self.app.log(f"▶ 開始剪輯: {Path(video).name}")
        self.app.log(f"  Prompt: {prompt}")
        self.app.log(f"  Backend: {self.backend.get()}")
        self.app.log(f"  Reindex: {'yes' if self.force_reindex.get() else 'no'}")
        self.app.log(f"  360 View: {self.view_angle.get()}")
        self.app.log(f"  Output: {output}")
        self.app.log("")

        self.app.run_job(
            args,
            status_text="剪輯中…",
            success_msg="✓ 剪輯完成！",
            active_button=self._run_btn,
        )
