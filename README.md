# autoCut

基於 [sentrysearch](https://github.com/ssrajadh/sentrysearch) 的本地 AI 影片處理工具。

## 系統架構

```
MacBook (Intel, 16GB RAM)          遠端 GPU 伺服器 (192.168.0.207:8080)
┌────────────────────────┐         ┌──────────────────────────────┐
│ sentrysearch CLI       │         │ llama.cpp llama-server       │
│                        │  HTTP   │                              │
│ ffmpeg → 拆幀 / 轉檔   │ ◄─────► │ Qwen2.5-VL-7B-Q4_K_M.gguf   │
│ fastembed → 文字嵌入   │         │ mmproj (視覺投影)            │
│ ChromaDB → 向量檢索    │         │                              │
└────────────────────────┘         └──────────────────────────────┘
```

- **本地 Mac**：跑 `ffmpeg`、文字嵌入、向量資料庫，不需要 GPU
- **遠端伺服器**：跑 `llama-server` + Qwen2.5-VL-7B，負責看懂圖片

## 快速開始

```bash
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -e "sentrysearch[local-api]"
```

## 使用範例

```bash
# 先確認 API 有回應
curl http://192.168.0.207:8080/v1/models

# 索引 Insta360 LRV（自動偵測 360 / 雙魚眼）
sentrysearch index ./chain_trip/LRV_*.lrv \
  --backend local-api --verbose

# 自動剪輯：選取有趣片段 + 最佳視角輸出
sentrysearch autocut ./chain_trip/LRV_20260415_155421_01_001.lrv \
  --prompt "interesting moments" --count 3 \
  --api-base-url http://192.168.0.207:8080 \
  -o ~/Desktop/output.mp4

# 高畫質輸出：索引用 LRV，修剪用 HQ 來源
sentrysearch autocut ./chain_trip/LRV_20260415_155421_01_001.lrv \
  --prompt "interesting moments" --count 3 \
  --hq-dir ./chain_trip/ \
  --api-base-url http://192.168.0.207:8080 \
  -o ~/Desktop/output_hq.mp4

# 顯示已索引的時間軸
sentrysearch report --backend local-api
```

## 本地 API 設定

```bash
# 透過環境變數設定（建議寫入 .env）
export LOCAL_API_BASE=http://192.168.0.207:8080
```

詳細說明請見 [360 影片處理指南](sentrysearch/docs/360-video-guide.zh.md)。

## 專案結構

```
autoCut/
├── sentrysearch/       # Git submodule
│   ├── docs/           # 手冊
│   └── sentrysearch/   # 主要程式碼
├── chain_trip/         # 原始影片（.lrv .insv .mp4）
└── vio/                # 其他影片
```
