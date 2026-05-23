# autoCut

基於 [sentrysearch](https://github.com/ssrajadh/sentrysearch) 的本地 AI 影片處理工具。


## 快速開始

```bash
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -e "sentrysearch[local-api]"
```

## 使用範例

```bash
# 索引 360 影片
sentrysearch index ./chain_trip/LRV_20260415_155421_01_001.lrv \
  --backend local-api --verbose

# 自動剪輯
sentrysearch autocut ./chain_trip/LRV_20260415_155421_01_001.lrv \
  --prompt "interesting moments" --count 3 \
  --api-base-url http://192.168.0.207:8080 \
  -o ~/Desktop/output.mp4
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
