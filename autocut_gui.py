import json
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox


AUTOCUT_SCRIPT = Path(__file__).parent / "autocut.py"
AUTOCUT_SCRIPT_SCRIPT = Path(__file__).parent / "autocut_script.py"
ADD_DATE_SCRIPT = Path(__file__).parent / "scripts" / "add_date_to_name.py"
PYTHON_BIN = Path(__file__).parent / ".venv" / "bin" / "python"
GUI_STATE_FILE = Path.home() / ".autocut_gui_state.json"


class AutocutGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("autoCut")
        self.geometry("700x680")
        self.minsize(600, 550)

        self._running = False
        self._stopping = False
        self._current_proc: subprocess.Popen | None = None
        self._last_output: str | None = None
        self._last_success_message = "✓ 剪輯完成！"
        self._init_styles()
        self._init_vars()
        self._build_ui()
        self._load_state()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _init_styles(self):
        self.style = ttk.Style()
        if "aqua" in self.style.theme_names():
            self.style.theme_use("aqua")

    def _init_vars(self):
        # index mode
        self.index_files: list[str] = []
        self.index_backend = tk.StringVar(value="local-api")
        self.index_verbose = tk.BooleanVar(value=False)
        self.index_force_reindex = tk.BooleanVar(value=False)

        # normal mode
        self.video_path = tk.StringVar()
        self.prompt = tk.StringVar(value="Prefer the viewport with a clearly visible main person, face, or full body. Avoid empty scenery, corridors, walls, or signs. Only if no clear person is visible, choose the most impressive or scenic foreground view.")
        self.count = tk.IntVar(value=3)
        self.backend = tk.StringVar(value="local-api")
        self.is_360 = tk.BooleanVar(value=False)
        self.output_path = tk.StringVar()
        self.face_path = tk.StringVar()
        self.verbose = tk.BooleanVar(value=False)
        self.force_reindex = tk.BooleanVar(value=False)
        self.view_angle = tk.StringVar(value="auto")

        # script mode
        self.script_files: list[str] = []
        self.script_prompt = tk.StringVar(value="請根據素材編一支有起承轉合的短片，長度由你自行決定")
        self.script_backend = tk.StringVar(value="local-api")
        self.script_verbose = tk.BooleanVar(value=False)
        self.script_output = tk.StringVar()

        # auto script mode
        self.auto_files: list[str] = []
        self.auto_backend = tk.StringVar(value="local-api")
        self.auto_verbose = tk.BooleanVar(value=False)
        self.auto_output_layout = tk.StringVar(value="landscape")
        self.auto_output = tk.StringVar()

        # date restore mode
        self.date_files: list[str] = []
        self.date_dry_run = tk.BooleanVar(value=True)
        self.date_recursive = tk.BooleanVar(value=False)
        self.date_force = tk.BooleanVar(value=False)

    def _build_ui(self):
        main = ttk.Frame(self, padding=16)
        main.pack(fill=tk.BOTH, expand=True)

        notebook = ttk.Notebook(main)

        index_tab = ttk.Frame(notebook)
        notebook.add(index_tab, text="索引素材")
        self._build_index_tab(index_tab)

        normal_tab = ttk.Frame(notebook)
        notebook.add(normal_tab, text="一般剪輯")
        self._build_normal_tab(normal_tab)

        script_tab = ttk.Frame(notebook)
        notebook.add(script_tab, text="腳本模式")
        self._build_script_tab(script_tab)

        auto_tab = ttk.Frame(notebook)
        notebook.add(auto_tab, text="一鍵腳本")
        self._build_auto_tab(auto_tab)

        date_tab = ttk.Frame(notebook)
        notebook.add(date_tab, text="日期還原")
        self._build_date_tab(date_tab)

        notebook.pack(fill=tk.X, pady=(0, 10))

        # shared progress
        progress_frame = ttk.Frame(main)
        progress_frame.pack(fill=tk.X, pady=(0, 8))
        self.progress_label = ttk.Label(progress_frame, text="狀態：待命", font=("", 10))
        self.progress_label.pack(side=tk.LEFT)
        self.progress_bar = ttk.Progressbar(progress_frame, mode="indeterminate")
        self.progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 8))
        self.stop_btn = ttk.Button(progress_frame, text="強制停止", command=self._stop_process, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.RIGHT)

        # shared log
        ttk.Label(main, text="執行紀錄", font=("", 11, "bold")).pack(anchor=tk.W)
        lf = ttk.Frame(main)
        lf.pack(fill=tk.BOTH, expand=True)
        self.log_text = tk.Text(lf, height=10, wrap=tk.WORD, font=("Menlo", 9),
                                bg="#1e1e1e", fg="#d4d4d4",
                                insertbackground="white")
        self.log_text.configure(state=tk.DISABLED)
        self._bind_readonly_text_shortcuts(self.log_text)
        self.log_text.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        scroll = ttk.Scrollbar(lf, orient=tk.VERTICAL, command=self.log_text.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.configure(yscrollcommand=scroll.set)

        # footer: hint + play button
        footer = ttk.Frame(main)
        footer.pack(fill=tk.X, pady=(4, 0))
        ttk.Label(footer, text="點擊「瀏覽…」選擇影片，或將檔案路徑貼上到上方欄位",
                  font=("", 9), foreground="gray").pack(side=tk.LEFT)
        self.play_btn = ttk.Button(footer, text="▶ 播放輸出", command=self._play_output,
                                   state=tk.DISABLED)
        self.play_btn.pack(side=tk.RIGHT)

    def _load_state(self):
        try:
            data = json.loads(GUI_STATE_FILE.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except Exception as exc:
            self._log(f"⚠ 無法讀取上次暫存列表: {exc}")
            return

        if not isinstance(data, dict):
            return

        auto_files = data.get("auto_files", [])
        if isinstance(auto_files, list):
            self.auto_files = [str(f) for f in auto_files if isinstance(f, str)]
            self._refresh_auto_listbox()

        auto_output = data.get("auto_output")
        if isinstance(auto_output, str):
            self.auto_output.set(auto_output)

        auto_output_layout = data.get("auto_output_layout")
        if auto_output_layout in {"landscape", "portrait"}:
            self.auto_output_layout.set(auto_output_layout)

    def _save_state(self):
        data = {
            "auto_files": self.auto_files,
            "auto_output": self.auto_output.get().strip(),
            "auto_output_layout": self.auto_output_layout.get(),
        }
        try:
            GUI_STATE_FILE.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            self._log(f"⚠ 無法暫存目前列表: {exc}")

    def _on_close(self):
        self._save_state()
        if self._running:
            self._stop_process()
        self.destroy()

    def _bind_readonly_text_shortcuts(self, text_widget: tk.Text):
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

    # ── index mode tab ───────────────────────────────────────────────
    def _build_index_tab(self, parent):
        vl = ttk.Frame(parent)
        vl.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(vl, text="先把素材建立索引，之後一般剪輯 / 腳本模式 / 一鍵腳本會直接重用快取",
                  font=("", 11, "bold")).pack(anchor=tk.W)
        lrow = ttk.Frame(vl)
        lrow.pack(fill=tk.X, pady=(4, 0))
        self.index_listbox = tk.Listbox(lrow, height=7, font=("Menlo", 10))
        self.index_listbox.pack(side=tk.LEFT, fill=tk.X, expand=True)
        btn_frame = ttk.Frame(lrow)
        btn_frame.pack(side=tk.RIGHT, padx=(6, 0), fill=tk.Y)
        ttk.Button(btn_frame, text="新增影片…", command=self._index_add_files).pack(pady=(0, 4))
        ttk.Button(btn_frame, text="移除選取", command=self._index_remove_selected).pack(pady=(0, 4))
        ttk.Button(btn_frame, text="清空", command=self._index_clear_files).pack()

        opts = ttk.Frame(parent)
        opts.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(opts, text="後端").grid(row=0, column=0, sticky=tk.W, padx=(0, 4))
        ttk.Combobox(opts, textvariable=self.index_backend,
                     values=["local-api", "local", "qwen-cloud", "gemini"],
                     state="readonly", width=12).grid(row=0, column=1, sticky=tk.W, padx=(0, 20))
        ttk.Checkbutton(opts, text="詳細日誌", variable=self.index_verbose).grid(row=0, column=2, sticky=tk.W, padx=(0, 12))
        ttk.Checkbutton(opts, text="強制重建索引", variable=self.index_force_reindex).grid(row=0, column=3, sticky=tk.W)

        hint = ttk.Label(
            parent,
            text="提示：如果只是新增素材，不用勾強制重建；改了 360 視角提示或想刷新舊資料才需要重建。",
            foreground="gray",
            wraplength=620,
        )
        hint.pack(fill=tk.X, pady=(0, 6))

        self.run_index_btn = ttk.Button(parent, text="▶ 開始索引素材", command=self._run_index)
        self.run_index_btn.pack(pady=(6, 0))

    # ── normal mode tab ──────────────────────────────────────────────
    def _build_normal_tab(self, parent):
        # file
        row0 = ttk.Frame(parent)
        row0.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(row0, text="影片檔案", font=("", 11, "bold")).pack(anchor=tk.W)
        frow = ttk.Frame(row0)
        frow.pack(fill=tk.X, pady=(4, 0))
        ttk.Entry(frow, textvariable=self.video_path).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(frow, text="播放", command=self._play_video).pack(side=tk.RIGHT, padx=(2, 0))
        ttk.Button(frow, text="瀏覽…", command=self._browse_file).pack(side=tk.RIGHT, padx=(6, 0))

        # prompt
        row1 = ttk.Frame(parent)
        row1.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(row1, text="搜尋提示 (Prompt)", font=("", 11, "bold")).pack(anchor=tk.W)
        self.prompt_entry = tk.Text(row1, height=3, wrap=tk.WORD, font=("", 11))
        self.prompt_entry.pack(fill=tk.X, pady=(4, 0))
        self.prompt_entry.insert("1.0", self.prompt.get())

        # options
        opts = ttk.Frame(parent)
        opts.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(opts, text="剪輯數量").grid(row=0, column=0, sticky=tk.W, padx=(0, 4))
        ttk.Spinbox(opts, from_=1, to=20, textvariable=self.count, width=4).grid(row=0, column=1, sticky=tk.W, padx=(0, 20))
        ttk.Label(opts, text="後端").grid(row=0, column=2, sticky=tk.W, padx=(0, 4))
        ttk.Combobox(opts, textvariable=self.backend,
                     values=["local-api", "local", "qwen-cloud", "gemini"],
                     state="readonly", width=12).grid(row=0, column=3, sticky=tk.W, padx=(0, 20))
        ttk.Checkbutton(opts, text="360 模式", variable=self.is_360).grid(row=0, column=4, sticky=tk.W)
        ttk.Checkbutton(opts, text="詳細日誌", variable=self.verbose).grid(row=0, column=5, sticky=tk.W, padx=(10, 0))
        ttk.Label(opts, text="360 角度").grid(row=1, column=0, sticky=tk.W, padx=(0, 4))
        ttk.Combobox(opts, textvariable=self.view_angle,
                     values=["auto", "front", "right", "back", "left"],
                     state="readonly", width=8).grid(row=1, column=1, sticky=tk.W, padx=(0, 20))
        ttk.Checkbutton(opts, text="強制重建索引", variable=self.force_reindex).grid(row=1, column=2, columnspan=3, sticky=tk.W, pady=(6, 0))

        # face reference
        row2 = ttk.Frame(parent)
        row2.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(row2, text="參考臉部照片 (選填)", font=("", 11, "bold")).pack(anchor=tk.W)
        frow2 = ttk.Frame(row2)
        frow2.pack(fill=tk.X, pady=(4, 0))
        ttk.Entry(frow2, textvariable=self.face_path).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(frow2, text="選擇…", command=self._browse_face).pack(side=tk.RIGHT, padx=(6, 0))

        # output
        row3 = ttk.Frame(parent)
        row3.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(row3, text="輸出檔案", font=("", 11, "bold")).pack(anchor=tk.W)
        orow = ttk.Frame(row3)
        orow.pack(fill=tk.X, pady=(4, 0))
        ttk.Entry(orow, textvariable=self.output_path).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(orow, text="另存新檔…", command=self._browse_output).pack(side=tk.RIGHT, padx=(6, 0))

        # run
        self.run_btn = ttk.Button(parent, text="▶ 開始剪輯", command=self._run_normal)
        self.run_btn.pack(pady=(6, 0))

    # ── script mode tab ──────────────────────────────────────────────
    def _build_script_tab(self, parent):
        # video list
        vl = ttk.Frame(parent)
        vl.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(vl, text="素材影片", font=("", 11, "bold")).pack(anchor=tk.W)
        lrow = ttk.Frame(vl)
        lrow.pack(fill=tk.X, pady=(4, 0))
        self.script_listbox = tk.Listbox(lrow, height=4, font=("Menlo", 10))
        self.script_listbox.pack(side=tk.LEFT, fill=tk.X, expand=True)
        btn_frame = ttk.Frame(lrow)
        btn_frame.pack(side=tk.RIGHT, padx=(6, 0), fill=tk.Y)
        ttk.Button(btn_frame, text="新增影片…", command=self._script_add_files).pack(pady=(0, 4))
        ttk.Button(btn_frame, text="移除選取", command=self._script_remove_selected).pack()

        # prompt
        rp = ttk.Frame(parent)
        rp.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(rp, text="腳本提示 (告訴 AI 你想編什麼故事)", font=("", 11, "bold")).pack(anchor=tk.W)
        self.script_prompt_entry = tk.Text(rp, height=3, wrap=tk.WORD, font=("", 11))
        self.script_prompt_entry.pack(fill=tk.X, pady=(4, 0))
        self.script_prompt_entry.insert("1.0", self.script_prompt.get())

        # options
        sopts = ttk.Frame(parent)
        sopts.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(sopts, text="後端").grid(row=0, column=0, sticky=tk.W, padx=(0, 4))
        ttk.Combobox(sopts, textvariable=self.script_backend,
                     values=["local-api", "local", "qwen-cloud", "gemini"],
                     state="readonly", width=12).grid(row=0, column=1, sticky=tk.W, padx=(0, 20))
        ttk.Checkbutton(sopts, text="詳細日誌", variable=self.script_verbose).grid(row=0, column=2, sticky=tk.W)

        # output
        ro = ttk.Frame(parent)
        ro.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(ro, text="輸出檔案", font=("", 11, "bold")).pack(anchor=tk.W)
        sorow = ttk.Frame(ro)
        sorow.pack(fill=tk.X, pady=(4, 0))
        ttk.Entry(sorow, textvariable=self.script_output).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(sorow, text="另存新檔…", command=self._script_browse_output).pack(side=tk.RIGHT, padx=(6, 0))

        # run
        self.run_script_btn = ttk.Button(parent, text="▶ 開始腳本剪輯", command=self._run_script)
        self.run_script_btn.pack(pady=(6, 0))

    # ── auto script mode tab ─────────────────────────────────────────
    def _build_auto_tab(self, parent):
        # video list
        vl = ttk.Frame(parent)
        vl.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(vl, text="素材影片（AI 會自行分析內容決定主題與腳本）",
                  font=("", 11, "bold")).pack(anchor=tk.W)
        lrow = ttk.Frame(vl)
        lrow.pack(fill=tk.X, pady=(4, 0))
        self.auto_listbox = tk.Listbox(lrow, height=4, font=("Menlo", 10))
        self.auto_listbox.pack(side=tk.LEFT, fill=tk.X, expand=True)
        btn_frame = ttk.Frame(lrow)
        btn_frame.pack(side=tk.RIGHT, padx=(6, 0), fill=tk.Y)
        ttk.Button(btn_frame, text="新增影片…", command=self._auto_add_files).pack(pady=(0, 4))
        ttk.Button(btn_frame, text="移除選取", command=self._auto_remove_selected).pack(pady=(0, 4))
        ttk.Button(btn_frame, text="清空", command=self._auto_clear_files).pack()

        # options
        aopts = ttk.Frame(parent)
        aopts.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(aopts, text="後端").grid(row=0, column=0, sticky=tk.W, padx=(0, 4))
        ttk.Combobox(aopts, textvariable=self.auto_backend,
                     values=["local-api", "local", "qwen-cloud", "gemini"],
                     state="readonly", width=12).grid(row=0, column=1, sticky=tk.W, padx=(0, 20))
        ttk.Label(aopts, text="輸出版型").grid(row=0, column=2, sticky=tk.W, padx=(0, 4))
        ttk.Combobox(aopts, textvariable=self.auto_output_layout,
                     values=["landscape", "portrait"],
                     state="readonly", width=10).grid(row=0, column=3, sticky=tk.W, padx=(0, 20))
        ttk.Checkbutton(aopts, text="詳細日誌", variable=self.auto_verbose).grid(row=0, column=4, sticky=tk.W)

        # output
        ro = ttk.Frame(parent)
        ro.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(ro, text="輸出檔案", font=("", 11, "bold")).pack(anchor=tk.W)
        aorow = ttk.Frame(ro)
        aorow.pack(fill=tk.X, pady=(4, 0))
        ttk.Entry(aorow, textvariable=self.auto_output).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(aorow, text="另存新檔…", command=self._auto_browse_output).pack(side=tk.RIGHT, padx=(6, 0))

        # run
        self.run_auto_btn = ttk.Button(parent, text="▶ 一鍵腳本剪輯", command=self._run_auto)
        self.run_auto_btn.pack(pady=(6, 0))

    # ── index mode actions ───────────────────────────────────────────
    def _index_add_files(self):
        files = filedialog.askopenfilenames(
            title="選擇要索引的素材影片",
            filetypes=[("影片", "*.mp4 *.mov *.lrv *.insv"), ("所有檔案", "*.*")]
        )
        if not files:
            return
        for f in files:
            if f not in self.index_files:
                self.index_files.append(f)
                self.index_listbox.insert(tk.END, Path(f).name)

    def _index_remove_selected(self):
        sel = self.index_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        self.index_listbox.delete(idx)
        del self.index_files[idx]

    def _index_clear_files(self):
        self.index_files.clear()
        self.index_listbox.delete(0, tk.END)

    def _find_already_indexed_files(self, files: list[str]) -> list[str]:
        try:
            if str(Path(__file__).parent / "sentrysearch") not in sys.path:
                sys.path.insert(0, str(Path(__file__).parent / "sentrysearch"))
            from dotenv import load_dotenv
            from sentrysearch.store import SentryStore

            load_dotenv(Path(__file__).parent / ".env")
            model = os.environ.get("LOCAL_API_MODEL") or None
            store = SentryStore(backend=self.index_backend.get(), model=model)
            return [f for f in files if store.is_indexed(f)]
        except Exception as exc:
            self._log(f"⚠ 無法預先檢查索引快取，將交由索引流程判斷: {exc}")
            return []

    def _run_index(self):
        if self._running:
            return
        if not self.index_files:
            messagebox.showerror("錯誤", "請至少加入一部素材影片")
            return

        already_indexed = []
        if not self.index_force_reindex.get():
            already_indexed = self._find_already_indexed_files(self.index_files)
            if already_indexed:
                names = "\n".join(f"• {Path(f).name}" for f in already_indexed)
                messagebox.showinfo(
                    "已建立索引",
                    "以下影片已經建立過索引，這次會跳過：\n\n"
                    f"{names}\n\n若要重新建立，請勾選「強制重建索引」。",
                )

        self._start_run("索引中…", self.run_index_btn)

        args = [
            str(PYTHON_BIN), str(AUTOCUT_SCRIPT_SCRIPT), "index",
            *self.index_files,
            "--backend", self.index_backend.get(),
        ]
        if self.index_force_reindex.get():
            args.append("--force-reindex")
        if self.index_verbose.get():
            args.append("--verbose")

        self._clear_log()
        self._last_success_message = "✓ 素材索引完成！現在可以切到一般剪輯 / 腳本模式 / 一鍵腳本使用。"
        self._log(f"▶ 開始索引素材: {len(self.index_files)} 部")
        for f in self.index_files:
            self._log(f"    {Path(f).name}")
        self._log(f"  Backend: {self.index_backend.get()}")
        self._log(f"  Reindex: {'yes' if self.index_force_reindex.get() else 'no'}")
        if already_indexed:
            self._log(f"  已索引將跳過: {len(already_indexed)} 部")
            for f in already_indexed:
                self._log(f"    skip: {Path(f).name}")
        self._log("")

        threading.Thread(target=self._run_process, args=(args,), daemon=True).start()

    # ── normal mode actions ──────────────────────────────────────────
    def _play_output(self):
        path = self._last_output
        if path and os.path.isfile(path):
            subprocess.Popen(["open", path])

    def _play_video(self):
        path = self.video_path.get().strip()
        if not path or not os.path.isfile(path):
            messagebox.showwarning("提示", "請先選擇影片檔案")
            return
        subprocess.Popen(["open", path])

    def _browse_file(self):
        f = filedialog.askopenfilename(
            title="選擇影片檔案",
            filetypes=[("影片", "*.mp4 *.mov *.lrv *.insv"), ("所有檔案", "*.*")]
        )
        if f:
            self._set_video(f)

    def _browse_face(self):
        f = filedialog.askopenfilename(
            title="選擇參考臉部照片",
            filetypes=[("圖片", "*.jpg *.jpeg *.png *.webp"), ("所有檔案", "*.*")]
        )
        if f:
            self.face_path.set(f)

    def _browse_output(self):
        f = filedialog.asksaveasfilename(
            title="輸出檔案位置",
            defaultextension=".mp4",
            filetypes=[("MP4 影片", "*.mp4"), ("所有檔案", "*.*")]
        )
        if f:
            self.output_path.set(f)

    def _set_video(self, path):
        self.video_path.set(path)
        stem = Path(path).stem
        self.output_path.set(str(Path.home() / "Movies" / f"{stem}_autocut.mp4"))

    def _run_normal(self):
        if self._running:
            return
        video = self.video_path.get().strip()
        if not video or not os.path.isfile(video):
            messagebox.showerror("錯誤", "請選擇有效的影片檔案")
            return

        prompt = self.prompt_entry.get("1.0", tk.END).strip()
        if not prompt:
            messagebox.showerror("錯誤", "請輸入搜尋提示")
            return

        self._start_run("剪輯中…", self.run_btn)

        output = self.output_path.get().strip()
        if not output:
            output = str(Path.home() / "Movies" / "autocut_output.mp4")
            self.output_path.set(output)

        args = [
            str(PYTHON_BIN), str(AUTOCUT_SCRIPT), "autocut", video,
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

        self._clear_log()
        self._last_success_message = "✓ 剪輯完成！"
        self._log(f"▶ 開始剪輯: {Path(video).name}")
        self._log(f"  Prompt: {prompt}")
        self._log(f"  Backend: {self.backend.get()}")
        self._log(f"  Reindex: {'yes' if self.force_reindex.get() else 'no'}")
        self._log(f"  360 View: {self.view_angle.get()}")
        self._log(f"  Output: {output}")
        self._log("")

        threading.Thread(target=self._run_process, args=(args,), daemon=True).start()

    # ── script mode actions ──────────────────────────────────────────
    def _script_add_files(self):
        files = filedialog.askopenfilenames(
            title="選擇素材影片",
            filetypes=[("影片", "*.mp4 *.mov *.lrv *.insv"), ("所有檔案", "*.*")]
        )
        if not files:
            return
        for f in files:
            if f not in self.script_files:
                self.script_files.append(f)
                self.script_listbox.insert(tk.END, Path(f).name)
        if len(self.script_files) == 1:
            stem = Path(self.script_files[0]).stem
            self.script_output.set(str(Path.home() / "Movies" / f"{stem}_script.mp4"))

    def _script_remove_selected(self):
        sel = self.script_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        self.script_listbox.delete(idx)
        del self.script_files[idx]

    def _script_browse_output(self):
        f = filedialog.asksaveasfilename(
            title="輸出檔案位置",
            defaultextension=".mp4",
            filetypes=[("MP4 影片", "*.mp4"), ("所有檔案", "*.*")]
        )
        if f:
            self.script_output.set(f)

    def _run_script(self):
        if self._running:
            return
        if not self.script_files:
            messagebox.showerror("錯誤", "請至少加入一部素材影片")
            return

        prompt = self.script_prompt_entry.get("1.0", tk.END).strip()
        if not prompt:
            messagebox.showerror("錯誤", "請輸入腳本提示")
            return

        self._start_run("腳本剪輯中…", self.run_script_btn)

        output = self.script_output.get().strip()
        if not output:
            output = str(Path.home() / "Movies" / "script_output.mp4")
            self.script_output.set(output)

        args = [
            str(PYTHON_BIN), str(AUTOCUT_SCRIPT_SCRIPT), "create",
            *self.script_files,
            "--prompt", prompt,
            "--backend", self.script_backend.get(),
            "-o", output,
        ]
        if self.script_verbose.get():
            args.append("--verbose")

        self._clear_log()
        self._last_success_message = "✓ 腳本剪輯完成！"
        self._log(f"▶ 開始腳本剪輯: {len(self.script_files)} 部素材")
        for sf in self.script_files:
            self._log(f"    {Path(sf).name}")
        self._log(f"  Prompt: {prompt}")
        self._log(f"  Backend: {self.script_backend.get()}")
        self._log(f"  Output: {output}")
        self._log("")

        threading.Thread(target=self._run_process, args=(args,), daemon=True).start()

    # ── auto script mode actions ─────────────────────────────────────
    def _refresh_auto_listbox(self):
        self.auto_listbox.delete(0, tk.END)
        for f in self.auto_files:
            self.auto_listbox.insert(tk.END, Path(f).name)

    def _auto_add_files(self):
        files = filedialog.askopenfilenames(
            title="選擇素材影片",
            filetypes=[("影片", "*.mp4 *.mov *.lrv *.insv"), ("所有檔案", "*.*")]
        )
        if not files:
            return
        changed = False
        for f in files:
            if f not in self.auto_files:
                self.auto_files.append(f)
                self.auto_listbox.insert(tk.END, Path(f).name)
                changed = True
        if len(self.auto_files) == 1:
            stem = Path(self.auto_files[0]).stem
            self.auto_output.set(str(Path.home() / "Movies" / f"{stem}_auto.mp4"))
        if changed:
            self._save_state()

    def _auto_remove_selected(self):
        sel = self.auto_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        self.auto_listbox.delete(idx)
        del self.auto_files[idx]
        self._save_state()

    def _auto_clear_files(self):
        self.auto_files.clear()
        self.auto_listbox.delete(0, tk.END)
        self._save_state()

    def _auto_browse_output(self):
        f = filedialog.asksaveasfilename(
            title="輸出檔案位置",
            defaultextension=".mp4",
            filetypes=[("MP4 影片", "*.mp4"), ("所有檔案", "*.*")]
        )
        if f:
            self.auto_output.set(f)
            self._save_state()

    def _run_auto(self):
        if self._running:
            return
        if not self.auto_files:
            messagebox.showerror("錯誤", "請至少加入一部素材影片")
            return

        self._start_run("一鍵腳本剪輯中…", self.run_auto_btn)

        output = self.auto_output.get().strip()
        if not output:
            output = str(Path.home() / "Movies" / "auto_output.mp4")
            self.auto_output.set(output)
        self._save_state()

        args = [
            str(PYTHON_BIN), str(AUTOCUT_SCRIPT_SCRIPT), "create",
            *self.auto_files,
            "--auto-prompt",
            "--backend", self.auto_backend.get(),
            "--output-layout", self.auto_output_layout.get(),
            "-o", output,
        ]
        if self.auto_verbose.get():
            args.append("--verbose")

        self._clear_log()
        self._last_success_message = "✓ 一鍵腳本剪輯完成！"
        self._log(f"▶ 一鍵腳本剪輯: {len(self.auto_files)} 部素材")
        for sf in self.auto_files:
            self._log(f"    {Path(sf).name}")
        self._log(f"  Backend: {self.auto_backend.get()}")
        self._log(f"  Layout: {self.auto_output_layout.get()}")
        self._log(f"  Output: {output}")
        self._log("")

        threading.Thread(target=self._run_process, args=(args,), daemon=True).start()

    # ── date restore tab ─────────────────────────────────────────────
    def _build_date_tab(self, parent):
        vl = ttk.Frame(parent)
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
        ttk.Button(btn_frame, text="新增檔案…", command=self._date_add_files).pack(pady=(0, 4))
        ttk.Button(btn_frame, text="新增資料夾…", command=self._date_add_dir).pack(pady=(0, 4))
        ttk.Button(btn_frame, text="移除選取", command=self._date_remove_selected).pack(pady=(0, 4))
        ttk.Button(btn_frame, text="清空", command=self._date_clear_files).pack()

        opts = ttk.Frame(parent)
        opts.pack(fill=tk.X, pady=(0, 6))
        ttk.Checkbutton(opts, text="僅預覽 (不實際改名)", variable=self.date_dry_run).grid(row=0, column=0, sticky=tk.W, padx=(0, 12))
        ttk.Checkbutton(opts, text="遞迴處理子資料夾", variable=self.date_recursive).grid(row=0, column=1, sticky=tk.W, padx=(0, 12))
        ttk.Checkbutton(opts, text="強制處理 (跳過已有日期尾綴的檔案)", variable=self.date_force).grid(row=0, column=2, sticky=tk.W)

        hint = ttk.Label(
            parent,
            text="提示：建議先用「僅預覽」模式確認結果無誤，再取消勾選進行實際改名。",
            foreground="gray",
            wraplength=620,
        )
        hint.pack(fill=tk.X, pady=(0, 6))

        self.run_date_btn = ttk.Button(parent, text="▶ 執行日期還原", command=self._run_date)
        self.run_date_btn.pack(pady=(6, 0))

    def _date_add_files(self):
        files = filedialog.askopenfilenames(
            title="選擇媒體檔案",
            filetypes=[
                ("媒體檔案", "*.mp4 *.mov *.m4v *.avi *.mkv *.webm *.ts *.mts *.m2ts *.lrv *.jpg *.jpeg *.png *.heic *.heif *.webp *.tiff *.tif"),
                ("所有檔案", "*.*"),
            ]
        )
        if not files:
            return
        for f in files:
            if f not in self.date_files:
                self.date_files.append(f)
                self.date_listbox.insert(tk.END, Path(f).name)

    def _date_add_dir(self):
        d = filedialog.askdirectory(title="選擇資料夾")
        if not d:
            return
        # don't add the directory itself, just list files inside
        path = Path(d)
        files_added = 0
        for f in sorted(path.iterdir()):
            if f.is_file() and str(f) not in self.date_files:
                self.date_files.append(str(f))
                self.date_listbox.insert(tk.END, f.name)
                files_added += 1
        if files_added == 0:
            messagebox.showinfo("提示", "資料夾內沒有找到可加入的檔案")

    def _date_remove_selected(self):
        sel = self.date_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        self.date_listbox.delete(idx)
        del self.date_files[idx]

    def _date_clear_files(self):
        self.date_files.clear()
        self.date_listbox.delete(0, tk.END)

    def _run_date(self):
        if self._running:
            return
        if not self.date_files:
            messagebox.showerror("錯誤", "請至少加入一個檔案或資料夾")
            return

        self._start_run("日期還原中…", self.run_date_btn)

        args = [
            str(PYTHON_BIN), str(ADD_DATE_SCRIPT),
            *self.date_files,
        ]
        if self.date_dry_run.get():
            args.append("--dry-run")
        if self.date_recursive.get():
            args.append("--recursive")
        if self.date_force.get():
            args.append("--force")

        self._clear_log()
        self._last_success_message = "✓ 日期還原完成！"
        self._log(f"▶ 開始日期還原: {len(self.date_files)} 個路徑")
        for f in self.date_files:
            self._log(f"    {Path(f).name}")
        self._log(f"  Dry-run: {'yes' if self.date_dry_run.get() else 'no'}")
        self._log(f"  Recursive: {'yes' if self.date_recursive.get() else 'no'}")
        self._log(f"  Force: {'yes' if self.date_force.get() else 'no'}")
        self._log("")

        threading.Thread(target=self._run_process, args=(args,), daemon=True).start()

    # ── shared process runner ────────────────────────────────────────
    def _clear_log(self):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _log(self, msg):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, msg + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)
        self.update_idletasks()

    def _start_run(self, status_text, active_button):
        self._running = True
        self._stopping = False
        self._current_proc = None
        self._set_run_buttons_state(tk.DISABLED)
        active_button.configure(text="■ 執行中…")
        self.play_btn.configure(state=tk.DISABLED)
        self.stop_btn.configure(state=tk.NORMAL)
        self.progress_label.configure(text=f"狀態：{status_text}")
        self.progress_bar.start(12)

    def _stop_process(self):
        if not self._running:
            return
        self._stopping = True
        self.stop_btn.configure(state=tk.DISABLED)
        self.progress_label.configure(text="狀態：正在強制停止…")
        self._log("\n⚠ 正在強制停止目前執行…")
        proc = self._current_proc
        if proc and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except Exception:
                try:
                    proc.terminate()
                except Exception as e:
                    self._log(f"✗ 停止失敗: {e}")
            threading.Timer(3.0, self._kill_process_if_needed, args=(proc,)).start()

    def _kill_process_if_needed(self, proc):
        if proc.poll() is not None:
            return
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def _run_process(self, args):
        # extract output path from args (-o / --output followed by path)
        try:
            o_idx = next(i for i, a in enumerate(args) if a in ("-o", "--output"))
            self._last_output = args[o_idx + 1]
        except (StopIteration, IndexError):
            self._last_output = None

        try:
            popen_kwargs = {
                "stdout": subprocess.PIPE,
                "stderr": subprocess.STDOUT,
                "text": True,
                "bufsize": 1,
            }
            if os.name == "posix":
                popen_kwargs["start_new_session"] = True
            else:
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

            proc = subprocess.Popen(args, **popen_kwargs)
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
                self.after(0, self._log, "")
                self.after(0, self._log, self._last_success_message)
                self.after(0, self._play_completion_sound)
                if self._last_output and os.path.isfile(self._last_output):
                    self.after(0, lambda: self.play_btn.configure(state=tk.NORMAL))
            else:
                self.after(0, self._log, f"✗ 失敗 (return code {proc.returncode})")
        except Exception as e:
            self.after(0, self._log, f"✗ 錯誤: {e}")
        finally:
            self.after(0, self._done)

    def _set_run_buttons_state(self, state):
        self.run_index_btn.configure(state=state)
        self.run_btn.configure(state=state)
        self.run_script_btn.configure(state=state)
        self.run_auto_btn.configure(state=state)
        self.run_date_btn.configure(state=state)

    def _play_completion_sound(self):
        """Play a short notification sound when a job completes successfully."""
        try:
            if sys.platform == "darwin":
                subprocess.Popen(
                    ["afplay", "/System/Library/Sounds/Glass.aiff"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            elif os.name == "nt":
                import winsound

                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            else:
                self.bell()
        except Exception:
            try:
                self.bell()
            except Exception:
                pass

    def _done(self, *_):
        stopped = self._stopping
        self._running = False
        self._stopping = False
        self._current_proc = None
        self.progress_bar.stop()
        self.progress_label.configure(text="狀態：已停止" if stopped else "狀態：待命")
        self.stop_btn.configure(state=tk.DISABLED)
        self._set_run_buttons_state(tk.NORMAL)
        self.run_index_btn.configure(text="▶ 開始索引素材")
        self.run_btn.configure(text="▶ 開始剪輯")
        self.run_script_btn.configure(text="▶ 開始腳本剪輯")
        self.run_auto_btn.configure(text="▶ 一鍵腳本剪輯")
        self.run_date_btn.configure(text="▶ 執行日期還原")


if __name__ == "__main__":
    app = AutocutGUI()
    app.mainloop()
