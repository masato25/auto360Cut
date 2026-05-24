import os
import subprocess
import threading
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox


AUTOCUT_SCRIPT = Path(__file__).parent / "autocut.py"
PYTHON_BIN = Path(__file__).parent / ".venv" / "bin" / "python"


class AutocutGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("autoCut")
        self.geometry("700x620")
        self.minsize(600, 500)

        self._running = False
        self._init_styles()
        self._init_vars()
        self._build_ui()

    def _init_styles(self):
        self.style = ttk.Style()
        if "aqua" in self.style.theme_names():
            self.style.theme_use("aqua")

    def _init_vars(self):
        self.video_path = tk.StringVar()
        self.prompt = tk.StringVar(value="請找有人物出現、互動或畫面資訊比較有價值的片段")
        self.count = tk.IntVar(value=3)
        self.backend = tk.StringVar(value="local-api")
        self.is_360 = tk.BooleanVar(value=False)
        self.output_path = tk.StringVar()
        self.verbose = tk.BooleanVar(value=False)

    def _build_ui(self):
        main = ttk.Frame(self, padding=16)
        main.pack(fill=tk.BOTH, expand=True)

        # file
        row0 = ttk.Frame(main)
        row0.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(row0, text="影片檔案", font=("", 11, "bold")).pack(anchor=tk.W)
        frow = ttk.Frame(row0)
        frow.pack(fill=tk.X, pady=(4, 0))
        ttk.Entry(frow, textvariable=self.video_path).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(frow, text="瀏覽…", command=self._browse_file).pack(side=tk.RIGHT, padx=(6, 0))

        # prompt
        row1 = ttk.Frame(main)
        row1.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(row1, text="搜尋提示 (Prompt)", font=("", 11, "bold")).pack(anchor=tk.W)
        self.prompt_entry = tk.Text(row1, height=3, wrap=tk.WORD, font=("", 11))
        self.prompt_entry.pack(fill=tk.X, pady=(4, 0))
        self.prompt_entry.insert("1.0", self.prompt.get())

        # options
        opts = ttk.Frame(main)
        opts.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(opts, text="剪輯數量").grid(row=0, column=0, sticky=tk.W, padx=(0, 4))
        ttk.Spinbox(opts, from_=1, to=20, textvariable=self.count, width=4).grid(row=0, column=1, sticky=tk.W, padx=(0, 20))
        ttk.Label(opts, text="後端").grid(row=0, column=2, sticky=tk.W, padx=(0, 4))
        ttk.Combobox(opts, textvariable=self.backend,
                     values=["local-api", "local", "qwen-cloud", "gemini"],
                     state="readonly", width=12).grid(row=0, column=3, sticky=tk.W, padx=(0, 20))
        ttk.Checkbutton(opts, text="360 模式", variable=self.is_360).grid(row=0, column=4, sticky=tk.W)
        ttk.Checkbutton(opts, text="詳細日誌", variable=self.verbose).grid(row=0, column=5, sticky=tk.W, padx=(10, 0))

        # output
        row3 = ttk.Frame(main)
        row3.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(row3, text="輸出檔案", font=("", 11, "bold")).pack(anchor=tk.W)
        orow = ttk.Frame(row3)
        orow.pack(fill=tk.X, pady=(4, 0))
        ttk.Entry(orow, textvariable=self.output_path).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(orow, text="另存新檔…", command=self._browse_output).pack(side=tk.RIGHT, padx=(6, 0))

        # run
        self.run_btn = ttk.Button(main, text="▶ 開始剪輯", command=self._run)
        self.run_btn.pack(pady=(0, 8))

        # log
        ttk.Label(main, text="執行紀錄", font=("", 11, "bold")).pack(anchor=tk.W)
        lf = ttk.Frame(main)
        lf.pack(fill=tk.BOTH, expand=True)
        self.log_text = tk.Text(lf, height=10, wrap=tk.WORD, font=("Menlo", 9),
                                state=tk.DISABLED, bg="#1e1e1e", fg="#d4d4d4",
                                insertbackground="white")
        self.log_text.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        scroll = ttk.Scrollbar(lf, orient=tk.VERTICAL, command=self.log_text.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.configure(yscrollcommand=scroll.set)

        ttk.Label(main, text="點擊「瀏覽…」選擇影片，或將檔案路徑貼上到上方欄位",
                  font=("", 9), foreground="gray").pack(anchor=tk.W, pady=(4, 0))

    # ---- actions ----
    def _browse_file(self):
        f = filedialog.askopenfilename(
            title="選擇影片檔案",
            filetypes=[("影片", "*.mp4 *.mov *.lrv *.insv"), ("所有檔案", "*.*")]
        )
        if f:
            self._set_video(f)

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

    def _log(self, msg):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, msg + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)
        self.update_idletasks()

    def _run(self):
        if self._running:
            return
        self._running = True
        self.run_btn.configure(state=tk.DISABLED, text="■ 執行中…")

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
        if self.is_360.get():
            args.append("--360")
        if self.verbose.get():
            args.append("--verbose")

        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)
        self._log(f"▶ 開始剪輯: {Path(video).name}")
        self._log(f"  Prompt: {prompt}")
        self._log(f"  Backend: {self.backend.get()}")
        self._log(f"  Output: {output}")
        self._log("")

        threading.Thread(target=self._run_process, args=(args,), daemon=True).start()

    def _run_process(self, args):
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
            else:
                self.after(0, self._log, f"✗ 失敗 (return code {proc.returncode})")
        except Exception as e:
            self.after(0, self._log, f"✗ 錯誤: {e}")
        finally:
            self.after(0, self._done)

    def _done(self):
        self._running = False
        self.run_btn.configure(state=tk.NORMAL, text="▶ 開始剪輯")


if __name__ == "__main__":
    app = AutocutGUI()
    app.mainloop()
