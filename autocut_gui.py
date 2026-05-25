import os
import os
import subprocess
import threading
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox


AUTOCUT_SCRIPT = Path(__file__).parent / "autocut.py"
AUTOCUT_SCRIPT_SCRIPT = Path(__file__).parent / "autocut_script.py"
PYTHON_BIN = Path(__file__).parent / ".venv" / "bin" / "python"


class AutocutGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("autoCut")
        self.geometry("700x680")
        self.minsize(600, 550)

        self._running = False
        self._last_output: str | None = None
        self._init_styles()
        self._init_vars()
        self._build_ui()

    def _init_styles(self):
        self.style = ttk.Style()
        if "aqua" in self.style.theme_names():
            self.style.theme_use("aqua")

    def _init_vars(self):
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
        self.auto_output = tk.StringVar()

    def _build_ui(self):
        main = ttk.Frame(self, padding=16)
        main.pack(fill=tk.BOTH, expand=True)

        notebook = ttk.Notebook(main)

        normal_tab = ttk.Frame(notebook)
        notebook.add(normal_tab, text="一般剪輯")
        self._build_normal_tab(normal_tab)

        script_tab = ttk.Frame(notebook)
        notebook.add(script_tab, text="腳本模式")
        self._build_script_tab(script_tab)

        auto_tab = ttk.Frame(notebook)
        notebook.add(auto_tab, text="一鍵腳本")
        self._build_auto_tab(auto_tab)

        notebook.pack(fill=tk.X, pady=(0, 10))

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
        ttk.Button(btn_frame, text="移除選取", command=self._auto_remove_selected).pack()

        # options
        aopts = ttk.Frame(parent)
        aopts.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(aopts, text="後端").grid(row=0, column=0, sticky=tk.W, padx=(0, 4))
        ttk.Combobox(aopts, textvariable=self.auto_backend,
                     values=["local-api", "local", "qwen-cloud", "gemini"],
                     state="readonly", width=12).grid(row=0, column=1, sticky=tk.W, padx=(0, 20))
        ttk.Checkbutton(aopts, text="詳細日誌", variable=self.auto_verbose).grid(row=0, column=2, sticky=tk.W)

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
        self._running = True
        self.run_btn.configure(state=tk.DISABLED, text="■ 執行中…")
        self.run_script_btn.configure(state=tk.DISABLED)

        video = self.video_path.get().strip()
        if not video or not os.path.isfile(video):
            messagebox.showerror("錯誤", "請選擇有效的影片檔案")
            self._done()
            return

        prompt = self.prompt_entry.get("1.0", tk.END).strip()
        if not prompt:
            messagebox.showerror("錯誤", "請輸入搜尋提示")
            self._done()
            return

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
        self._running = True
        self.run_script_btn.configure(state=tk.DISABLED, text="■ 執行中…")
        self.run_btn.configure(state=tk.DISABLED)

        if not self.script_files:
            messagebox.showerror("錯誤", "請至少加入一部素材影片")
            self._done()
            return

        prompt = self.script_prompt_entry.get("1.0", tk.END).strip()
        if not prompt:
            messagebox.showerror("錯誤", "請輸入腳本提示")
            self._done()
            return

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
        self._log(f"▶ 開始腳本剪輯: {len(self.script_files)} 部素材")
        for sf in self.script_files:
            self._log(f"    {Path(sf).name}")
        self._log(f"  Prompt: {prompt}")
        self._log(f"  Backend: {self.script_backend.get()}")
        self._log(f"  Output: {output}")
        self._log("")

        threading.Thread(target=self._run_process, args=(args,), daemon=True).start()

    # ── auto script mode actions ─────────────────────────────────────
    def _auto_add_files(self):
        files = filedialog.askopenfilenames(
            title="選擇素材影片",
            filetypes=[("影片", "*.mp4 *.mov *.lrv *.insv"), ("所有檔案", "*.*")]
        )
        if not files:
            return
        for f in files:
            if f not in self.auto_files:
                self.auto_files.append(f)
                self.auto_listbox.insert(tk.END, Path(f).name)
        if len(self.auto_files) == 1:
            stem = Path(self.auto_files[0]).stem
            self.auto_output.set(str(Path.home() / "Movies" / f"{stem}_auto.mp4"))

    def _auto_remove_selected(self):
        sel = self.auto_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        self.auto_listbox.delete(idx)
        del self.auto_files[idx]

    def _auto_browse_output(self):
        f = filedialog.asksaveasfilename(
            title="輸出檔案位置",
            defaultextension=".mp4",
            filetypes=[("MP4 影片", "*.mp4"), ("所有檔案", "*.*")]
        )
        if f:
            self.auto_output.set(f)

    def _run_auto(self):
        if self._running:
            return
        self._running = True
        self.run_auto_btn.configure(state=tk.DISABLED, text="■ 執行中…")
        self.run_btn.configure(state=tk.DISABLED)
        self.run_script_btn.configure(state=tk.DISABLED)

        if not self.auto_files:
            messagebox.showerror("錯誤", "請至少加入一部素材影片")
            self._done()
            return

        output = self.auto_output.get().strip()
        if not output:
            output = str(Path.home() / "Movies" / "auto_output.mp4")
            self.auto_output.set(output)

        args = [
            str(PYTHON_BIN), str(AUTOCUT_SCRIPT_SCRIPT), "create",
            *self.auto_files,
            "--auto-prompt",
            "--backend", self.auto_backend.get(),
            "-o", output,
        ]
        if self.auto_verbose.get():
            args.append("--verbose")

        self._clear_log()
        self._log(f"▶ 一鍵腳本剪輯: {len(self.auto_files)} 部素材")
        for sf in self.auto_files:
            self._log(f"    {Path(sf).name}")
        self._log(f"  Backend: {self.auto_backend.get()}")
        self._log(f"  Output: {output}")
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

    def _run_process(self, args):
        # extract output path from args (-o / --output followed by path)
        try:
            o_idx = next(i for i, a in enumerate(args) if a in ("-o", "--output"))
            self._last_output = args[o_idx + 1]
        except (StopIteration, IndexError):
            self._last_output = None

        try:
            proc = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            for line in iter(proc.stdout.readline, ""):
                line = line.rstrip("\n\r")
                if line:
                    self.after(0, self._log, line)
            proc.wait()
            if proc.returncode == 0:
                self.after(0, self._log, "")
                self.after(0, self._log, "✓ 剪輯完成！")
                if self._last_output and os.path.isfile(self._last_output):
                    self.after(0, lambda: self.play_btn.configure(state=tk.NORMAL))
            else:
                self.after(0, self._log, f"✗ 失敗 (return code {proc.returncode})")
        except Exception as e:
            self.after(0, self._log, f"✗ 錯誤: {e}")
        finally:
            self.after(0, self._done)

    def _done(self, *_):
        self._running = False
        self.run_btn.configure(state=tk.NORMAL, text="▶ 開始剪輯")
        self.run_script_btn.configure(state=tk.NORMAL, text="▶ 開始腳本剪輯")
        self.run_auto_btn.configure(state=tk.NORMAL, text="▶ 一鍵腳本剪輯")


if __name__ == "__main__":
    app = AutocutGUI()
    app.mainloop()
