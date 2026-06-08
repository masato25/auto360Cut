# auto360Cut 快速開始

這份文件給「只想用工具剪影片」的人，不需要理解程式碼。

## 你需要準備什麼

1. macOS / Linux / Windows WSL 皆可，建議 macOS。
2. Python 3.11–3.14。
3. ffmpeg / ffprobe。
4. 一個 AI 後端：
   - 推薦：本機或區網內的 OpenAI-compatible VLM server（例如 llama.cpp server），使用 `AUTOCUT_BACKEND=local-api`。
   - 或 Gemini / Qwen Cloud API key。
5. 影片素材：一般 `.mp4`，或 Insta360 的 `.lrv` 代理檔 + Studio 匯出的 HQ `.mp4`。

## 1. 安裝

```bash
bash scripts/install.sh
```

安裝腳本會建立 `.venv`、安裝相依套件、建立 `.env`，並處理 macOS Python 3.14 常見的 expat 問題。

## 2. 設定 `.env`

打開 `.env`，至少確認這幾個值：

```env
AUTOCUT_BACKEND=local-api
LOCAL_API_BASE=http://127.0.0.1:8080
LOCAL_API_MODEL=你的-VLM-model

AUTOCUT_SCRIPT_API_BASE=http://127.0.0.1:8080/v1
AUTOCUT_SCRIPT_API_KEY=not-needed
AUTOCUT_SCRIPT_API_MODEL=你的-文字-LLM-model
```

如果你用 Gemini：

```env
AUTOCUT_BACKEND=gemini
GEMINI_API_KEY=你的-gemini-key
```

如果你用 DeepSeek 當腳本 LLM：

```env
AUTOCUT_SCRIPT_API_BASE=https://api.deepseek.com/v1
AUTOCUT_SCRIPT_API_KEY=你的-deepseek-key
AUTOCUT_SCRIPT_API_MODEL=deepseek-chat
```

## 3. 檢查設定

```bash
./scripts/check_setup.sh
```

看到 `✓ Basic setup looks ready` 代表基本環境完成。若 local server 尚未啟動，檢查工具會用 `!` 提醒；這不一定是安裝錯誤，但你要在正式索引/剪輯前啟動它。

## 4. 開 GUI（推薦）

```bash
./scripts/run_gui.sh
```

GUI 可以選影片、輸入 prompt、選輸出檔與常用選項。這是最適合一般使用者的入口。

## 5. 一鍵腳本剪輯（多素材）

```bash
./scripts/run_script_mode.sh ./videos/LRV_001.lrv ./videos/LRV_002.lrv \
  --auto-prompt \
  --output-layout portrait \
  -o ./output.mp4
```

常用參數：

- `--auto-prompt`：讓 AI 自己根據素材規劃剪輯。
- `-p "你的剪輯需求"`：自己指定剪輯方向。
- `--output-layout landscape|portrait`：橫式或直式輸出。
- `--hq-dir ./hq-folder`：用 LRV 分析、用 HQ MP4 輸出。
- `--force-reindex`：素材或設定改很多時，強制重建索引。
- `--enhance light|vivid|cinematic`：輸出後做簡單色彩/音訊增強。

## 6. 單支影片快速剪輯（CLI）

```bash
.venv/bin/python autocut.py autocut ./videos/LRV_001.lrv \
  --prompt "first-person perspective, exciting travel moments" \
  --count 3 \
  -o ./preview.mp4
```

如果你有 HQ MP4：

```bash
.venv/bin/python autocut.py autocut ./videos/LRV_001.lrv \
  --hq-dir ./hq \
  --prompt "first-person perspective, exciting travel moments" \
  --count 3 \
  -o ./final_hq.mp4
```

## Insta360 建議流程

1. 保留相機產生的 `.lrv`，用來讓 AI 快速分析。
2. 用 Insta360 Studio 把原始 `.insv` 匯出成高畫質 360/equirectangular `.mp4`。
3. 在 auto360Cut 中指定 LRV 當輸入，並用 `--hq-dir` 或 GUI 的 HQ 來源欄位指向 HQ MP4。
4. 成品會用 HQ MP4 裁切輸出，品質會比直接用 LRV 好。

## 常見問題

### 找不到 ffmpeg

安裝 ffmpeg，並確認 `ffmpeg`、`ffprobe` 在 PATH 裡。

macOS：

```bash
brew install ffmpeg
```

### GUI 打不開，出現 tkinter 相關錯誤

macOS Homebrew Python 可能需要：

```bash
brew install python-tk@3.12
```

把 `3.12` 換成你的 Python 小版本。

### local-api 連不上

確認你的 VLM server 已啟動，且 `.env` 裡的 `LOCAL_API_BASE` 是 client 可以連到的地址。通常同一台電腦用：

```env
LOCAL_API_BASE=http://127.0.0.1:8080
```

不要把 client 連線地址寫成 `0.0.0.0`，那通常只用於 server 監聽。
