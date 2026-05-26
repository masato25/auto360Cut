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
┌──────────────────────────┐          ┌──────────────────────────────┐
│ auto360Cut (autocut.py)  │          │ llama.cpp 伺服器             │
│                          │ HTTP POST│                              │
│ 1. 讀取影片檔             │ ───────→ │ llama-server                 │
│ 2. ffmpeg 拆幀/轉檔       │          │   -m Qwen2.5-VL-7B.Q4_K_M   │
│ 3. 傳送圖片給 API         │ ←─────── │   --mmproj (視覺投影檔)      │
│ 4. API /v1/embeddings    │ 回傳文字  │   --host 0.0.0.0 --port 8080 │
│ 5. ChromaDB 向量檢索      │          │                              │
│ 6. ffmpeg 拼接輸出        │          │ 提供功能：                    │
└──────────────────────────┘          │ • 圖片理解（caption）         │
                                       │ • 文字嵌入（embeddings）      │
                                       └──────────────────────────────┘
```

### 各元件角色

| 元件 | 用途 | 在本地還是遠端 |
|------|------|---------------|
| **llama.cpp (llama-server)** | 提供 HTTP API 給 vision / text LLM 推理 | 遠端 GPU 伺服器 |
| **Qwen2.5-VL-7B** | 多模態模型：看懂圖片、產生描述、文字嵌入 | 遠端 GPU 伺服器 |
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
# 建立虛擬環境（需要 Python 3.11-3.14）
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip

# macOS 3.14 expat 問題：先執行以下指令再繼續
# brew install expat
# export DYLD_LIBRARY_PATH=/opt/homebrew/Cellar/expat/2.8.1/lib

# 安裝 auto360Cut 依賴（含 local-api backend）
python -m pip install -r requirements-local-api.txt
```

依賴透過 `sentrysearch` submodule 管理，依安裝的 extras 決定：

**核心依賴**（`sentrysearch` 核心，一定會裝）：
- `click`（CLI 框架）
- `python-dotenv`（環境變數管理）
- `chromadb`（向量資料庫）
- `google-genai`（Gemini 嵌入 backend）
- `imageio-ffmpeg`（影片幀提取）
- `protobuf`（序列化）

**Local API 模式**（`requirements-local-api.txt` 額外安裝）：
- `openai`（OpenAI 相容 API 客戶端）

**Qwen Cloud 模式**（`requirements-qwen-cloud.txt` 額外安裝）：
- `dashscope`（阿里雲 DashScope SDK）

**Local 模式**（直接在地端推理）：
- `torch`、`torchvision`、`transformers`、`accelerate`、`qwen-vl-utils`、`torchcodec`

---

## 環境設定

API 位址與模型名稱透過 `.env` 設定（位於 auto360Cut 專案根目錄）：

```bash
cp .env.example .env
```

填入你的實際位址與模型：

```bash
AUTOCUT_BACKEND=local-api
LOCAL_API_BASE=http://192.168.0.207:8080
LOCAL_API_MODEL=ggml-org_Qwen2.5-VL-7B-Instruct-GGUF_Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf
```

設定完成後，所有指令會自動讀取這些變數，不需再手動帶入 `--api-base-url`。

---

## 使用方式

### 單一指令：索引 + 選取 + 拼接

```bash
./.venv/bin/python autocut.py autocut video.lrv \
  --prompt "first-person perspective or over-the-shoulder user viewpoint moments" \
  --count 3 \
  -o ./output.mp4
```

### 只索引（不上游 CLI passthrough）

`autocut.py` 提供 `upstream` 子指令，可透傳到上游 `sentrysearch` 原生 CLI：

```bash
./.venv/bin/python autocut.py upstream index video.lrv --backend local-api
./.venv/bin/python autocut.py upstream report --backend local-api
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
    ▼ API /v1/embeddings (caption → 768 維向量)
    │
    ▼ ChromaDB (儲存向量 + 元資料)
```

---

## 自動剪輯（autocut）

```bash
# 索引 + 選取 + 拼接一氣呵成
./.venv/bin/python autocut.py autocut video.lrv \
  --prompt "first-person perspective or over-the-shoulder user viewpoint moments" \
  --count 3 \
  -o ~/Desktop/output.mp4

# 改變 360 視角選擇規則後，用 --force-reindex 重新生成 metadata
./.venv/bin/python autocut.py autocut video.lrv \
  --force-reindex \
  --hq-dir ./chain_trip_hq \
  --count 3 \
  -o ~/Desktop/output_reindexed.mp4

# 最終輸出時可直接強制固定視角
./.venv/bin/python autocut.py autocut video.lrv \
  --hq-dir ./chain_trip_hq \
  --view front \
  -o ~/Desktop/output_front.mp4

./.venv/bin/python autocut.py autocut video.lrv \
  --hq-dir ./chain_trip_hq \
  --yaw 180 \
  -o ~/Desktop/output_back.mp4
```

### 流程

1. **索引**：將影片切成 30 秒 chunks；360 chunk 會先轉成 `front/right/back/left` 四個平面視角，分別送 Qwen2.5-VL 產生 caption 與 embedding，再把最佳視角 metadata 存入 ChromaDB
2. **選取**：將 prompt 轉成向量，在 ChromaDB 做語意搜尋，選出最相關的 clips
3. **自動視角**：索引階段也會把 prompt 與四個視角 caption 做 embedding 相似度比對，寫入 `best_direction` / `best_yaw`；`--view auto` 會使用這個結果
4. **轉換**：將選中的 clips 從最佳視角或 `--view` / `--yaw` 指定視角輸出成平面影片；若 trim 來源是 Studio 匯出的 HQ equirect MP4，會重新偵測投影格式，避免沿用 LRV 的 `dfisheye` 設定造成拉伸
5. **拼接**：所有 clip 串接成一支影片

### 參數分工

- `--prompt`：控制選哪些片段，也控制 360 自動視角要偏向哪種畫面；同一段 chunk 可能因 prompt 不同而選到不同 `best_direction`
- `--force-reindex`：重建既有 chunk 的索引；若 cached caption 為空、視角索引版本過期、projection 改變，或 360 索引使用的 prompt 不同，auto360Cut 也會自動重建該 chunk
- `--view`：最終輸出時強制使用 `front/right/back/left`；預設 `auto` 使用索引 metadata 的最佳視角
- `--yaw`：最終輸出時直接指定角度，優先權高於 `--view`

### 360 自動視角 metadata

每個 360 chunk 會保存下列資訊，方便後續輸出與除錯：

| 欄位 | 說明 |
|------|------|
| `best_direction` | `front` / `right` / `back` / `left`，prompt 比對後選出的方向 |
| `best_yaw` | 對應 yaw 角度，輸出時會正規化到 ffmpeg v360 可用範圍 |
| `viewport_prompt` | 建立此視角索引時使用的 prompt |
| `viewport_captions` | 四個視角 caption 的合併摘要 |
| `viewport_index_version` | 視角索引策略版本，用於判斷 cache 是否仍有效 |

### HQ 工作流建議

1. 用原始 `.lrv` 建 index
2. 用 Insta360 Studio 把 `.insv` 匯出成高畫質 equirectangular MP4
3. autocut 時帶 `--hq-dir` 或 `--hq-source` 讓最終修剪從 HQ 素材輸出
4. 若 HQ 是 equirect，而 LRV 是 dfisheye，auto360Cut 會以 trim 後實際來源重新判定投影，降低變形風險

### 關於變形問題

先前你遇到的「拉長 / 過度伸展」通常有兩種來源：

1. **投影後再硬縮放**：現在已改回由上游處理；auto360Cut 本身不再 fork 這段邏輯
2. **把 HQ equirect MP4 誤當成 dfisheye 來轉**：目前 auto360Cut 會對真正拿來 trim 的來源重新偵測 projection，避免直接沿用 LRV index metadata 的投影類型

如果 HQ 檔本身已經是標準 equirect，這點特別重要。

---

## 指令參數

### `autocut`

| 參數 | 說明 |
|------|------|
| `VIDEO` | 要處理的影片路徑 |
| `-p, --prompt` | 描述想選取的片段內容，也會用來選 360 自動視角（預設：`first-person perspective or over-the-shoulder user viewpoint moments`） |
| `-n, --count` | 選取片段數量（預設 3） |
| `-o, --output` | 輸出影片路徑（預設 `autocut_output.mp4`） |
| `--backend` | 選擇 backend：`local-api`（預設）、`local`、`qwen-cloud`、`gemini` |
| `--model` | 指定 `local-api` 或 `local` 的模型名稱 |
| `--hq-source` | 高畫質來源檔案（直接指定；優先於原始 VIDEO） |
| `--hq-dir` | 高畫質來源目錄（自動依 timestamp 對應 LRV → VID；優先於原始 VIDEO） |
| `--360 / --no-360` | 強制開啟/關閉 360 模式（預設自動偵測） |
| `--view` | 最終輸出視角：`auto`（預設）、`front`、`right`、`back`、`left` |
| `--yaw` | 最終輸出角度，優先權高於 `--view` |
| `--force-reindex` | 重新索引此影片 |
| `--verbose` | 顯示詳細日誌 |

### `upstream`（透傳到原生 sentrysearch CLI）

```bash
./.venv/bin/python autocut.py upstream index <path> --backend local-api
./.venv/bin/python autocut.py upstream report --backend local-api
./.venv/bin/python autocut.py upstream search --query "..." --backend local-api
```

---

## 高畫質輸出工作流程

目前 pipeline 建議採用 **proxy 索引、HQ 輸出**：索引時使用低解析度代理檔（LRV 或自行轉出的 proxy MP4）加快分析；最後剪輯與投影轉換則改從高畫質 360 MP4 來源輸出。

如果原始素材是 Insta360 `INSV`，最穩定的流程是：

1. 先用 **Insta360 Studio** 把 `INSV` 匯出成高畫質 **equirectangular / 360 MP4**，作為 HQ master。
2. 從這支 HQ MP4 另外產生一支低解析度 proxy MP4（例如 960px 高、5fps）。
3. 用 proxy MP4 建索引與選片。
4. 透過 `--hq-source` 或 `--hq-dir` 指向 HQ master，讓最終輸出使用高畫質來源。

> 為什麼不直接索引 HQ？可以，但慢很多、吃儲存與模型處理時間。proxy 只影響搜尋與選片速度；實際輸出仍從 HQ master 裁切，所以畫質不會被 proxy 限制。

### 從 HQ 360 MP4 產生 proxy MP4

假設 Studio 匯出的高畫質檔是：

```bash
./hq/VID_20260415_155421_00_001.mp4
```

可用 ffmpeg 產生低解析度代理檔：

```bash
mkdir -p ./proxy
ffmpeg -i ./hq/VID_20260415_155421_00_001.mp4 \
  -vf "scale=-2:960,fps=5" \
  -c:v libx264 -preset veryfast -crf 28 \
  -pix_fmt yuv420p -an \
  ./proxy/VID_20260415_155421_00_001.proxy.mp4
```

建議：

- `scale=-2:960`：維持原始 2:1 equirectangular 比例，只把高度降到 960px；若機器較慢可改 `720`。
- `fps=5`：索引用低幀率即可，大幅降低處理量。
- `-an`：索引不需要音訊，proxy 可移除音軌。
- proxy 仍必須是 **equirectangular / 360 2:1**，不要輸出成 reframed 平面影片。

### 方式 1：proxy 索引 + 直接指定 HQ 檔案

```bash
./.venv/bin/python autocut.py autocut ./proxy/VID_20260415_155421_00_001.proxy.mp4 \
  --prompt "first-person perspective or over-the-shoulder user viewpoint moments" \
  --count 3 \
  --hq-source ./hq/VID_20260415_155421_00_001.mp4 \
  -o ~/Desktop/output_hq.mp4
```

這是最明確、最不容易配錯檔案的方式：`VIDEO` 參數負責索引與搜尋，`--hq-source` 負責最終裁切輸出。

### 方式 2：proxy 索引 + `--hq-dir` 自動對應

若 proxy 檔名保留同一組 timestamp / 序號，也可以把 HQ master 放在同一個目錄或指定的 HQ 目錄，讓 autocut 自動尋找：

```bash
./.venv/bin/python autocut.py autocut ./proxy/VID_20260415_155421_00_001.proxy.mp4 \
  --prompt "first-person perspective or over-the-shoulder user viewpoint moments" \
  --count 3 \
  --hq-dir ./hq \
  -o ~/Desktop/output_hq.mp4
```

若自動配對失敗，改用 `--hq-source` 直接指定 HQ master。

### 舊流程：LRV 索引 + HQ 輸出

若相機已提供 `.lrv`，也可沿用 **LRV 直接索引、HQ 輸出**：

#### 方式 A：直接指定 HQ 檔案

```bash
./.venv/bin/python autocut.py autocut LRV_20260415_155421_01_001.lrv \
  --prompt "first-person perspective or over-the-shoulder user viewpoint moments" \
  --count 3 \
  --hq-source VID_20260415_155421_00_001.mp4 \
  -o ~/Desktop/output_hq.mp4
```

#### 方式 B：自動對應目錄

```bash
./.venv/bin/python autocut.py autocut LRV_20260415_155421_01_001.lrv \
  --prompt "first-person perspective or over-the-shoulder user viewpoint moments" \
  --count 3 \
  --hq-dir ./chain_trip/ \
  -o ~/Desktop/output_hq.mp4
```

自動對應邏輯：
```
LRV_20260415_155421_01_001.lrv
  → 擷取 timestamp: 20260415_155421, seq: 001
  → 搜尋 VID_20260415_155421_00_001.mp4
```

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
./.venv/bin/python autocut.py autocut LRV_20260415_155421_01_001.lrv \
  --prompt "first-person perspective or over-the-shoulder user viewpoint moments" \
  --hq-dir ./exports \
  -o output.mp4
```

注意：

- **不要輸出成一般 reframed 平面影片**，否則 autocut 就不能再替你重新選最佳視角
- **不要只保留 INSV 不匯出**，因為 INSV 原始檔無法直接當作 HQ 輸入
- 若匯出後的 MP4 不是 2:1 畫面，通常代表你輸出的不是 360 equirectangular 版本

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

## 已知限制

- **left 方向**（yaw=270）在某些 dfisheye 檔案可能提取失敗（視野邊界問題，Insta360 鏡頭縫合不完全）
- 雙魚眼需要設定 `ih_fov=200` / `iv_fov=200` 才能涵蓋完整 360 視野
- INSV 原始檔（未拼接的雙鏡頭 raw）無法直接處理，需先透過 Insta360 Studio 匯出成 mp4
- 每 30 秒 chunk 約需 3-5 秒的 caption + embedding 時間（取決於 API 回應速度）
