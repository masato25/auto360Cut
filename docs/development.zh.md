# autoCut 開發說明

這份文件只記錄開發相關資訊。

如果你只是想知道這個專案是做什麼、怎麼使用，請看根目錄的 [`README.md`](../README.md)。

## 專案結構

```text
autoCut/
├─ autocut.py              # 主專案入口，放 autoCut 自己的 CLI 與客製工作流
├─ docs/
│  ├─ 360-video-guide.zh.md
│  └─ development.zh.md
├─ sentrysearch/           # 上游 submodule
└─ README.md               # 使用者導向說明
```

## 開發原則

### 1. README 以使用者為主

根目錄 `README.md` 應該優先回答：
- 這個專案是什麼
- 典型使用情境
- 安裝方式
- 如何使用
- 有哪些主要文件可看

開發細節、內部架構、submodule 維護原則，不應持續膨脹到 README。

### 2. sentrysearch 盡量貼近上游

`./sentrysearch` 是上游 submodule。

原則上：
- 能不改就不改
- 若必須修改，盡量做最小改動
- autoCut 專案自己的工作流、參數、包裝入口，優先放在根目錄 `autocut.py`
- 若某功能明顯屬於本專案客製需求，應避免把大量邏輯直接灌進 submodule

### 3. autoCut 的客製功能集中在主入口

以下類型的功能，優先放在 `autocut.py` 或本 repo 自己的文件／包裝層：
- 360 工作流整合
- HQ / LRV 對應策略
- 額外 CLI 參數
- 視角覆寫策略
- reindex / 快取控制
- upstream CLI 轉呼叫

## 目前工作流概念

### LRV 與 HQ 分工

- **LRV**：用於索引、caption、語意搜尋、片段選取
- **HQ MP4**：用於最後裁切與輸出
- **INSV**：保留原始素材，需要時先透過 Insta360 Studio 匯出成適合處理的 HQ MP4

### 360 影片處理重點

1. 分析時可從代理檔快速抽樣
2. 最終輸出時再對 HQ 來源做 viewport 轉換
3. 若來源投影格式不同，轉換參數必須分清楚
4. 已索引的視角 metadata 可能被快取，改規則後需要 reindex

## 文件分工

### `README.md`
放：
- 專案介紹
- 安裝
- 使用方式
- 基本參數
- 文件索引

### `docs/360-video-guide.zh.md`
放：
- 360 影片處理知識
- 投影格式說明
- AI / ffmpeg / server 工作流
- 進階操作與疑難排解

### `docs/development.zh.md`
放：
- 開發規則
- 專案結構
- submodule 維護原則
- 設計決策與客製邊界

## 開發注意事項

### Python / 執行環境

目前建議使用專案自己的虛擬環境執行：

```bash
cd /Users/geassbot/Movies/autoCut
source .venv/bin/activate
```

若要跑主入口：

```bash
./.venv/bin/python autocut.py --help
```

若要直接測 submodule：

```bash
cd sentrysearch
./.venv/bin/python -m sentrysearch.cli --help
```

### 修改文件時的原則

- 使用者第一眼看到的是 `README.md`
- 因此 README 應保持短、清楚、可快速上手
- 太多開發背景、架構實作細節、內部規則，應移到開發文件

### 修改 submodule 時

如果必須修改 `sentrysearch/`：
- 先確認是否真的不能在 wrapper 層處理
- 修改時盡量維持最小差異
- 文件中應清楚標示哪些是上游、哪些是本專案額外行為
