from __future__ import annotations

import json
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .base import BaseTab
from ..settings import is_verbose_enabled
from ..utils import bind_listbox_double_click_to_play, play_selected_listbox_video

_ROOT = Path(__file__).resolve().parent.parent.parent
_STATE_FILE = Path.home() / ".autocut_gui_state.json"

_DEFAULT_PROMPT = (
    "請根據素材編一支精華短片，優先挑最精彩、有資訊量、有人物表情或故事推進的片段；"
    "長度可自行決定，寧可短而精準，不要為了湊長度加入普通片段"
)


class ScriptTab(BaseTab):
    TAB_LABEL = "腳本模式"
    IDLE_LABEL = "▶ 開始腳本剪輯"

    def __init__(self, parent, app):
        self.script_files: list[str] = []
        self.script_weights: dict[str, int] = {}  # path → required flag (0 = normal, >0 = mandatory)
        self.script_weight_var = tk.StringVar(value="0")
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
        self.script_listbox = tk.Listbox(
            lrow,
            height=6,
            font=("Menlo", 10),
            selectmode=tk.EXTENDED,
            activestyle="dotbox",
            exportselection=False,
        )
        self.script_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.script_listbox.bind("<Double-Button-1>", self._on_double_click)
        self.script_listbox.bind("<Return>", self._play_selected_event)
        self.script_listbox.bind("<Delete>", self._remove_selected_event)
        self.script_listbox.bind("plus", lambda _e: self._set_selected_weight(1))
        self.script_listbox.bind("minus", lambda _e: self._set_selected_weight(0))
        self.script_listbox.bind("<Left>", lambda _e: self._set_selected_weight(0))
        self.script_listbox.bind("<Right>", lambda _e: self._set_selected_weight(1))
        bind_listbox_double_click_to_play(self.script_listbox, self.script_files)
        btn_frame = ttk.Frame(lrow)
        btn_frame.pack(side=tk.RIGHT, padx=(6, 0), fill=tk.Y)
        ttk.Button(btn_frame, text="新增影片…", command=self._add_files).pack(pady=(0, 4), fill=tk.X)
        ttk.Button(btn_frame, text="播放選取", command=self._play_selected).pack(pady=(0, 4), fill=tk.X)
        ttk.Button(btn_frame, text="設為必選", command=lambda: self._set_selected_weight(1)).pack(pady=(0, 4), fill=tk.X)
        ttk.Button(btn_frame, text="設為一般", command=lambda: self._set_selected_weight(0)).pack(pady=(0, 4), fill=tk.X)
        ttk.Button(btn_frame, text="移除選取", command=self._remove_selected).pack(pady=(0, 4), fill=tk.X)
        ttk.Button(btn_frame, text="清空", command=self._clear_files).pack(fill=tk.X)

        hint_row = ttk.Frame(vl)
        hint_row.pack(fill=tk.X, pady=(4, 0))
        ttk.Label(
            hint_row,
            text="快捷鍵：Enter 播放、Delete 移除、→ / + 設為必選、← / - 設為一般",
            font=("", 9), foreground="gray",
        ).pack(side=tk.LEFT)
        self.script_listbox.bind("<<ListboxSelect>>", self._on_listbox_select)

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

        ttk.Label(
            self,
            text="設為必選的素材一定會入選。字幕秒數預設 3 秒，可用 .env 的 AUTOCUT_CAPTION_DURATION_SECONDS 調整。",
            font=("", 9), foreground="gray", wraplength=520,
        ).pack(fill=tk.X, pady=(0, 6))

        ro = ttk.Frame(self)
        ro.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(ro, text="輸出檔案", font=("", 11, "bold")).pack(anchor=tk.W)
        sorow = ttk.Frame(ro)
        sorow.pack(fill=tk.X, pady=(4, 0))
        ttk.Entry(sorow, textvariable=self.script_output).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(sorow, text="另存新檔…", command=self._browse_output).pack(side=tk.RIGHT, padx=(6, 0))

        self._run_btn = ttk.Button(self, text=self.IDLE_LABEL, command=self._run)
        self._run_btn.pack(pady=(6, 0))

    # ── state persistence ────────────────────────────────────────────────

    def load_state(self) -> None:
        try:
            data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except Exception as exc:
            self.app.log(f"⚠ 無法讀取上次暫存列表: {exc}")
            return
        if not isinstance(data, dict):
            return

        script_files = data.get("script_files", [])
        if isinstance(script_files, list):
            self.script_files.clear()
            self.script_files.extend(str(f) for f in script_files if isinstance(f, str))
            self._refresh_listbox()

        script_weights = data.get("script_weights", {})
        if isinstance(script_weights, dict):
            self.script_weights = {
                str(k): int(v) for k, v in script_weights.items()
                if isinstance(k, str) and isinstance(v, (int, float))
            }
        else:
            self.script_weights = {}
        for f in self.script_files:
            if f not in self.script_weights:
                self.script_weights[f] = 0

        script_output = data.get("script_output")
        if isinstance(script_output, str):
            self.script_output.set(script_output)

        script_prompt = data.get("script_prompt")
        if isinstance(script_prompt, str):
            self.script_prompt.set(script_prompt)
            self.script_prompt_entry.delete("1.0", tk.END)
            self.script_prompt_entry.insert("1.0", script_prompt)

        script_opening_caption = data.get("script_opening_caption")
        if isinstance(script_opening_caption, str):
            self.script_opening_caption.set(script_opening_caption)

        script_closing_caption = data.get("script_closing_caption")
        if isinstance(script_closing_caption, str):
            self.script_closing_caption.set(script_closing_caption)

        script_auto_music = data.get("script_auto_music")
        if isinstance(script_auto_music, bool):
            self.script_auto_music.set(script_auto_music)

    def save_state(self) -> None:
        # Read existing state to preserve other tabs' data
        try:
            data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        except (FileNotFoundError, Exception):
            data = {}
        if not isinstance(data, dict):
            data = {}

        data["script_files"] = self.script_files
        data["script_weights"] = self.script_weights
        data["script_output"] = self.script_output.get().strip()
        data["script_prompt"] = self.script_prompt.get().strip()
        data["script_opening_caption"] = self.script_opening_caption.get().strip()
        data["script_closing_caption"] = self.script_closing_caption.get().strip()
        data["script_auto_music"] = self.script_auto_music.get()
        try:
            _STATE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            self.app.log(f"⚠ 無法暫存目前列表: {exc}")

    # ── list management ──────────────────────────────────────────────────

    def _refresh_listbox(self) -> None:
        self.script_listbox.delete(0, tk.END)
        for f in self.script_files:
            w = self.script_weights.get(f, 0)
            label = f"⚡{Path(f).name}" if w > 0 else Path(f).name
            self.script_listbox.insert(tk.END, label)

    def _add_files(self) -> None:
        files = filedialog.askopenfilenames(
            title="選擇素材影片",
            filetypes=[("影片", "*.mp4 *.mov *.lrv *.insv"), ("所有檔案", "*.*")]
        )
        changed = False
        for f in files:
            if f not in self.script_files:
                self.script_files.append(f)
                self.script_weights[f] = 0
                changed = True
        if changed:
            self._refresh_listbox()
        if len(self.script_files) == 1:
            stem = Path(self.script_files[0]).stem
            self.script_output.set(str(Path.home() / "Movies" / f"{stem}_script.mp4"))
        if changed:
            self.save_state()

    def _play_selected(self) -> None:
        play_selected_listbox_video(self.script_listbox, self.script_files)

    def _play_selected_event(self, event: object = None) -> str:
        self._play_selected()
        return "break"

    def _on_double_click(self, event: object = None) -> None:
        play_selected_listbox_video(self.script_listbox, self.script_files)

    def _remove_selected_event(self, event: object = None) -> str:
        self._remove_selected()
        return "break"

    def _remove_selected(self) -> None:
        selected = list(self.script_listbox.curselection())
        if not selected:
            return
        for idx in reversed(selected):
            if 0 <= idx < len(self.script_files):
                path = self.script_files[idx]
                self.script_files.pop(idx)
                self.script_weights.pop(path, None)
        self._refresh_listbox()
        if self.script_files:
            next_idx = min(selected[0], len(self.script_files) - 1)
            self.script_listbox.selection_set(next_idx)
            self.script_listbox.activate(next_idx)
        self._on_listbox_select()
        self.save_state()

    def _clear_files(self) -> None:
        self.script_files.clear()
        self.script_weights.clear()
        self.script_listbox.delete(0, tk.END)
        self.script_weight_var.set("0")
        self.save_state()

    # ── required / normal flag ──────────────────────────────────────────

    def _on_listbox_select(self, event: object = None) -> None:
        sel = self.script_listbox.curselection()
        if not sel:
            self.script_weight_var.set("0")
            return

        weights = {
            1 if self.script_weights.get(self.script_files[idx], 0) > 0 else 0
            for idx in sel
            if 0 <= idx < len(self.script_files)
        }
        if len(weights) == 1:
            self.script_weight_var.set(str(next(iter(weights))))
        else:
            self.script_weight_var.set("")

    def _restore_selection(self, selected: list[int]) -> None:
        for idx in selected:
            if 0 <= idx < len(self.script_files):
                self.script_listbox.selection_set(idx)
        if selected:
            anchor = min(selected[0], len(self.script_files) - 1)
            if anchor >= 0:
                self.script_listbox.activate(anchor)
                self.script_listbox.see(anchor)

    def _set_selected_weight(self, weight: int) -> None:
        selected = list(self.script_listbox.curselection())
        if not selected:
            return
        normalized = 1 if int(weight) > 0 else 0
        for idx in selected:
            if 0 <= idx < len(self.script_files):
                self.script_weights[self.script_files[idx]] = normalized
        self.script_weight_var.set(str(normalized))
        self._refresh_listbox()
        self._restore_selection(selected)
        self.save_state()

    def _browse_output(self) -> None:
        f = filedialog.asksaveasfilename(
            title="輸出檔案位置",
            defaultextension=".mp4",
            filetypes=[("MP4 影片", "*.mp4"), ("所有檔案", "*.*")]
        )
        if f:
            self.script_output.set(f)
            self.save_state()

    # ── run ──────────────────────────────────────────────────────────────

    def _run(self) -> None:
        if self.app.is_running:
            return
        if not self.script_files:
            messagebox.showerror("錯誤", "請至少加入一部素材影片")
            return

        prompt = self.script_prompt_entry.get("1.0", "end-1c").strip()
        if not prompt:
            messagebox.showerror("錯誤", "請輸入腳本提示")
            return

        opening_caption = self.script_opening_caption.get().strip()
        closing_caption = self.script_closing_caption.get().strip()

        output = self.script_output.get().strip()
        if not output:
            output = str(Path.home() / "Movies" / "script_output.mp4")
            self.script_output.set(output)
        self.save_state()

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
        # Weight args
        for path, w in self.script_weights.items():
            if w > 0:
                args.extend(["--weight", f"{path}:{w}"])
        verbose_enabled = is_verbose_enabled()
        if verbose_enabled:
            args.append("--verbose")

        self.app.clear_log()
        self.app.log(f"▶ 開始腳本剪輯: {len(self.script_files)} 部素材")
        for sf in self.script_files:
            required = self.script_weights.get(sf, 0) > 0
            tag = " [必選]" if required else ""
            self.app.log(f"    {Path(sf).name}{tag}")
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
