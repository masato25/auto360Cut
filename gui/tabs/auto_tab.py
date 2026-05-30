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


class AutoTab(BaseTab):
    TAB_LABEL = "一鍵腳本"
    IDLE_LABEL = "▶ 一鍵腳本剪輯"

    def __init__(self, parent, app):
        self.auto_files: list[str] = []
        self.auto_weights: dict[str, int] = {}  # path → required flag (0 = normal, >0 = mandatory)
        self.auto_weight_var = tk.StringVar(value="0")
        self.auto_output_layout = tk.StringVar(value="landscape")
        self.auto_target_duration = tk.StringVar(value="")
        self.auto_opening_caption = tk.StringVar(value="")
        self.auto_closing_caption = tk.StringVar(value="")
        self.auto_music = tk.BooleanVar(value=True)
        self.auto_output = tk.StringVar()
        super().__init__(parent, app)

    def _build(self) -> None:
        vl = ttk.Frame(self)
        vl.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(vl, text="素材影片（AI 會自行分析內容決定主題與腳本）",
                  font=("", 11, "bold")).pack(anchor=tk.W)
        lrow = ttk.Frame(vl)
        lrow.pack(fill=tk.X, pady=(4, 0))
        self.auto_listbox = tk.Listbox(
            lrow,
            height=6,
            font=("Menlo", 10),
            selectmode=tk.EXTENDED,
            activestyle="dotbox",
            exportselection=False,
        )
        self.auto_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.auto_listbox.bind("<Double-Button-1>", self._on_double_click)
        self.auto_listbox.bind("<Return>", self._play_selected_event)
        self.auto_listbox.bind("<Delete>", self._remove_selected_event)
        self.auto_listbox.bind("plus", lambda _e: self._set_selected_weight(1))
        self.auto_listbox.bind("minus", lambda _e: self._set_selected_weight(0))
        self.auto_listbox.bind("<Left>", lambda _e: self._set_selected_weight(0))
        self.auto_listbox.bind("<Right>", lambda _e: self._set_selected_weight(1))
        bind_listbox_double_click_to_play(self.auto_listbox, self.auto_files)
        btn_frame = ttk.Frame(lrow)
        btn_frame.pack(side=tk.RIGHT, padx=(6, 0), fill=tk.Y)
        ttk.Button(btn_frame, text="新增影片…", command=self._add_files).pack(pady=(0, 4), fill=tk.X)
        ttk.Button(btn_frame, text="播放選取", command=self._play_selected).pack(pady=(0, 4), fill=tk.X)
        ttk.Button(btn_frame, text="設為必選", command=lambda: self._set_selected_weight(1)).pack(pady=(0, 4), fill=tk.X)
        ttk.Button(btn_frame, text="設為一般", command=lambda: self._set_selected_weight(0)).pack(pady=(0, 4), fill=tk.X)
        ttk.Button(btn_frame, text="移除選取", command=self._remove_selected).pack(pady=(0, 4), fill=tk.X)
        ttk.Button(btn_frame, text="清空", command=self._clear_files).pack(pady=(0, 6), fill=tk.X)
        ttk.Separator(btn_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=4)
        ttk.Button(btn_frame, text="匯出清單…", command=self._export_list).pack(pady=(4, 4), fill=tk.X)
        ttk.Button(btn_frame, text="匯入清單…", command=self._import_list).pack(fill=tk.X)

        hint_row = ttk.Frame(vl)
        hint_row.pack(fill=tk.X, pady=(4, 0))
        ttk.Label(
            hint_row,
            text="快捷鍵：Enter 播放、Delete 移除、→ / + 設為必選、← / - 設為一般",
            font=("", 9), foreground="gray",
        ).pack(side=tk.LEFT)
        self.auto_listbox.bind("<<ListboxSelect>>", self._on_listbox_select)

        aopts = ttk.Frame(self)
        aopts.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(aopts, text="輸出版型").grid(row=0, column=0, sticky=tk.W, padx=(0, 4))
        ttk.Combobox(aopts, textvariable=self.auto_output_layout,
                     values=["landscape", "portrait"],
                     state="readonly", width=10).grid(row=0, column=1, sticky=tk.W, padx=(0, 20))
        ttk.Label(aopts, text="目標長度(分)").grid(row=0, column=2, sticky=tk.W, padx=(0, 4))
        ttk.Entry(aopts, textvariable=self.auto_target_duration,
                  width=8).grid(row=0, column=3, sticky=tk.W, padx=(0, 20))
        cap = ttk.Frame(self)
        cap.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(cap, text="開場字幕（可選）", font=("", 11, "bold")).grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(cap, textvariable=self.auto_opening_caption).grid(row=1, column=0, sticky=tk.EW, pady=(4, 0))
        cap.columnconfigure(0, weight=1)

        ccap = ttk.Frame(self)
        ccap.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(ccap, text="閉場字幕（可選）", font=("", 11, "bold")).grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(ccap, textvariable=self.auto_closing_caption).grid(row=1, column=0, sticky=tk.EW, pady=(4, 0))
        ccap.columnconfigure(0, weight=1)

        music = ttk.Frame(self)
        music.pack(fill=tk.X, pady=(0, 6))
        ttk.Checkbutton(
            music,
            text="自動選擇背景音樂（從設定的音樂資料夾）",
            variable=self.auto_music,
        ).pack(anchor=tk.W)

        ttk.Label(
            self,
            text="開場/閉場字幕留空＝不加；字幕秒數預設 3 秒，可用 .env 的 AUTOCUT_CAPTION_DURATION_SECONDS 調整；Band、音樂資料夾與音量可在「設定」頁籤調整；目標長度留空＝AI 自行決定片長。設為必選的素材一定會入選。",
            font=("", 9), foreground="gray", wraplength=520,
        ).pack(fill=tk.X, pady=(0, 6))

        ro = ttk.Frame(self)
        ro.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(ro, text="輸出檔案", font=("", 11, "bold")).pack(anchor=tk.W)
        aorow = ttk.Frame(ro)
        aorow.pack(fill=tk.X, pady=(4, 0))
        ttk.Entry(aorow, textvariable=self.auto_output).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(aorow, text="另存新檔…", command=self._browse_output).pack(side=tk.RIGHT, padx=(6, 0))

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

        auto_files = data.get("auto_files", [])
        if isinstance(auto_files, list):
            self.auto_files.clear()
            self.auto_files.extend(str(f) for f in auto_files if isinstance(f, str))
            self._refresh_listbox()

        auto_weights = data.get("auto_weights", {})
        if isinstance(auto_weights, dict):
            self.auto_weights = {
                str(k): int(v) for k, v in auto_weights.items()
                if isinstance(k, str) and isinstance(v, (int, float))
            }
        else:
            self.auto_weights = {}
        # Ensure every file has a weight entry
        for f in self.auto_files:
            if f not in self.auto_weights:
                self.auto_weights[f] = 0

        auto_output = data.get("auto_output")
        if isinstance(auto_output, str):
            self.auto_output.set(auto_output)

        auto_output_layout = data.get("auto_output_layout")
        if auto_output_layout in {"landscape", "portrait"}:
            self.auto_output_layout.set(auto_output_layout)

        auto_target_duration = data.get("auto_target_duration")
        if isinstance(auto_target_duration, str):
            self.auto_target_duration.set(auto_target_duration)

        auto_opening_caption = data.get("auto_opening_caption")
        if isinstance(auto_opening_caption, str):
            self.auto_opening_caption.set(auto_opening_caption)

        auto_closing_caption = data.get("auto_closing_caption")
        if isinstance(auto_closing_caption, str):
            self.auto_closing_caption.set(auto_closing_caption)

        auto_music = data.get("auto_music")
        if isinstance(auto_music, bool):
            self.auto_music.set(auto_music)

    def save_state(self) -> None:
        # Read existing state to preserve other tabs' data
        try:
            data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        except (FileNotFoundError, Exception):
            data = {}
        if not isinstance(data, dict):
            data = {}

        data["auto_files"] = self.auto_files
        data["auto_weights"] = self.auto_weights
        data["auto_output"] = self.auto_output.get().strip()
        data["auto_output_layout"] = self.auto_output_layout.get()
        data["auto_target_duration"] = self.auto_target_duration.get().strip()
        data["auto_opening_caption"] = self.auto_opening_caption.get().strip()
        data["auto_closing_caption"] = self.auto_closing_caption.get().strip()
        data["auto_music"] = self.auto_music.get()
        try:
            _STATE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            self.app.log(f"⚠ 無法暫存目前列表: {exc}")

    # ── list management ──────────────────────────────────────────────────

    def _refresh_listbox(self) -> None:
        self.auto_listbox.delete(0, tk.END)
        for f in self.auto_files:
            w = self.auto_weights.get(f, 0)
            label = f"⚡{Path(f).name}" if w > 0 else Path(f).name
            self.auto_listbox.insert(tk.END, label)

    def _add_files(self) -> None:
        files = filedialog.askopenfilenames(
            title="選擇素材影片",
            filetypes=[("影片", "*.mp4 *.mov *.lrv *.insv"), ("所有檔案", "*.*")]
        )
        changed = False
        for f in files:
            if f not in self.auto_files:
                self.auto_files.append(f)
                self.auto_weights[f] = 0
                changed = True
        if changed:
            self._refresh_listbox()
        if len(self.auto_files) == 1:
            stem = Path(self.auto_files[0]).stem
            self.auto_output.set(str(Path.home() / "Movies" / f"{stem}_auto.mp4"))
        if changed:
            self.save_state()

    def _play_selected(self) -> None:
        play_selected_listbox_video(self.auto_listbox, self.auto_files)

    def _play_selected_event(self, event: object = None) -> str:
        self._play_selected()
        return "break"

    def _on_double_click(self, event: object = None) -> None:
        play_selected_listbox_video(self.auto_listbox, self.auto_files)

    def _remove_selected_event(self, event: object = None) -> str:
        self._remove_selected()
        return "break"

    def _remove_selected(self) -> None:
        selected = list(self.auto_listbox.curselection())
        if not selected:
            return
        for idx in reversed(selected):
            if 0 <= idx < len(self.auto_files):
                path = self.auto_files[idx]
                self.auto_files.pop(idx)
                self.auto_weights.pop(path, None)
        self._refresh_listbox()
        if self.auto_files:
            next_idx = min(selected[0], len(self.auto_files) - 1)
            self.auto_listbox.selection_set(next_idx)
            self.auto_listbox.activate(next_idx)
        self._on_listbox_select()
        self.save_state()

    def _clear_files(self) -> None:
        self.auto_files.clear()
        self.auto_weights.clear()
        self.auto_listbox.delete(0, tk.END)
        self.auto_weight_var.set("0")
        self.save_state()

    def _export_list(self) -> None:
        out = filedialog.asksaveasfilename(
            title="匯出素材清單",
            defaultextension=".json",
            filetypes=[("JSON 清單", "*.json"), ("所有檔案", "*.*")],
            initialfile="material_list.json",
        )
        if not out:
            return
        payload = {
            "version": 1,
            "files": [
                {"path": f, "required": self.auto_weights.get(f, 0) > 0}
                for f in self.auto_files
            ],
        }
        try:
            Path(out).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            self.app.log(f"✓ 已匯出 {len(self.auto_files)} 筆素材清單 → {out}")
        except Exception as exc:
            messagebox.showerror("匯出失敗", f"無法寫入檔案：{exc}")

    def _import_list(self) -> None:
        infile = filedialog.askopenfilename(
            title="匯入素材清單",
            filetypes=[("JSON 清單", "*.json"), ("所有檔案", "*.*")],
        )
        if not infile:
            return
        try:
            data = json.loads(Path(infile).read_text(encoding="utf-8"))
        except Exception as exc:
            messagebox.showerror("匯入失敗", f"無法讀取檔案：{exc}")
            return
        if not isinstance(data, dict) or not isinstance(data.get("files"), list):
            messagebox.showerror("匯入失敗", "檔案格式錯誤，找不到 files 陣列")
            return

        added = 0
        missing = []
        for entry in data["files"]:
            if not isinstance(entry, dict):
                continue
            path = entry.get("path")
            if not isinstance(path, str) or not path.strip():
                continue
            path = path.strip()
            if not Path(path).is_file():
                missing.append(Path(path).name)
                continue
            required = 1 if entry.get("required", False) else 0
            if path not in self.auto_files:
                self.auto_files.append(path)
                added += 1
            self.auto_weights[path] = max(self.auto_weights.get(path, 0), required)

        self._refresh_listbox()
        self.save_state()

        msg = f"匯入完成：新增 {added} 筆素材"
        if missing:
            msg += f"；{len(missing)} 個找不到（已略過）：{', '.join(missing[:5])}"
            if len(missing) > 5:
                msg += f" …及 {len(missing)-5} 個"
        self.app.log(f"✓ {msg}")
        if missing:
            messagebox.showwarning("部分略過", msg)

    # ── required / normal flag ──────────────────────────────────────

    def _on_listbox_select(self, event: object = None) -> None:
        sel = self.auto_listbox.curselection()
        if not sel:
            self.auto_weight_var.set("0")
            return

        weights = {
            1 if self.auto_weights.get(self.auto_files[idx], 0) > 0 else 0
            for idx in sel
            if 0 <= idx < len(self.auto_files)
        }
        if len(weights) == 1:
            self.auto_weight_var.set(str(next(iter(weights))))
        else:
            self.auto_weight_var.set("")

    def _restore_selection(self, selected: list[int]) -> None:
        for idx in selected:
            if 0 <= idx < len(self.auto_files):
                self.auto_listbox.selection_set(idx)
        if selected:
            anchor = min(selected[0], len(self.auto_files) - 1)
            if anchor >= 0:
                self.auto_listbox.activate(anchor)
                self.auto_listbox.see(anchor)

    def _set_selected_weight(self, weight: int) -> None:
        selected = list(self.auto_listbox.curselection())
        if not selected:
            return
        normalized = 1 if int(weight) > 0 else 0
        for idx in selected:
            if 0 <= idx < len(self.auto_files):
                self.auto_weights[self.auto_files[idx]] = normalized
        self.auto_weight_var.set(str(normalized))
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
            self.auto_output.set(f)
            self.save_state()

    # ── run ─────────────────────────────────────────────────────────────

    def _run(self) -> None:
        if self.app.is_running:
            return
        if not self.auto_files:
            messagebox.showerror("錯誤", "請至少加入一部素材影片")
            return

        target_duration = self.auto_target_duration.get().strip()
        if target_duration:
            try:
                if float(target_duration) <= 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("錯誤", "目標長度必須是正數，或留空")
                return

        opening_caption = self.auto_opening_caption.get().strip()
        closing_caption = self.auto_closing_caption.get().strip()

        output = self.auto_output.get().strip()
        if not output:
            output = str(Path.home() / "Movies" / "auto_output.mp4")
            self.auto_output.set(output)
        self.save_state()

        args = [
            str(_ROOT / ".venv" / "bin" / "python"),
            str(_ROOT / "autocut_script.py"), "create",
            *self.auto_files,
            "--auto-prompt",
            "--output-layout", self.auto_output_layout.get(),
            "-o", output,
        ]
        if target_duration:
            args.extend(["--target-duration-minutes", target_duration])
        if opening_caption:
            args.extend(["--opening-caption", opening_caption])
        if closing_caption:
            args.extend(["--closing-caption", closing_caption])
        if self.auto_music.get():
            args.append("--auto-music")
        # Weight args
        for path, w in self.auto_weights.items():
            if w > 0:
                args.extend(["--weight", f"{path}:{w}"])
        verbose_enabled = is_verbose_enabled()
        if verbose_enabled:
            args.append("--verbose")

        self.app.clear_log()
        self.app.log(f"▶ 一鍵腳本剪輯: {len(self.auto_files)} 部素材")
        for sf in self.auto_files:
            required = self.auto_weights.get(sf, 0) > 0
            tag = " [必選]" if required else ""
            self.app.log(f"    {Path(sf).name}{tag}")
        self.app.log("  Backend: from .env AUTOCUT_BACKEND")
        self.app.log(f"  Layout: {self.auto_output_layout.get()}")
        self.app.log(f"  Target duration: {target_duration or 'auto'} min")
        self.app.log(f"  Opening caption: {opening_caption or 'none'}")
        self.app.log(f"  Closing caption: {closing_caption or 'none'}")
        self.app.log("  Band: from .env AUTOCUT_BAND_TEXT")
        self.app.log(f"  Auto music: {'yes' if self.auto_music.get() else 'no'}")
        if opening_caption or closing_caption:
            self.app.log("  Caption duration: from .env AUTOCUT_CAPTION_DURATION_SECONDS (default 3s)")
        self.app.log(f"  Output: {output}")
        self.app.log("")

        self.app.run_job(
            args,
            status_text="一鍵腳本剪輯中…",
            success_msg="✓ 一鍵腳本剪輯完成！",
            active_button=self._run_btn,
        )
