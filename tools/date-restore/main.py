#!/usr/bin/env python3
"""Standalone GUI for the date restore tool."""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

BASE_DIR = Path(__file__).resolve().parent
SCRIPT = BASE_DIR / "date_restore.py"
MEDIA_FILETYPES = [("媒體檔案", "*.mp4 *.mov *.m4v *.avi *.mkv *.webm *.ts *.mts *.m2ts *.lrv *.insv *.jpg *.jpeg *.png *.heic *.heif *.webp *.tiff *.tif *.bmp *.gif"), ("所有檔案", "*.*")]

class DateRestoreApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("日期還原工具")
        self.geometry("760x620")
        self.minsize(620, 520)
        self.paths: list[str] = []
        self.dry_run = tk.BooleanVar(value=True)
        self.recursive = tk.BooleanVar(value=False)
        self.force = tk.BooleanVar(value=False)
        self._running = False
        self._stopping = False
        self._current_proc: subprocess.Popen | None = None
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        main = ttk.Frame(self, padding=16)
        main.pack(fill=tk.BOTH, expand=True)
        ttk.Label(main, text="日期還原工具", font=("", 16, "bold")).pack(anchor=tk.W)
        ttk.Label(main, text="從影片 / 圖片 metadata、檔名或檔案時間推測日期，並附加到檔名。", foreground="gray", wraplength=700).pack(anchor=tk.W, pady=(2, 12))

        list_frame = ttk.Frame(main)
        list_frame.pack(fill=tk.BOTH, expand=False)
        self.listbox = tk.Listbox(list_frame, height=8, font=("Menlo", 10))
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.listbox.yview)
        scroll.pack(side=tk.LEFT, fill=tk.Y)
        self.listbox.configure(yscrollcommand=scroll.set)
        buttons = ttk.Frame(list_frame)
        buttons.pack(side=tk.RIGHT, fill=tk.Y, padx=(8, 0))
        ttk.Button(buttons, text="新增檔案…", command=self._add_files).pack(fill=tk.X, pady=(0, 6))
        ttk.Button(buttons, text="新增資料夾…", command=self._add_dir).pack(fill=tk.X, pady=(0, 6))
        ttk.Button(buttons, text="移除選取", command=self._remove_selected).pack(fill=tk.X, pady=(0, 6))
        ttk.Button(buttons, text="清空", command=self._clear_paths).pack(fill=tk.X)

        opts = ttk.LabelFrame(main, text="選項", padding=10)
        opts.pack(fill=tk.X, pady=(12, 8))
        ttk.Checkbutton(opts, text="僅預覽 (不實際改名)", variable=self.dry_run).grid(row=0, column=0, sticky=tk.W, padx=(0, 16))
        ttk.Checkbutton(opts, text="遞迴處理子資料夾", variable=self.recursive).grid(row=0, column=1, sticky=tk.W, padx=(0, 16))
        ttk.Checkbutton(opts, text="強制處理 (跳過已有日期尾綴的檔案)", variable=self.force).grid(row=0, column=2, sticky=tk.W)
        ttk.Label(main, text="建議先用「僅預覽」確認結果，再取消勾選進行實際改名。影片 metadata 需要 ffprobe。", foreground="gray", wraplength=700).pack(anchor=tk.W, pady=(0, 8))

        run_frame = ttk.Frame(main)
        run_frame.pack(fill=tk.X, pady=(0, 10))
        self.run_btn = ttk.Button(run_frame, text="▶ 執行日期還原", command=self._run)
        self.run_btn.pack(side=tk.LEFT)
        self.stop_btn = ttk.Button(run_frame, text="強制停止", command=self._stop, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=(8, 0))
        self.status_label = ttk.Label(run_frame, text="狀態：待命", foreground="gray")
        self.status_label.pack(side=tk.LEFT, padx=(12, 0))
        self.progress = ttk.Progressbar(run_frame, mode="indeterminate")
        self.progress.pack(side=tk.RIGHT, fill=tk.X, expand=True)

        ttk.Label(main, text="執行紀錄", font=("", 11, "bold")).pack(anchor=tk.W)
        log_frame = ttk.Frame(main)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
        self.log_text = tk.Text(log_frame, height=10, wrap=tk.WORD, font=("Menlo", 9), bg="#1e1e1e", fg="#d4d4d4", insertbackground="white")
        self.log_text.configure(state=tk.DISABLED)
        self.log_text.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        log_scroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.configure(yscrollcommand=log_scroll.set)

    def _add_files(self) -> None:
        for f in filedialog.askopenfilenames(title="選擇媒體檔案", filetypes=MEDIA_FILETYPES):
            self._add_path(f)

    def _add_dir(self) -> None:
        d = filedialog.askdirectory(title="選擇資料夾")
        if d:
            self._add_path(d)

    def _add_path(self, path: str) -> None:
        if path not in self.paths:
            self.paths.append(path)
            p = Path(path)
            self.listbox.insert(tk.END, f"📁 {p.name}" if p.is_dir() else p.name)

    def _remove_selected(self) -> None:
        for idx in reversed(self.listbox.curselection()):
            self.listbox.delete(idx)
            del self.paths[idx]

    def _clear_paths(self) -> None:
        self.paths.clear()
        self.listbox.delete(0, tk.END)

    def _run(self) -> None:
        if self._running:
            return
        if not self.paths:
            messagebox.showerror("錯誤", "請至少加入一個檔案或資料夾")
            return
        args = [sys.executable, str(SCRIPT), *self.paths]
        if self.dry_run.get(): args.append("--dry-run")
        if self.recursive.get(): args.append("--recursive")
        if self.force.get(): args.append("--force")
        self._clear_log()
        self._log(f"▶ 開始日期還原: {len(self.paths)} 個路徑")
        for p in self.paths:
            self._log(f"    {Path(p).name}")
        self._log(f"  Dry-run: {'yes' if self.dry_run.get() else 'no'}")
        self._log(f"  Recursive: {'yes' if self.recursive.get() else 'no'}")
        self._log(f"  Force: {'yes' if self.force.get() else 'no'}\n")
        self._running = True
        self._stopping = False
        self.run_btn.configure(state=tk.DISABLED)
        self.stop_btn.configure(state=tk.NORMAL)
        self.status_label.configure(text="狀態：日期還原中…")
        self.progress.start(10)
        threading.Thread(target=self._worker, args=(args,), daemon=True).start()

    def _worker(self, args: list[str]) -> None:
        try:
            kwargs = {"stdout": subprocess.PIPE, "stderr": subprocess.STDOUT, "text": True, "bufsize": 1, "cwd": str(BASE_DIR)}
            if os.name != "nt":
                kwargs["preexec_fn"] = os.setsid
            proc = subprocess.Popen(args, **kwargs)
            self._current_proc = proc
            assert proc.stdout is not None
            for line in iter(proc.stdout.readline, ""):
                line = line.rstrip("\n\r")
                if line:
                    self.after(0, self._log, line)
            proc.wait()
            if self._stopping:
                self.after(0, self._log, "■ 已強制停止")
            elif proc.returncode == 0:
                self.after(0, self._log, "\n✓ 日期還原完成！")
                self.after(0, self._play_completion_sound)
            else:
                self.after(0, self._log, f"✗ 失敗 (return code {proc.returncode})")
        except Exception as exc:
            self.after(0, self._log, f"✗ 錯誤: {exc}")
        finally:
            self.after(0, self._done)

    def _stop(self) -> None:
        self._stopping = True
        proc = self._current_proc
        if not proc or proc.poll() is not None:
            return
        try:
            if os.name == "nt":
                proc.terminate()
            else:
                os.killpg(os.getpgid(proc.pid), 15)
        except Exception:
            proc.kill()

    def _done(self) -> None:
        self._running = False
        self._stopping = False
        self._current_proc = None
        self.progress.stop()
        self.status_label.configure(text="狀態：待命")
        self.run_btn.configure(state=tk.NORMAL)
        self.stop_btn.configure(state=tk.DISABLED)

    def _log(self, text: str) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, text + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _clear_log(self) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _play_completion_sound(self) -> None:
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["afplay", "/System/Library/Sounds/Glass.aiff"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                self.bell()
        except Exception:
            pass

    def _on_close(self) -> None:
        if self._running:
            self._stop()
        self.destroy()

if __name__ == "__main__":
    DateRestoreApp().mainloop()
