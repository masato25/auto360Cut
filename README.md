# auto360Cut

auto360Cut 是一個用來把 360 / 一般影片做「語意搜尋」與「自動剪輯」的本地工作流專案。

它以 [`sentrysearch`](./sentrysearch/README.md)（forked from [ssrajadh/sentrysearch](https://github.com/ssrajadh/sentrysearch)）為核心，補上更適合 360 相機素材的使用方式：

- 用 **LRV 低解析代理檔**做 AI 分析與索引
- 用 **HQ 高畫質 MP4** 做最後輸出
- 支援 **prompt-aware 360 視角挑選** 與 **自動平面化輸出**
- 適合 Insta360 這類會同時產生 `.lrv`、`.insv`、匯出 `.mp4` 的工作流

> 簡單說：先讓 AI 看得快，再讓成品輸出得好。

## 人臉辨識（選用）

```bash
.venv/bin/python -m pip install face_recognition
```

索引時自動偵測各視角的人臉。搜尋時加 `--face ref.jpg` 就會把有該主角的片段排在前面。

## 圖形介面 (GUI)

```bash
.venv/bin/python autocut_gui.py
```

開啟後即可選擇影片、輸入 prompt、選擇參考臉部照片、一鍵執行剪輯。需先安裝 tkinter：
```bash
brew install python-tk@3.14
```

## 這個專案是什麼

auto360Cut 提供一個偏實用的影片處理流程：

1. 先用較小的代理檔建立索引
2. 用文字描述找出你想要的片段
3. 對 360 影片依照 prompt 挑選合適觀看方向
4. 最後從高畫質來源裁出成品

這讓你不用先手動把長影片全部看完，就能直接用 prompt 找片段，再輸出成精簡影片。

## 典型使用情境

- 從 Insta360 旅遊 / 騎車 / 活動素材中找重點片段
- 從長時間錄影中快速找出「第一人稱視角」或「背後跟拍感」的畫面
- 先拿 LRV 快速分析，再用 Studio 匯出的 HQ MP4 做最終輸出
- 把 360 素材自動轉成一般可觀看的平面影片

## 工作流程

```text
Insta360 原始素材
├─ .insv   → 保留原始 360 檔，必要時用 Insta360 Studio 匯出 HQ MP4
├─ .lrv    → 給 auto360Cut 做索引、caption、語意搜尋、視角判定
└─ HQ .mp4 → 給 auto360Cut 做最終裁切與輸出

使用流程
1. 準備 LRV 與 HQ MP4
2. 用文字 prompt 找片段
3. auto360Cut 決定要保留哪些 clip
4. 若為 360 影片，轉成指定/自動視角的平面畫面
5. 拼接輸出成最終影片
```

## 安裝

### 快速安裝（自動腳本）

```bash
bash scripts/install.sh
```

腳本會自動：
1. 檢查 Python 版本（需 3.11–3.14）
2. 偵測並修復 macOS Python 3.14 的 `libexpat` 問題
3. 建立 virtual environment（`.venv`）
4. 讓你選擇 backend 並安裝對應依賴
5. 從 `.env.example` 建立 `.env`

### 手動安裝

#### 系統需求

- **Python 3.11 – 3.14**
- **ffmpeg**（系統安裝或由 `imageio-ffmpeg` 自動處理）
- **macOS + Python 3.14**：需先安裝 Homebrew expat（見下方疑難排解）

#### 步驟

```bash
# 1. 建立 virtual environment（macOS 3.14 請見下方注意）
python3 -m venv .venv

# 2. 升級 pip
.venv/bin/python -m pip install --upgrade pip

# 3. 安裝依賴（依你的 backend 選擇其一）
.venv/bin/python -m pip install -r requirements-local-api.txt    # local-api（推薦）
# .venv/bin/python -m pip install -r requirements-qwen-cloud.txt # qwen-cloud
# .venv/bin/python -m pip install -e "./sentrysearch[local]"     # local GPU

# 4. 環境設定
cp .env.example .env
# 編輯 .env 填入你的 API 設定
```

#### 安裝確認

```bash
.venv/bin/python autocut.py --help
.venv/bin/python autocut.py autocut --help
```

### macOS Python 3.14 疑難排解（expat）

Homebrew 的 Python 3.14 依賴新版 `libexpat`，但 macOS 系統內建的是舊版，會導致 `pip install` 失敗：

```
ImportError: Symbol not found: _XML_SetAllocTrackerActivationThreshold
```

**解法：**

```bash
# 1. 安裝 Homebrew 的 expat
brew install expat

# 2. 設定環境變數後再操作 Python
export DYLD_LIBRARY_PATH=/opt/homebrew/Cellar/expat/2.8.1/lib

# 3. 建立 venv（必須在有 DYLD_LIBRARY_PATH 的環境下）
python3 -m venv .venv

# 4. [重要] 建立 expat 修復包裝器，以後就不用再設變數
mv .venv/bin/python .venv/bin/python.real
cat > .venv/bin/python << 'WRAPPER'
#!/bin/bash
export DYLD_LIBRARY_PATH=/opt/homebrew/Cellar/expat/2.8.1/lib
exec "${BASH_SOURCE[0]}.real" "$@"
WRAPPER
chmod +x .venv/bin/python
```

之後 `./.venv/bin/python` 會自動載入正確的 expat，不需額外設定。

> 💡 `scripts/install.sh` 會自動處理以上所有步驟。

## 基本使用

### 1. 直接對 LRV 做自動剪輯

```bash
./.venv/bin/python autocut.py autocut ./chain_trip/LRV_20260415_155421_01_001.lrv \
  --prompt "first-person perspective or over-the-shoulder user viewpoint moments" \
  --count 3 \
  -o ./autocut_preview.mp4
```

這個模式適合：
- 先快速測試索引與選片結果
- 先產出 preview
- 還沒決定最後要用哪個 HQ 輸出檔

### 2. 使用 HQ MP4 做最終輸出

```bash
./.venv/bin/python autocut.py autocut ./chain_trip/LRV_20260415_155421_01_001.lrv \
  --hq-dir ./chain_trip_hq \
  --prompt "first-person perspective or over-the-shoulder user viewpoint moments" \
  --count 3 \
  -o ./autocut_hq.mp4
```

建議做法：
- **LRV 負責 AI 分析**
- **HQ MP4 負責最後成品輸出**

### 3. Enhance Mode（輸出增強）

自動剪輯完成後可加一次 preset-based 的 ffmpeg 增強 pass，包含基本色彩/銳化與音量正規化，並會輸出一份可追蹤的 enhancement plan JSON。

```bash
./.venv/bin/python autocut.py autocut ./chain_trip/LRV_20260415_155421_01_001.lrv \
  --hq-dir ./chain_trip_hq \
  --prompt "first-person perspective or over-the-shoulder user viewpoint moments" \
  --count 3 \
  --enhance vivid \
  -o ./autocut_hq_vivid.mp4
```

可用 preset：
- `none`：不做增強（預設）
- `light`：輕微對比、飽和、銳化與 loudness normalize
- `vivid`：較鮮明的旅遊/動態素材風格
- `cinematic`：較深對比、較克制飽和，並加 high-pass 音訊清理

預設 plan 會寫到 `輸出檔.enhance-plan.json`，也可用 `--enhance-plan ./plan.json` 指定位置。

Script Mode 也支援同樣參數：

```bash
./.venv/bin/python autocut_script.py create ./chain_trip/LRV_20260415_155421_01_001.lrv \
  --auto-prompt \
  --output-layout portrait \
  --enhance light \
  -o ./script_output.mp4
```

## 360 影片建議流程

如果你的來源是 Insta360：

1. 拍攝後會拿到原始 `.insv`
2. 相機也會產生 `.lrv` 代理檔
3. 先用 `.lrv` 給 auto360Cut 做分析
4. 用 Insta360 Studio 把需要的原始 360 影片匯出成高畫質 equirectangular `.mp4`
5. 再用 `--hq-dir` 或 `--hq-source` 讓 auto360Cut 從 HQ 檔輸出成品

### 自動視角如何運作

360 索引時，auto360Cut 會先把每個 chunk 轉成四個平面視角：`front`、`right`、`back`、`left`，分別送到 local-api 產生 caption 與 embedding。接著它會把你的 `--prompt` 也轉成 embedding，和四個視角 caption 比對，將最符合 prompt 的方向寫入 metadata：

- `best_direction` / `best_yaw`：後續 `--view auto` 輸出時使用的視角
- `viewport_prompt`：建立此索引時使用的 prompt
- `viewport_captions`：四個視角的 caption 摘要，方便除錯
- `viewport_index_version`：視角索引版本，策略改變時用來判斷是否需要重建

因此同一段 360 影片會依 prompt 自動偏向不同視角；例如找「第一人稱 / 肩後視角」時，會優先選出更像使用者視線或背後跟拍的方向。

如果你改了 prompt 或視角策略，舊索引會被視為過期並自動重建對應 chunk；也可以明確加上 `--force-reindex` 重新產生全部 metadata。

## 常用參數

### `--prompt`
控制「你想找什麼片段」，也會用來決定 360 chunk 的自動視角。不同 prompt 可能讓同一個 chunk 選到不同的 `best_direction`。

例如：
- `interesting and highlight moments`
- `first-person perspective or over-the-shoulder user viewpoint moments`
- `people interacting closely with the camera wearer`

### `--hq-dir`
指定高畫質輸出來源資料夾，讓 auto360Cut 自動對應 LRV 與 HQ MP4。

### `--hq-source`
直接指定某一個高畫質來源檔案。

### `--view`
強制最後輸出時採用固定視角。預設 `auto` 會使用索引階段依 prompt 選出的 `best_direction`。

可選值：
- `auto`
- `front`
- `right`
- `back`
- `left`

### `--enhance`
在最終輸出後套用 preset-based 增強 pass。選項為 `none`、`light`、`vivid`、`cinematic`。啟用時會同時寫出 enhancement plan JSON，方便確認實際使用的 ffmpeg filter 與編碼設定。

### `--yaw`
直接指定最後輸出使用的 yaw 角度；若有設定，優先權高於 `--view`。

## 安裝檔說明

- `requirements.txt`
  - auto360Cut root venv 的基礎安裝需求
  - 包含 pip 常用建置工具與最基本啟動依賴
- `requirements-local-api.txt`
  - 建議使用自架 llama.cpp / llmcpp / OpenAI 相容 HTTP API 的工作流使用
  - 會直接安裝 `./sentrysearch[local-api]`
- `requirements-qwen-cloud.txt`
  - 只有真的要走 qwen-cloud 時才需要
  - 會直接安裝 `./sentrysearch[qwen-cloud]`

## 文件

- 使用指南：[`docs/360-video-guide.zh.md`](./docs/360-video-guide.zh.md)
- fork 上游：[ssrajadh/sentrysearch](https://github.com/ssrajadh/sentrysearch)（本專案內的 `sentrysearch/` 為本地獨立 fork）
- 開發說明：[`docs/development.zh.md`](./docs/development.zh.md)

## 常見問題

### `Symbol not found: _XML_SetAllocTrackerActivationThreshold`

**原因**：macOS 的 Python 3.14（Homebrew）依賴新版 `libexpat`，但系統 `/usr/lib/libexpat.1.dylib` 是舊版。

**解法**：
```bash
brew install expat
export DYLD_LIBRARY_PATH=/opt/homebrew/Cellar/expat/2.8.1/lib
# 之後所有 Python 指令都需要在這個環境變數下執行
# 或用 bash scripts/install.sh 自動處理
```

### `pip install` 出現 `externally-managed-environment`

**原因**：Homebrew Python 不允許 pip 直接安裝系統套件。

**解法**：使用 virtual environment（`.venv`），或在 pip 指令加 `--break-system-packages`。

### `No module named 'encodings'` / `Could not find platform independent libraries`

**原因**：virtual environment 建立時沒有正確設定 `DYLD_LIBRARY_PATH`（macOS 3.14 expat 問題）。

**解法**：砍掉 `.venv`，在 `DYLD_LIBRARY_PATH` 有設定的環境下重新建立：
```bash
rm -rf .venv
export DYLD_LIBRARY_PATH=/opt/homebrew/Cellar/expat/2.8.1/lib
python3 -m venv .venv
```

## 注意事項

- `.insv` 通常不是直接拿來做最終平面輸出的主要來源，建議先經過 Insta360 Studio 匯出
- 如果你改的是「360 視角判定策略」或 `--prompt`，auto360Cut 會重建過期 chunk；必要時也可用 `--force-reindex` 全部重建
- 若要得到較好的輸出品質，請盡量使用 HQ MP4，而不是直接拿 LRV 當成成品來源
