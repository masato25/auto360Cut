# Development Guide

## sentrysearch 維護原則

本專案內的 `sentrysearch/` 是本地獨立 fork，主要用來支援 `auto360Cut` 的影片分析與搜尋流程。

為了降低與上游同步時的衝突、減少不必要的維護成本，請遵守以下原則：

- **只有在需要變更程式碼時，才更新 `sentrysearch/` 內的內容。**
- 如果只是調整專案文件、範例、腳本、設定、README 或 `auto360Cut` 外層流程，且不需要修改 `sentrysearch` 的程式行為，請不要改動 `sentrysearch/`。
- 若功能需求可以在外層 wrapper、CLI、設定檔或呼叫方式完成，優先在外層處理，不要直接修改 `sentrysearch/`。
- 只有在 `sentrysearch` 本身的 bug、API、依賴、模型整合或核心邏輯確實需要修改時，才變更 `sentrysearch/`。
- 修改 `sentrysearch/` 時，請在 commit 或 PR 說明中清楚記錄：
  - 為什麼必須修改 `sentrysearch/`
  - 修改了哪些行為
  - 是否可能影響與上游 fork 的同步

簡單判斷方式：

> 沒有需要改 `sentrysearch` 的程式碼，就不要更新 `sentrysearch/`。
