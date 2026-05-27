from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading

import tkinter as tk
from tkinter import ttk

from .utils import bind_readonly_text_shortcuts
from .tabs.index_tab import IndexTab
from .tabs.normal_tab import NormalTab
from .tabs.script_tab import ScriptTab
from .tabs.auto_tab import AutoTab


class AutocutGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("autoCut")
        self.geometry("760x720")
        self.minsize(600, 550)

        self._running = False
        self._stopping = False
        self._current_proc: subprocess.Popen | None = None
        self._last_output: str | None = None
        self._last_success_message = "✓ 剪輯完成！"
        self._tabs: list = []

        self._init_styles()
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    @property
    def is_running(self) -> bool:
        return self._running

    def _init_styles(self) -> None:
        style = ttk.Style()
        if "aqua" in style.theme_names():
            style.theme_use("aqua")

    def _build_ui(self) -> None:
        main = ttk.Frame(self, padding=16)
        main.pack(fill=tk.BOTH, expand=True)

        notebook = ttk.Notebook(main)
        for cls in [IndexTab, NormalTab, ScriptTab, AutoTab]:
            tab = cls(notebook, self)
            notebook.add(tab, text=cls.TAB_LABEL)
            self._tabs.append(tab)
        notebook.pack(fill=tk.X, pady=(0, 10))

        # shared progress
        progress_frame = ttk.Frame(main)
        progress_frame.pack(fill=tk.X, pady=(0, 8))
        self.progress_label = ttk.Label(progress_frame, text="狀態：待命", font=("", 10))
        self.progress_label.pack(side=tk.LEFT)
        self.progress_bar = ttk.Progressbar(progress_frame, mode="indeterminate")
        self.progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 8))
        self.stop_btn = ttk.Button(
            progress_frame, text="強制停止", command=self._stop_process, state=tk.DISABLED
        )
        self.stop_btn.pack(side=tk.RIGHT)

        # shared log
        ttk.Label(main, text="執行紀錄", font=("", 11, "bold")).pack(anchor=tk.W)
        lf = ttk.Frame(main)
        lf.pack(fill=tk.BOTH, expand=True)
        self.log_text = tk.Text(lf, height=10, wrap=tk.WORD, font=("Menlo", 9),
                                bg="#1e1e1e", fg="#d4d4d4", insertbackground="white")
        self.log_text.configure(state=tk.DISABLED)
        bind_readonly_text_shortcuts(self.log_text)
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

        # load persisted state after log widget is available
        for tab in self._tabs:
            if hasattr(tab, "load_state"):
                tab.load_state()

    def _on_close(self) -> None:
        for tab in self._tabs:
            if hasattr(tab, "save_state"):
                tab.save_state()
        if self._running:
            self._stop_process()
        self.destroy()

    # ── public API used by tabs ──────────────────────────────────────────

    def log(self, msg: str) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, msg + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)
        self.update_idletasks()

    def clear_log(self) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def run_job(self, args: list[str], *, status_text: str, success_msg: str,
                active_button: ttk.Button) -> None:
        self._last_success_message = success_msg
        self._start_run(status_text, active_button)
        threading.Thread(target=self._run_process, args=(args,), daemon=True).start()

    # ── internal ─────────────────────────────────────────────────────────

    def _play_output(self) -> None:
        path = self._last_output
        if path and os.path.isfile(path):
            subprocess.Popen(["open", path])

    def _start_run(self, status_text: str, active_button: ttk.Button) -> None:
        self._running = True
        self._stopping = False
        self._current_proc = None
        self._set_run_buttons_state(tk.DISABLED)
        active_button.configure(text="■ 執行中…")
        self.play_btn.configure(state=tk.DISABLED)
        self.stop_btn.configure(state=tk.NORMAL)
        self.progress_label.configure(text=f"狀態：{status_text}")
        self.progress_bar.start(12)

    def _stop_process(self) -> None:
        if not self._running:
            return
        self._stopping = True
        self.stop_btn.configure(state=tk.DISABLED)
        self.progress_label.configure(text="狀態：正在強制停止…")
        self.log("\n⚠ 正在強制停止目前執行…")
        proc = self._current_proc
        if proc and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except Exception:
                try:
                    proc.terminate()
                except Exception as e:
                    self.log(f"✗ 停止失敗: {e}")
            threading.Timer(3.0, self._kill_process_if_needed, args=(proc,)).start()

    def _kill_process_if_needed(self, proc: subprocess.Popen) -> None:
        if proc.poll() is not None:
            return
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def _run_process(self, args: list[str]) -> None:
        try:
            o_idx = next(i for i, a in enumerate(args) if a in ("-o", "--output"))
            self._last_output = args[o_idx + 1]
        except (StopIteration, IndexError):
            self._last_output = None

        try:
            popen_kwargs: dict = {
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
                    self.after(0, self.log, line)
            proc.wait()
            if self._stopping:
                self.after(0, self.log, "■ 已強制停止")
            elif proc.returncode == 0:
                self.after(0, self.log, "")
                self.after(0, self.log, self._last_success_message)
                self.after(0, self._play_completion_sound)
                if self._last_output and os.path.isfile(self._last_output):
                    self.after(0, lambda: self.play_btn.configure(state=tk.NORMAL))
            else:
                self.after(0, self.log, f"✗ 失敗 (return code {proc.returncode})")
        except Exception as e:
            self.after(0, self.log, f"✗ 錯誤: {e}")
        finally:
            self.after(0, self._done)

    def _set_run_buttons_state(self, state: str) -> None:
        for tab in self._tabs:
            tab.set_run_button_state(state)

    def _play_completion_sound(self) -> None:
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

    def _done(self, *_) -> None:
        stopped = self._stopping
        self._running = False
        self._stopping = False
        self._current_proc = None
        self.progress_bar.stop()
        self.progress_label.configure(text="狀態：已停止" if stopped else "狀態：待命")
        self.stop_btn.configure(state=tk.DISABLED)
        self._set_run_buttons_state(tk.NORMAL)
        for tab in self._tabs:
            tab.reset_run_button()
