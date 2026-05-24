# 360 影片處理指南

## 簡介

支援兩種 360 投影格式：

| 格式 | 說明 | 來源 |
|------|------|------|
| `equirect` | 等距柱狀投影 (2:1) | 一般 360 相機匯出、YouTube 360 |
| `dfisheye` | 雙魚眼左右並排 | Insta360 原生 LRV 檔案 |

**自動偵測**會檢查 `handler_name` 是否含 `INS`（Insta360）來區分兩者。

---

## 本地 AI 架構概覽

整個 pipeline 由兩台機器協作：

```
MacBook (Intel, 無 GPU)               遠端伺服器 (192.168.0.207, 有 GPU)
┌──────────────────────┐              ┌──────────────────────────────┐
│ sentrysearch CLI     │              │ llama.cpp 伺服器             │
│                      │  HTTP POST   │                              │
│ 1. 讀取影片檔         │ ──────────→  │ llama-server                 │
│ 2. ffmpeg 拆幀/轉檔   │              │   -m Qwen2.5-VL-7B.Q4_K_M   │
│ 3. 傳送圖片給 API     │ ←──────────  │   --mmproj (視覺投影檔)      │
│ 4. fastembed 文字嵌入 │   回傳文字    │   --host 0.0.0.0 --port 8080 │
│ 5. ChromaDB 向量檢索  │              │                              │
│ 6. ffmpeg 拼接輸出    │              │ 提供功能：                    │
└──────────────────────┘              │ • 圖片理解（caption）         │
                                       │ • 文字生成（clip 選取）       │
                                       └──────────────────────────────┘
```

### 各元件角色

| 元件 | 用途 | 在本地還是遠端 |
|------|------|---------------|
| **llama.cpp (llama-server)** | 提供 HTTP API 給 vision / text LLM 推理 | 遠端 GPU 伺服器 |
| **Qwen2.5-VL-7B** | 多模態模型：看懂圖片、產生描述、選取片段 | 遠端 GPU 伺服器 |
| **fastembed** | 輕量級文字嵌入（BAAI/bge-small-en-v1.5），將 caption 轉成向量 | 本地 Mac |
| **ChromaDB** | 向量資料庫，存儲 chunk 嵌入供語意搜尋 | 本地 Mac |
| **ffmpeg** | 影片拆幀、chunk 切割、360 投影轉換、最終拼接 | 本地 Mac |

---

## llama-server 設定詳解

### llama.cpp 是什麼

[llama.cpp](https://github.com/ggerganov/llama.cpp) 是一個純 C/C++ 的 LLM 推理引擎，特點：
- 不需要 Python / PyTorch / CUDA 等大型框架
- 支援 GPU 加速（CUDA / Metal / Vulkan）
- 使用 GGUF 格式的量化模型（4-bit 大幅減小記憶體）
- 內建 HTTP 伺服器（`llama-server`），提供 OpenAI 相容 API

### 下載模型

從 HuggingFace 下載 Qwen2.5-VL-7B 的 GGUF 格式：

```bash
# 下載主模型（4-bit 量化，約 4.7GB）
wget https://huggingface.co/ggml-org/Qwen2.5-VL-7B-Instruct-GGUF/resolve/main/Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf

# 下載視覺投影檔（mmproj，必須，約 2.2GB）
wget https://huggingface.co/ggml-org/Qwen2.5-VL-7B-Instruct-GGUF/resolve/main/mmproj-Qwen2.5-VL-7B-Instruct-f16.gguf
```

為什麼需要兩個檔案：
- **主模型** (`Q4_K_M.gguf`)：LLM 本身（文字推理），4-bit 量化節省記憶體
- **mmproj** (`mmproj-*-f16.gguf`)：視覺投影層，將圖片特徵對齊到 LLM 的 embedding 空間。**沒有這個檔案就無法看圖片**

> ⚠️ 雖然檔名都叫 `.gguf`，但 `mmproj` 不是完整模型，不能單獨跑。

### 啟動伺服器

基本啟動（預設 4096 context）：

```bash
llama-server \
  -m Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf \
  --mmproj mmproj-Qwen2.5-VL-7B-Instruct-f16.gguf \
  --host 0.0.0.0 \
  --port 8080
```

進階啟動（加大 context 以處理多張圖片）：

```bash
llama-server \
  -m Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf \
  --mmproj mmproj-Qwen2.5-VL-7B-Instruct-f16.gguf \
  --host 0.0.0.0 \
  --port 8080 \
  -c 8192 \
  --parallel 4 \
  --cont-batching
```

| 參數 | 說明 |
|------|------|
| `-m` | 主模型路徑 |
| `--mmproj` | 視覺投影檔路徑（**必須**，否則無法處理圖片） |
| `--host 0.0.0.0` | 監聽所有網路介面 |
| `--port 8080` | 埠號 |
| `-c 8192` | context 大小（越大能處理越多張圖片，但更吃記憶體） |
| `--parallel 4` | 平行處理請求數 |
| `--cont-batching` | 持續批次（提高吞吐量） |

### 確認伺服器正常

```bash
# 檢查模型資訊
curl http://192.168.0.207:8080/v1/models

# 測試文字生成
curl http://192.168.0.207:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "ggml-org_Qwen2.5-VL-7B-Instruct-GGUF_Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

### 注意事項

- 首次載入模型需要約 30 秒（載入到 GPU 記憶體）
- 約需 6-8GB VRAM（Q4_K_M + mmproj）
- 若使用 Metal（Mac），需加 `-ngl 1` 參數增量卸載到 GPU
- 圖片分析速度：約 3-5 秒 / 張圖片（取決於 GPU）
- 不使用的時候伺服器可以留著，佔用記憶體但不會耗電

---

## 安裝與環境

```bash
# 建立虛擬環境（需要 Python 3.11-3.12）
uv venv --python 3.12 .venv
source .venv/bin/activate

# 安裝 sentrysearch（含 local-api 相關依賴）
uv pip install -e "sentrysearch[local-api]"
```

安裝項目：
- `fastembed`（ONNX 文字嵌入，不需 GPU）
- `openai`（OpenAI 相容 API 客戶端）
- `chromadb`（向量資料庫）
- `click`（CLI 框架）

---

## 本地 API 設定

預設 API 位址為 `http://192.168.0.207:8080`，可透過以下方式修改：

```bash
# 方式 1：環境變數（建議寫入 .env）
export LOCAL_API_BASE=http://你的伺服器:8080
export LOCAL_API_MODEL=模型名稱

# 方式 2：每次指令帶入
sentrysearch index video.lrv --backend local-api \
  --api-base-url http://192.168.0.207:8080
```

### 模型自動偵測

不指定 `--api-model-name` 時，會自動呼叫 `/v1/models` 端點取得第一支模型的 ID：

```
ggml-org_Qwen2.5-VL-7B-Instruct-GGUF_Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf
```

---

## 索引 360 影片

### 單一檔案

```bash
# 自動偵測 360 格式
sentrysearch index video.lrv --backend local-api

# 強制指定格式
sentrysearch index video.lrv --backend local-api --360
sentrysearch index video.lrv --backend local-api --no-360

# 指定 API 位址
sentrysearch index video.lrv --backend local-api \
  --api-base-url http://192.168.0.207:8080
```

### 整個目錄

```bash
sentrysearch ./chain_trip/ --backend local-api --verbose
```

### 自動偵測邏輯

```python
1. ffprobe side_data 含 spherical     → "equirect"
2. 解析度 2:1 + handler_name 含 INS   → "dfisheye"  (Insta360)
3. 解析度 2:1 + 無 INS 標記            → "equirect"
```

### 索引流程（以 360 dfisheye 為例）

```
原始 LRV (1664x832, 雙魚眼)
    │
    ▼ ffmpeg chunk (30s, overlap 5s)
chunk_000.mp4
    │
    ▼ ffmpeg v360=dfisheye:flat (4 個方向)
    ├── front (yaw=0)   → frame_front.jpg
    ├── right (yaw=90)  → frame_right.jpg
    ├── back (yaw=180)  → frame_back.jpg
    └── left (yaw=270)  → frame_left.jpg
    │
    ▼ Qwen2.5-VL (看 4 張圖，回答)
    "The front view shows a moving walkway...
     Best direction: front"
    │
    ▼ fastembed (caption → 384 維向量)
    │
    ▼ ChromaDB (儲存向量 + 元資料)
```

---

## 自動剪輯（autocut）

> 建議從 `autoCut/` 根目錄執行 `python autocut.py ...`。`sentrysearch` 盡量保持接近上游；主專案才承接客製參數與工作流。

```bash
# 索引 + 選取 + 拼接一氣呵成
python autocut.py autocut video.lrv \
  --prompt "first-person perspective or over-the-shoulder user viewpoint moments" \
  --view-prompt "first-person perspective or over-the-shoulder user viewpoint, prefer the direction the user is facing" \
  --count 3 \
  --api-base-url http://192.168.0.207:8080 \
  -o ~/Desktop/output.mp4

# 改變 360 視角選擇規則後，用 --force-reindex 重新生成 metadata
python autocut.py autocut video.lrv \
  --view-prompt "第一人稱視角，或是使用者背後視角，盡量選擇使用者面朝前方的觀看方向" \
  --force-reindex \
  --hq-dir ./chain_trip_hq \
  --count 3 \
  -o ~/Desktop/output_reindexed.mp4

# 最終輸出時可直接強制固定視角
python autocut.py autocut video.lrv \
  --hq-dir ./chain_trip_hq \
  --view front \
  -o ~/Desktop/output_front.mp4

python autocut.py autocut video.lrv \
  --hq-dir ./chain_trip_hq \
  --yaw 180 \
  -o ~/Desktop/output_back.mp4
```

### 流程

1. **索引**：將影片切成 30 秒 chunks，每個 chunk 從 4 個方向取視角畫面，送 Qwen2.5-VL 依 `--view-prompt` 選最佳方向並產生描述
2. **選取**：讀取所有 chunk 的描述，送 LLM 根據 `--prompt` 選出最相關的 clips
3. **轉換**：將選中的 clips 從最佳視角或 `--view` / `--yaw` 指定視角輸出成平面影片；若 trim 來源是 Studio 匯出的 HQ equirect MP4，會重新偵測投影格式，避免沿用 LRV 的 `dfisheye` 設定造成拉伸
4. **拼接**：所有 clip 串接成一支影片

### 參數分工

- `--prompt`：控制選哪些片段
- `--view-prompt`：控制 index 時 360 chunk 的最佳方向判定
- `--force-reindex`：當 `--view-prompt` 改了，要重新產生既有 chunk metadata 時使用
- `--view`：最終輸出時強制使用 `front/right/back/left`
- `--yaw`：最終輸出時直接指定角度，優先權高於 `--view`

這樣就把「選片」和「選視角」拆開了：
- 改 `--prompt` 不會偷偷重算舊的視角 metadata
- 改 `--view-prompt` + `--force-reindex` 才會重建 chunk 視角選擇
- 或者完全不用重建，直接在輸出階段用 `--view` / `--yaw` 覆蓋

### HQ 工作流建議

1. 用原始 `.lrv` 建 index
2. 用 Insta360 Studio 把 `.insv` 匯出成高畫質 equirectangular MP4
3. autocut 時帶 `--hq-dir` 或 `--hq-source` 讓最終修剪從 HQ 素材輸出
4. 若 HQ 是 equirect，而 LRV 是 dfisheye，autoCut 會以 trim 後實際來源重新判定投影，降低變形風險

### 關於變形問題

先前你遇到的「拉長 / 過度伸展」通常有兩種來源：

1. **投影後再硬縮放**：現在已改回由上游處理；autoCut 本身不再 fork 這段邏輯
2. **把 HQ equirect MP4 誤當成 dfisheye 來轉**：目前 autoCut 會對真正拿來 trim 的來源重新偵測 projection，避免直接沿用 LRV index metadata 的投影類型

如果 HQ 檔本身已經是標準 equirect，這點特別重要。
4. **拼接**：所有 clip 串接成一支影片

### 自動選取範例

```
LLM 收到的 prompt：

You are a video editor. Given these video segments:
  #0: 00:00-00:30 - The front view shows a moving walkway...
  #1: 00:25-00:55 - The right view shows a Starbucks counter...
  #2: 00:50-01:20 - The back view shows departure boards...

Select the top 3 segments that match: "first-person perspective or over-the-shoulder user viewpoint moments"
Return only the index numbers, one per line.

LLM 回應：
0
2
1
```

---

## 指令參數

### `index`

| 參數 | 說明 |
|------|------|
| `--backend local-api` | 使用本地 API（一定要加） |
| `--api-base-url` | API 位址（預設 `http://192.168.0.207:8080`） |
| `--api-model-name` | 模型名稱（預設自動偵測） |
| `--360 / --no-360` | 強制開啟/關閉 360 模式（預設自動偵測） |
| `--verbose` | 顯示詳細日誌 |

### `autocut`

| 參數 | 說明 |
|------|------|
| `[VIDEO]` | 要處理的影片路徑（有給 → 先索引再剪輯；沒給 → 從資料庫讀取） |
| `-p, --prompt` | 描述想選取的片段內容（例如「第一人稱視角」或「使用者背後視角」；可直接從 command 傳入自訂文字） |
| `-n, --count` | 選取片段數量（預設 3） |
| `-o, --output` | 輸出影片路徑 |
| `--api-base-url` | API 位址 |
| `--hq-source` | 高畫質來源檔案（直接指定；優先於原始 VIDEO） |
| `--hq-dir` | 高畫質來源目錄（自動依 timestamp 對應 LRV → VID；優先於原始 VIDEO） |
| `--360 / --no-360` | 強制開啟/關閉 360 模式（預設自動偵測） |

### `report`

```bash
# 顯示已索引的 chunk 時間軸
sentrysearch report --backend local-api
```

輸出範例：
```
 Timeline:
  00:00  The front view shows a moving walkway...  ★  [front]
```

---

## 色彩範圍說明

Insta360 LRV 使用 `yuvj420p`（全範圍 0-255，JPEG 風格）。若未經轉換，QuickTime Player 等 macOS 播放器會顯示錯誤顏色（紫色、六色方塊等）。

輸出時 pipeline 會自動加入：
```bash
-filter:v "setparams=range=tv,format=yuv420p"
-x264-params "fullrange=0"
```

確保最終影片為標準 `yuv420p` + `color_range=tv`（有限範圍 16-235），相容所有播放器。

---

---

## 高畫質輸出工作流程

目前 pipeline 設計是**索引用 LRV（低解析度代理），輸出用 HQ 來源**：

### 方式 1：直接指定 HQ 檔案

```bash
# LRV 負責索引（快），HQ MP4 負責輸出（高畫質）
sentrysearch autocut LRV_20260415_155421_01_001.lrv \
  --prompt "first-person perspective or over-the-shoulder user viewpoint moments" --count 3 \
  --hq-source VID_20260415_155421_00_001.mp4 \
  --api-base-url http://192.168.0.207:8080 \
  -o ~/Desktop/output_hq.mp4
```

### 方式 2：自動對應目錄

```bash
# 指定 HQ 目錄，autocut 會自動找出對應的 VID 檔案
sentrysearch autocut LRV_20260415_155421_01_001.lrv \
  --prompt "first-person perspective or over-the-shoulder user viewpoint moments" --count 3 \
  --hq-dir ./chain_trip/ \
  --api-base-url http://192.168.0.207:8080 \
  -o ~/Desktop/output_hq.mp4
```

自動對應邏輯：
```
LRV_20260415_155421_01_001.lrv
  → 擷取 timestamp: 20260415_155421, seq: 001
  → 搜尋 VID_20260415_155421_00_001.mp4（或 .insv）
```

### Insta360 建議工作流程

1. **LRV 直接索引**（快，不吃 GPU）
2. 把對應的 **INSV 用 Insta360 Studio 匯出成 equirectangular MP4**
3. 用 `--hq-dir` 指向匯出目錄，autocut 自動抓 HQ 來源
4. 輸出即為高畫質 + 最佳視角

### 如何用 Insta360 Studio 輸出 360 檔案

若你手上是 `INSV` 原始檔，請先在 **Insta360 Studio** 匯出成已拼接的 360 影片，再交給 autocut 當高畫質來源。

建議步驟：

1. 在 **Insta360 Studio** 開啟對應的 `INSV` 檔案
2. 確認素材是 **360 全景**，不要先手動裁成一般平面視角
3. 點選 **Export / 匯出**
4. 輸出格式選 **MP4**
5. 投影格式選 **Equirectangular / 360**（等距柱狀投影，2:1 畫面）
6. 解析度盡量選原始或較高解析度
7. 若有編碼選項，使用 **H.264** 或 **H.265** 皆可，優先選你目前機器穩定可播放的格式
8. 匯出到集中目錄，例如 `./exports/`、`./hq/` 或相機專案資料夾底下的 `stitched/`

建議命名與放置方式：

- 保留 Insta360 預設檔名，例如 `VID_20260415_155421_00_001.mp4`
- 或至少保留相同時間戳與序號，方便 autocut 自動配對
- 之後用 `--hq-dir` 指向這個匯出資料夾即可

範例：

```bash
sentrysearch autocut LRV_20260415_155421_01_001.lrv \
  --prompt "first-person perspective or over-the-shoulder user viewpoint moments" \
  --hq-dir ./exports \
  -o output.mp4
```

注意：

- **不要輸出成一般 reframed 平面影片**，否則 autocut 就不能再替你重新選最佳視角
- **不要只保留 INSV 不匯出**，因為 INSV 原始檔無法直接當作 HQ 輸入
- 若匯出後的 MP4 不是 2:1 畫面，通常代表你輸出的不是 360 equirectangular 版本

---

## 已知限制

- **left 方向**（yaw=270）在某些 dfisheye 檔案可能提取失敗（視野邊界問題，Insta360 鏡頭縫合不完全）
- 雙魚眼需要設定 `ih_fov=200` / `iv_fov=200` 才能涵蓋完整 360 視野
- INSV 原始檔（未拼接的雙鏡頭 raw）無法直接處理，需先透過 Insta360 Studio 匯出成 mp4
- 單次 API 請求最多 4 張圖片，超過可能觸發 500 錯誤
- 每 30 秒 chunk 約需 5-10 秒的 caption 時間（取決於 GPU）
