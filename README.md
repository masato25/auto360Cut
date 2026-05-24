# autoCut

autoCut 是一個用來把 360 / 一般影片做「語意搜尋」與「自動剪輯」的本地工作流專案。

它以 [`sentrysearch`](./sentrysearch/) 為核心，補上更適合 360 相機素材的使用方式：

- 用 **LRV 低解析代理檔**做 AI 分析與索引
- 用 **HQ 高畫質 MP4** 做最後輸出
- 支援 **360 視角挑選** 與 **自動平面化輸出**
- 適合 Insta360 這類會同時產生 `.lrv`、`.insv`、匯出 `.mp4` 的工作流

> 簡單說：先讓 AI 看得快，再讓成品輸出得好。

## 這個專案是什麼

autoCut 提供一個偏實用的影片處理流程：

1. 先用較小的代理檔建立索引
2. 用文字描述找出你想要的片段
3. 對 360 影片挑選合適觀看方向
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
├─ .lrv    → 給 autoCut 做索引、caption、語意搜尋、視角判定
└─ HQ .mp4 → 給 autoCut 做最終裁切與輸出

使用流程
1. 準備 LRV 與 HQ MP4
2. 用文字 prompt 找片段
3. autoCut 決定要保留哪些 clip
4. 若為 360 影片，轉成指定/自動視角的平面畫面
5. 拼接輸出成最終影片
```

## 安裝

```bash
cd /Users/geassbot/Movies/autoCut
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install click python-dotenv
python -m pip install -e "./sentrysearch[local-api]"
```

安裝完成後可先確認：

```bash
./.venv/bin/python autocut.py --help
./.venv/bin/python autocut.py autocut --help
```

## 基本使用

### 1. 直接對 LRV 做自動剪輯

```bash
./.venv/bin/python autocut.py autocut ./chain_trip/LRV_20260415_155421_01_001.lrv \
  --prompt "first-person perspective or over-the-shoulder user viewpoint moments" \
  --count 3 \
  --api-base-url http://192.168.0.207:8080 \
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
  --api-base-url http://192.168.0.207:8080 \
  -o ./autocut_hq.mp4
```

建議做法：
- **LRV 負責 AI 分析**
- **HQ MP4 負責最後成品輸出**

## 360 影片建議流程

如果你的來源是 Insta360：

1. 拍攝後會拿到原始 `.insv`
2. 相機也會產生 `.lrv` 代理檔
3. 先用 `.lrv` 給 autoCut 做分析
4. 用 Insta360 Studio 把需要的原始 360 影片匯出成高畫質 equirectangular `.mp4`
5. 再用 `--hq-dir` 或 `--hq-source` 讓 autoCut 從 HQ 檔輸出成品

## 常用參數

### `--prompt`
控制「你想找什麼片段」。

例如：
- `interesting and highlight moments`
- `first-person perspective or over-the-shoulder user viewpoint moments`
- `people interacting closely with the camera wearer`

### `--hq-dir`
指定高畫質輸出來源資料夾，讓 autoCut 自動對應 LRV 與 HQ MP4。

### `--hq-source`
直接指定某一個高畫質來源檔案。

### `--view`
強制最後輸出時採用固定視角。

可選值：
- `auto`
- `front`
- `right`
- `back`
- `left`

### `--yaw`
直接指定最後輸出使用的 yaw 角度；若有設定，優先權高於 `--view`。

## 文件

- 使用指南：[`docs/360-video-guide.zh.md`](./docs/360-video-guide.zh.md)
- 上游專案：[`sentrysearch/README.md`](./sentrysearch/README.md)
- 開發說明：[`docs/development.zh.md`](./docs/development.zh.md)

## 注意事項

- `.insv` 通常不是直接拿來做最終平面輸出的主要來源，建議先經過 Insta360 Studio 匯出
- 如果你改的是「360 視角判定策略」，可能需要重建索引後結果才會更新
- 若要得到較好的輸出品質，請盡量使用 HQ MP4，而不是直接拿 LRV 當成成品來源
