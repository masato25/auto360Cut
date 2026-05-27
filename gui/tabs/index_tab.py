from __future__ import annotations

import os
import sys
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .base import BaseTab

_ROOT = Path(__file__).resolve().parent.parent.parent


class IndexTab(BaseTab):
    TAB_LABEL = "索引素材"
    IDLE_LABEL = "▶ 開始索引素材"

    def __init__(self, parent, app):
        self.index_files: list[str] = []
        self.index_backend = tk.StringVar(value="local-api")
        self.index_verbose = tk.BooleanVar(value=False)
        self.index_force_reindex = tk.BooleanVar(value=False)
        super().__init__(parent, app)

    def _build(self) -> None:
        vl = ttk.Frame(self)
        vl.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(vl, text="先把素材建立索引，之後一般剪輯 / 腳本模式 / 一鍵腳本會直接重用快取",
                  font=("", 11, "bold")).pack(anchor=tk.W)
        lrow = ttk.Frame(vl)
        lrow.pack(fill=tk.X, pady=(4, 0))
        self.index_listbox = tk.Listbox(lrow, height=7, font=("Menlo", 10))
        self.index_listbox.pack(side=tk.LEFT, fill=tk.X, expand=True)
        btn_frame = ttk.Frame(lrow)
        btn_frame.pack(side=tk.RIGHT, padx=(6, 0), fill=tk.Y)
        ttk.Button(btn_frame, text="新增影片…", command=self._add_files).pack(pady=(0, 4))
        ttk.Button(btn_frame, text="移除選取", command=self._remove_selected).pack(pady=(0, 4))
        ttk.Button(btn_frame, text="清空", command=self._clear_files).pack()

        opts = ttk.Frame(self)
        opts.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(opts, text="後端").grid(row=0, column=0, sticky=tk.W, padx=(0, 4))
        ttk.Combobox(opts, textvariable=self.index_backend,
                     values=["local-api", "local", "qwen-cloud", "gemini"],
                     state="readonly", width=12).grid(row=0, column=1, sticky=tk.W, padx=(0, 20))
        ttk.Checkbutton(opts, text="詳細日誌",
                        variable=self.index_verbose).grid(row=0, column=2, sticky=tk.W, padx=(0, 12))
        ttk.Checkbutton(opts, text="強制重建索引",
                        variable=self.index_force_reindex).grid(row=0, column=3, sticky=tk.W)

        ttk.Label(
            self,
            text="提示：如果只是新增素材，不用勾強制重建；改了 360 視角提示或想刷新舊資料才需要重建。",
            foreground="gray",
            wraplength=500,
        ).pack(fill=tk.X, pady=(0, 6))

        self._run_btn = ttk.Button(self, text=self.IDLE_LABEL, command=self._run)
        self._run_btn.pack(pady=(6, 0))

    def _add_files(self) -> None:
        files = filedialog.askopenfilenames(
            title="選擇要索引的素材影片",
            filetypes=[("影片", "*.mp4 *.mov *.lrv *.insv"), ("所有檔案", "*.*")]
        )
        for f in files:
            if f not in self.index_files:
                self.index_files.append(f)
                self.index_listbox.insert(tk.END, Path(f).name)

    def _remove_selected(self) -> None:
        sel = self.index_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        self.index_listbox.delete(idx)
        del self.index_files[idx]

    def _clear_files(self) -> None:
        self.index_files.clear()
        self.index_listbox.delete(0, tk.END)

    def _find_already_indexed(self, files: list[str]) -> list[str]:
        try:
            sentry_path = str(_ROOT / "sentrysearch")
            if sentry_path not in sys.path:
                sys.path.insert(0, sentry_path)
            from dotenv import load_dotenv
            from sentrysearch.store import SentryStore
            load_dotenv(_ROOT / ".env")
            model = os.environ.get("LOCAL_API_MODEL") or None
            store = SentryStore(backend=self.index_backend.get(), model=model)
            return [f for f in files if store.is_indexed(f)]
        except Exception as exc:
            self.app.log(f"⚠ 無法預先檢查索引快取，將交由索引流程判斷: {exc}")
            return []

    def _run(self) -> None:
        if self.app.is_running:
            return
        if not self.index_files:
            messagebox.showerror("錯誤", "請至少加入一部素材影片")
            return

        already_indexed: list[str] = []
        if not self.index_force_reindex.get():
            already_indexed = self._find_already_indexed(self.index_files)
            if already_indexed:
                names = "\n".join(f"• {Path(f).name}" for f in already_indexed)
                messagebox.showinfo(
                    "已建立索引",
                    "以下影片已經建立過索引，這次會跳過：\n\n"
                    f"{names}\n\n若要重新建立，請勾選「強制重建索引」。",
                )

        args = [
            str(_ROOT / ".venv" / "bin" / "python"),
            str(_ROOT / "autocut_script.py"), "index",
            *self.index_files,
            "--backend", self.index_backend.get(),
        ]
        if self.index_force_reindex.get():
            args.append("--force-reindex")
        if self.index_verbose.get():
            args.append("--verbose")

        self.app.clear_log()
        self.app.log(f"▶ 開始索引素材: {len(self.index_files)} 部")
        for f in self.index_files:
            self.app.log(f"    {Path(f).name}")
        self.app.log(f"  Backend: {self.index_backend.get()}")
        self.app.log(f"  Reindex: {'yes' if self.index_force_reindex.get() else 'no'}")
        if already_indexed:
            self.app.log(f"  已索引將跳過: {len(already_indexed)} 部")
            for f in already_indexed:
                self.app.log(f"    skip: {Path(f).name}")
        self.app.log("")

        self.app.run_job(
            args,
            status_text="索引中…",
            success_msg="✓ 素材索引完成！現在可以切到一般剪輯 / 腳本模式 / 一鍵腳本使用。",
            active_button=self._run_btn,
        )
