# 360 Video Converter

桌面 GUI 影片轉換工具 — 將 **Insta360 INCV** 及 **360° MP4** 轉換為多種特效風格。

## 功能特色

| 輸入格式 | 輸出風格 | 說明 |
|---------|---------|------|
| `.insv` (Insta360) | **雙魚眼 Dual Fisheye** | Insta360 原生雙魚眼左右分格畫面 |
| 360° `.mp4` (等距柱狀投影) | **六宮格 Cubemap 3×2** | 360 影片展開為立方體六面圖 |
| 360° `.mp4` | **魚眼 Fisheye** | 模擬魚眼鏡頭效果 |
| 360° `.mp4` | **小行星 Tiny Planet** | 360 全景轉為小行星視角 |

## 快速開始

### 1. 安裝依賴

```bash
cd tools/360-converter
# tkinter 為 Python 內建，無需額外安裝
```

**需要 FFmpeg**（已安裝請確認 `ffmpeg -version` 可用）
- macOS: `brew install ffmpeg`
- Ubuntu: `sudo apt install ffmpeg`
- Windows: 從 [ffmpeg.org](https://ffmpeg.org/) 下載

### 2. 啟動桌面應用

```bash
python3 main.py
```

直接開啟桌面視窗，無需瀏覽器。

### 3. 使用 CLI（可選）

```bash
# 查看可用輸出
python3 converter.py input.insv --list-styles
python3 converter.py input.mp4 --list-styles

# 轉換
python3 converter.py input.insv dual_fisheye -o ./output -q high
python3 converter.py input.mp4 cubemap -o ./output
python3 converter.py input.mp4 tiny_planet --size 2048x2048
```

## 專案結構

```
tools/360-converter/
├── main.py              # 桌面 GUI（tkinter）
├── converter.py         # FFmpeg 轉換核心引擎（含 CLI）
├── outputs/             # 轉換結果輸出（自動建立）
└── README.md
```

## 技術細節

- **GUI**: tkinter（Python 內建）
- **影片引擎**: FFmpeg `v360` filter
