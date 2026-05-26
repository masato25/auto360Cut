from __future__ import annotations

from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .base import BaseTab

_ROOT = Path(__file__).resolve().parent.parent.parent


class DateTab(BaseTab):
    TAB_LABEL = "日期還原"
    IDLE_LABEL = "▶ 執行日期還原"

    def __init__(self, parent, app):
        self.date_files: list[str] = []
        self.date_dry_run = tk.BooleanVar(value=True)
        self.date_recursive = tk.BooleanVar(value=False)
        self.date_force = tk.BooleanVar(value=False)
        super().__init__(parent, app)

    def _build(self) -> None:
        vl = ttk.Frame(self)
        vl.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(vl, text="從影片 / 圖片的嵌入式 metadata 還原日期，附加到檔名",
                  font=("", 11, "bold")).pack(anchor=tk.W)
        ttk.Label(vl, text="來源：EXIF (JPEG)、ffprobe creation_time (MP4/MOV)、檔名日期、檔案出生時間",
                  font=("", 9), foreground="gray").pack(anchor=tk.W)

        lrow = ttk.Frame(vl)
        lrow.pack(fill=tk.X, pady=(4, 0))
        self.date_listbox = tk.Listbox(lrow, height=6, font=("Menlo", 10))
        self.date_listbox.pack(side=tk.LEFT, fill=tk.X, expand=True)
        btn_frame = ttk.Frame(lrow)
        btn_frame.pack(side=tk.RIGHT, padx=(6, 0), fill=tk.Y)
        ttk.Button(btn_frame, text="新增檔案…", command=self._add_files).pack(pady=(0, 4))
        ttk.Button(btn_frame, text="新增資料夾…", command=self._add_dir).pack(pady=(0, 4))
        ttk.Button(btn_frame, text="移除選取", command=self._remove_selected).pack(pady=(0, 4))
        ttk.Button(btn_frame, text="清空", command=self._clear_files).pack()

        opts = ttk.Frame(self)
        opts.pack(fill=tk.X, pady=(0, 6))
        ttk.Checkbutton(opts, text="僅預覽 (不實際改名)",
                        variable=self.date_dry_run).grid(row=0, column=0, sticky=tk.W, padx=(0, 12))
        ttk.Checkbutton(opts, text="遞迴處理子資料夾",
                        variable=self.date_recursive).grid(row=0, column=1, sticky=tk.W, padx=(0, 12))
        ttk.Checkbutton(opts, text="強制處理 (跳過已有日期尾綴的檔案)",
                        variable=self.date_force).grid(row=0, column=2, sticky=tk.W)

        ttk.Label(
            self,
            text="提示：建議先用「僅預覽」模式確認結果無誤，再取消勾選進行實際改名。",
            foreground="gray",
            wraplength=620,
        ).pack(fill=tk.X, pady=(0, 6))

        self._run_btn = ttk.Button(self, text=self.IDLE_LABEL, command=self._run)
        self._run_btn.pack(pady=(6, 0))

    def _add_files(self) -> None:
        files = filedialog.askopenfilenames(
            title="選擇媒體檔案",
            filetypes=[
                ("媒體檔案", "*.mp4 *.mov *.m4v *.avi *.mkv *.webm *.ts *.mts *.m2ts "
                            "*.lrv *.jpg *.jpeg *.png *.heic *.heif *.webp *.tiff *.tif"),
                ("所有檔案", "*.*"),
            ]
        )
        for f in files:
            if f not in self.date_files:
                self.date_files.append(f)
                self.date_listbox.insert(tk.END, Path(f).name)

    def _add_dir(self) -> None:
        d = filedialog.askdirectory(title="選擇資料夾")
        if not d:
            return
        path = Path(d)
        files_added = 0
        for f in sorted(path.iterdir()):
            if f.is_file() and str(f) not in self.date_files:
                self.date_files.append(str(f))
                self.date_listbox.insert(tk.END, f.name)
                files_added += 1
        if files_added == 0:
            messagebox.showinfo("提示", "資料夾內沒有找到可加入的檔案")

    def _remove_selected(self) -> None:
        sel = self.date_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        self.date_listbox.delete(idx)
        del self.date_files[idx]

    def _clear_files(self) -> None:
        self.date_files.clear()
        self.date_listbox.delete(0, tk.END)

    def _run(self) -> None:
        if self.app.is_running:
            return
        if not self.date_files:
            messagebox.showerror("錯誤", "請至少加入一個檔案或資料夾")
            return

        args = [
            str(_ROOT / ".venv" / "bin" / "python"),
            str(_ROOT / "scripts" / "add_date_to_name.py"),
            *self.date_files,
        ]
        if self.date_dry_run.get():
            args.append("--dry-run")
        if self.date_recursive.get():
            args.append("--recursive")
        if self.date_force.get():
            args.append("--force")

        self.app.clear_log()
        self.app.log(f"▶ 開始日期還原: {len(self.date_files)} 個路徑")
        for f in self.date_files:
            self.app.log(f"    {Path(f).name}")
        self.app.log(f"  Dry-run: {'yes' if self.date_dry_run.get() else 'no'}")
        self.app.log(f"  Recursive: {'yes' if self.date_recursive.get() else 'no'}")
        self.app.log(f"  Force: {'yes' if self.date_force.get() else 'no'}")
        self.app.log("")

        self.app.run_job(
            args,
            status_text="日期還原中…",
            success_msg="✓ 日期還原完成！",
            active_button=self._run_btn,
        )
