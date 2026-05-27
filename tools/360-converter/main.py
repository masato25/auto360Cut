#!/usr/bin/env python3
"""
360 Video Converter - Desktop GUI (tkinter)
Convert .insv (Insta360) and 360° .mp4 to various styles.
"""

import os
import sys
import time
import threading
import subprocess
import queue
from pathlib import Path
from tkinter import (
    Tk, Frame, Label, Entry, StringVar,
    Radiobutton, IntVar, Text, messagebox, filedialog,
    ttk,
)
from tkinter.scrolledtext import ScrolledText

# Add parent to path for converter import
sys.path.insert(0, str(Path(__file__).parent.resolve()))
from converter import detect_input_type, get_available_outputs, run_conversion

# ─── Config ─────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent.resolve()
OUTPUT_DIR = BASE_DIR / "outputs"

# Style metadata (emoji + params)
STYLE_META = {
    "dual_lens": {
        "emoji": "\U0001F441\uFE0F",
        "params": [],
    },
    "cubemap": {
        "emoji": "\U0001F9CA",
        "params": [
            {"key": "size", "label": "解析度", "default": "2880x1920"},
        ],
    },
    "dual_fisheye": {
        "emoji": "\U0001F41F",
        "params": [
            {"key": "size", "label": "解析度", "default": "3840x1920"},
        ],
    },
    "tiny_planet": {
        "emoji": "\U0001F30D",
        "params": [
            {"key": "size", "label": "解析度", "default": "1920x1920"},
            {"key": "pitch", "label": "Pitch", "default": "-90"},
        ],
    },
}


# ─── Main Application ──────────────────────────────────────────────

class App:
    def __init__(self):
        self.root = Tk()
        self.root.title("360 Video Converter")
        self.root.geometry("680x800")
        self.root.minsize(600, 700)

        # Variables
        self.input_path = StringVar()
        self.input_type = StringVar(value="—")
        self.selected_style = StringVar()
        self.quality = StringVar(value="medium")
        self.param_vars = {}  # key -> StringVar

        # State
        self.available_styles = []
        self.current_input_type = None
        self.converting = False
        self.conversion_done = False
        self.output_file_path = None
        self.log_queue = queue.Queue()

        # Build UI
        self._build_ui()
        self._poll_log_queue()

        # Ensure output dir exists
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ─── UI Build ────────────────────────────────────────────────

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=16)
        main.pack(fill="both", expand=True)

        # ── Header ────────────────────────────────────────────────
        header = ttk.Frame(main)
        header.pack(fill="x", pady=(0, 12))
        ttk.Label(
            header, text="\U0001F504  360 Video Converter",
            font=("", 16, "bold"),
        ).pack(side="left")
        ttk.Label(
            header, text="INCV / 360° MP4 轉換工具",
            font=("", 9),
            foreground="gray",
        ).pack(side="right")

        # ━━━━ Section 1: Input File ━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        ttk.Label(main, text="\U0001F4C2  輸入檔案", font=("", 11, "bold")).pack(anchor="w")

        frow = ttk.Frame(main)
        frow.pack(fill="x", pady=(4, 0))
        self.input_entry = Entry(
            frow, textvariable=self.input_path,
            font=("", 11),
        )
        self.input_entry.pack(side="left", fill="x", expand=True, ipady=4)
        ttk.Button(frow, text="瀏覽…", command=self._browse_file).pack(side="right", padx=(6, 0))

        # Detected type
        type_row = ttk.Frame(main)
        type_row.pack(fill="x", pady=(4, 12))
        ttk.Label(type_row, text="檢測類型:", font=("", 10), foreground="gray").pack(side="left")
        ttk.Label(
            type_row, textvariable=self.input_type,
            font=("", 10, "bold"), foreground="#2563eb",
        ).pack(side="left", padx=(6, 0))

        # ━━━━ Section 2: Output Style ━━━━━━━━━━━━━━━━━━━━━━━━━
        ttk.Label(main, text="\U0001F3A8  輸出風格", font=("", 11, "bold")).pack(anchor="w")

        self.style_frame = ttk.Frame(main, padding=(0, 4))
        self.style_frame.pack(fill="x", pady=(0, 12))

        self.style_inner = ttk.Frame(self.style_frame)
        self.style_inner.pack(fill="x")

        ttk.Label(
            self.style_inner, text="請先選擇輸入檔案",
            foreground="gray", font=("", 10),
        ).pack()

        # ━━━━ Section 3: Advanced Parameters ━━━━━━━━━━━━━━━━━━
        ttk.Label(main, text="\u2699\uFE0F  進階參數", font=("", 11, "bold")).pack(anchor="w")

        self.param_frame = ttk.Frame(main, padding=(0, 4))
        self.param_frame.pack(fill="x", pady=(0, 12))

        self.param_inner = ttk.Frame(self.param_frame)
        self.param_inner.pack(fill="x")

        ttk.Label(
            self.param_inner, text="所選風格無額外參數",
            foreground="gray", font=("", 10),
        ).pack()

        # ━━━━ Section 4: Quality ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        quality_row = ttk.Frame(main)
        quality_row.pack(fill="x", pady=(0, 12))

        ttk.Label(quality_row, text="\U0001F4CA  編碼品質", font=("", 11, "bold")).pack(side="left")
        ttk.Combobox(
            quality_row, textvariable=self.quality,
            values=["high", "medium", "low"],
            state="readonly", width=10,
        ).pack(side="left", padx=(16, 8))
        ttk.Label(
            quality_row, text="(high=18M  medium=14M  low=10M, CRF on Linux/Win)",
            foreground="gray", font=("", 9),
        ).pack(side="left")

        # ━━━━ Section 5: Convert Button ━━━━━━━━━━━━━━━━━━━━━━━
        self.convert_btn = ttk.Button(
            main, text="\u26A1  開始轉換 Convert",
            command=self._start_conversion,
        )
        self.convert_btn.pack(fill="x", pady=(0, 12), ipady=4)

        # ━━━━ Section 6: Progress ━━━━━━━━━━━━━━━━━━━━━━━━━━━
        progress_frame = ttk.Frame(main)
        progress_frame.pack(fill="x", pady=(0, 8))

        self.progress_bar = ttk.Progressbar(
            progress_frame, mode="determinate",
        )
        self.progress_bar.pack(fill="x")

        self.progress_label = ttk.Label(
            progress_frame, text="等待開始…",
            foreground="gray", font=("", 10),
        )
        self.progress_label.pack(anchor="w", pady=(4, 0))

        # ━━━━ Section 7: Log ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        ttk.Label(main, text="\U0001F4DD  日誌", font=("", 11, "bold")).pack(anchor="w")

        log_frame = ttk.Frame(main)
        log_frame.pack(fill="both", expand=True, pady=(4, 8))

        self.log_text = Text(
            log_frame, height=6, wrap="word",
            font=("Menlo", 9),
            bg="#1e1e1e", fg="#d4d4d4", insertbackground="white",
            relief="flat", borderwidth=0,
        )
        self.log_text.configure(state="disabled")
        self.log_text.pack(fill="both", expand=True, side="left")
        scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        scroll.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=scroll.set)

        # Configure log tags
        self.log_text.tag_config("info", foreground="#d4d4d4")
        self.log_text.tag_config("success", foreground="#22c55e")
        self.log_text.tag_config("error", foreground="#ef4444")
        self.log_text.tag_config("warning", foreground="#f59e0b")
        self.log_text.tag_config("bold", font=("Menlo", 9, "bold"))
        self.log_text.tag_config("ts", foreground="#6b7280")

        # ━━━━ Section 8: Output Info & Actions ━━━━━━━━━━━━━━━━━━
        ttk.Label(main, text="\U0001F4C1  輸出位置", font=("", 11, "bold")).pack(anchor="w")

        output_frame = ttk.Frame(main)
        output_frame.pack(fill="x", pady=(4, 0))

        outdir_row = ttk.Frame(output_frame)
        outdir_row.pack(fill="x")

        ttk.Label(
            outdir_row, text="輸出目錄:",
            foreground="gray", font=("", 10),
        ).pack(side="left")
        ttk.Label(
            outdir_row, text=str(OUTPUT_DIR.resolve()),
            foreground="#22c55e", font=("", 10, "bold"),
        ).pack(side="left", padx=(6, 0))

        # Output file path (shown after conversion)
        self.output_file_label = ttk.Label(
            output_frame, text="",
            foreground="#f59e0b", font=("", 10),
        )
        self.output_file_label.pack(fill="x", pady=(4, 6))

        # Action buttons
        btn_row = ttk.Frame(output_frame)
        btn_row.pack(fill="x")

        self.open_btn = ttk.Button(
            btn_row, text="\U0001F4C2  開啟輸出資料夾",
            command=self._open_output,
            state="disabled",
        )
        self.open_btn.pack(side="left", padx=(0, 8))

        self.play_btn = ttk.Button(
            btn_row, text="\u25B6  播放影片",
            command=self._play_video,
            state="disabled",
        )
        self.play_btn.pack(side="left")

        # Footer
        ttk.Label(
            main, text="Powered by FFmpeg · 360 Video Converter v1.0",
            foreground="gray", font=("", 9),
        ).pack(pady=(12, 0))

    # ─── File Browsing ────────────────────────────────────────────

    def _browse_file(self):
        file_path = filedialog.askopenfilename(
            title="選擇 360 影片",
            filetypes=[
                ("360 Video", "*.insv *.mp4"),
                ("Insta360 INCV", "*.insv"),
                ("MP4 Video", "*.mp4"),
                ("All Files", "*.*"),
            ],
        )
        if not file_path:
            return

        self.input_path.set(file_path)
        self._analyze_file(file_path)

    def _analyze_file(self, file_path):
        """Detect input type and populate available styles."""
        self.log(f"分析檔案: {Path(file_path).name}", "info")

        detected = detect_input_type(file_path)
        self.current_input_type = detected

        if detected == "unknown":
            self.input_type.set("無法辨識")
            self.log("無法辨識輸入類型", "error")
            return

        type_map = {
            "insv": "INCV (Insta360)",
            "equirect": "360° 等距柱狀投影",
        }
        self.input_type.set(type_map.get(detected, detected))
        self.log(f"檢測類型: {type_map.get(detected, detected)}", "success")

        # Get available outputs
        styles = get_available_outputs(detected)
        self.available_styles = styles

        if not styles:
            self.log("此輸入類型無可用輸出格式", "error")
            return

        self._render_style_options(styles)
        self.log(f"可用輸出: {len(styles)} 種", "success")

    def _render_style_options(self, styles):
        """Render radio buttons for available styles."""
        # Clear old widgets
        for w in self.style_inner.winfo_children():
            w.destroy()
        self.style_buttons = {}

        self.selected_style.set("")

        for i, style in enumerate(styles):
            meta = STYLE_META.get(style["id"], {"emoji": "\U0001F3A5", "params": []})
            text = f"{meta['emoji']}  {style['label']}"

            rb = ttk.Radiobutton(
                self.style_inner,
                text=text,
                variable=self.selected_style,
                value=style["id"],
                command=self._on_style_selected,
            )
            rb.pack(anchor="w", pady=(0, 0))

            desc = ttk.Label(
                self.style_inner, text=f"    {style['description']}",
                foreground="gray", font=("", 9),
            )
            desc.pack(anchor="w", pady=(0, 6))

            self.style_buttons[style["id"]] = rb

        # Select first by default
        if styles:
            self.selected_style.set(styles[0]["id"])
            self._on_style_selected()

    def _on_style_selected(self):
        """When user selects a style, show relevant parameter inputs."""
        style_id = self.selected_style.get()
        if not style_id:
            return

        # Clear param inner
        for w in self.param_inner.winfo_children():
            w.destroy()
        self.param_vars = {}

        meta = STYLE_META.get(style_id, {"params": []})
        params = meta["params"]

        if not params:
            ttk.Label(
                self.param_inner, text="此風格無額外參數",
                foreground="gray", font=("", 10),
            ).pack(anchor="w")
            return

        for p in params:
            row = ttk.Frame(self.param_inner)
            row.pack(fill="x", pady=3)

            ttk.Label(
                row, text=f"{p['label']}:",
                font=("", 10), foreground="gray", width=12, anchor="w",
            ).pack(side="left")

            var = StringVar(value=p["default"])
            self.param_vars[p["key"]] = var

            entry = Entry(
                row, textvariable=var,
                font=("", 10),
                width=16,
            )
            entry.pack(side="left", ipady=2)

    # ─── Conversion ───────────────────────────────────────────────

    def _start_conversion(self):
        if self.converting:
            return

        input_path = self.input_path.get()
        if not input_path or not os.path.isfile(input_path):
            messagebox.showwarning("提示", "請先選擇一個有效的影片檔案")
            return

        style_id = self.selected_style.get()
        if not style_id:
            messagebox.showwarning("提示", "請選擇輸出風格")
            return

        quality = self.quality.get()

        # Collect params
        params = {}
        for key, var in self.param_vars.items():
            params[key] = var.get()

        self.converting = True
        self.conversion_done = False
        self.output_file_path = None

        self.convert_btn.config(state="disabled", text="\u23F3  轉換中...")
        self.open_btn.config(state="disabled")
        self.play_btn.config(state="disabled")
        self.output_file_label.config(text="")
        self.progress_bar["value"] = 0
        self.progress_label.config(text="初始化中...")

        self.log("\u2500" * 50, "info")
        self.log(f"開始轉換: {Path(input_path).name}", "bold")
        self.log(f"輸出風格: {style_id}", "info")
        self.log(f"品質: {quality}", "info")

        # Start conversion in a thread
        thread = threading.Thread(
            target=self._conversion_worker,
            args=(input_path, style_id, quality, params),
            daemon=True,
        )
        thread.start()

    def _conversion_worker(self, input_path, style_id, quality, params):
        """Run conversion in background thread."""
        try:
            # Progress callback
            def on_progress(secs):
                self.log_queue.put(("progress", min(secs % 100, 99)))

            success, message, output_path = run_conversion(
                input_path=input_path,
                output_style=style_id,
                output_dir=str(OUTPUT_DIR),
                quality=quality,
                params=params,
                progress_callback=on_progress,
            )

            if success:
                self.output_file_path = output_path
                self.log_queue.put(("result", (True, message, output_path)))
            else:
                self.log_queue.put(("result", (False, message, "")))

        except Exception as e:
            self.log_queue.put(("result", (False, str(e), "")))

    def _poll_log_queue(self):
        """Periodically check the log queue for messages."""
        try:
            while True:
                msg = self.log_queue.get_nowait()
                if isinstance(msg, tuple):
                    kind = msg[0]
                    if kind == "progress":
                        self.progress_bar["value"] = msg[1]
                    elif kind == "result":
                        success, message, output_path = msg[1]
                        self._on_conversion_done(success, message, output_path)
        except queue.Empty:
            pass
        self.root.after(200, self._poll_log_queue)

    def _on_conversion_done(self, success, message, output_path):
        """Handle conversion completion."""
        self.converting = False
        self.convert_btn.config(state="normal", text="\u26A1  開始轉換 Convert")

        if success:
            self.conversion_done = True
            self.progress_bar["value"] = 100
            self.progress_label.config(text="轉換完成！")
            self.log(message, "success")
            self.output_file_label.config(
                text=f"\u2714  {output_path}",
            )
            self.open_btn.config(state="normal")
            self.play_btn.config(state="normal")
            self._play_completion_sound()
        else:
            self.progress_bar["value"] = 0
            self.progress_label.config(text="轉換失敗")
            self.log(f"錯誤: {message}", "error")
            self.output_file_label.config(
                text=f"\u2718  {message}",
            )

    # ─── Logging ─────────────────────────────────────────────────

    def log(self, text, tag="info"):
        """Thread-safe append to log widget."""
        self.root.after(0, self._append_log, text, tag)

    def _append_log(self, text, tag="info"):
        """Append text to the log widget."""
        self.log_text.configure(state="normal")
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.insert("end", f"[{timestamp}] ", "ts")
        self.log_text.insert("end", f"{text}\n", tag)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    # ─── Actions ─────────────────────────────────────────────────

    def _open_output(self):
        """Open the output directory in file manager."""
        path = str(OUTPUT_DIR.resolve())
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", path])
            elif sys.platform == "win32":
                subprocess.run(["explorer", path])
            else:
                subprocess.run(["xdg-open", path])
        except Exception as e:
            self.log(f"無法開啟資料夾: {e}", "error")

    def _play_video(self):
        """Open the output video with system player."""
        if not self.output_file_path or not os.path.isfile(self.output_file_path):
            messagebox.showwarning("提示", "沒有可播放的影片")
            return

        path = str(Path(self.output_file_path).resolve())
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", path])
            elif sys.platform == "win32":
                subprocess.run(["start", path], shell=True)
            else:
                subprocess.run(["xdg-open", path])
        except Exception as e:
            self.log(f"無法播放影片: {e}", "error")

    def _play_completion_sound(self):
        """Play a system completion sound."""
        try:
            if sys.platform == "darwin":
                subprocess.Popen(
                    ["afplay", "/System/Library/Sounds/Glass.aiff"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                self.root.bell()
        except Exception:
            try:
                self.root.bell()
            except Exception:
                pass

    def _on_close(self):
        """Handle window close."""
        self.root.destroy()

    # ─── Run ──────────────────────────────────────────────────────

    def run(self):
        self.root.mainloop()


# ─── Entry Point ───────────────────────────────────────────────────

if __name__ == "__main__":
    App().run()
