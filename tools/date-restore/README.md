# 日期還原工具

從影片 / 圖片的嵌入式 metadata 或檔名推測建立日期，並將日期附加到檔名。

## 支援來源

優先順序：

1. JPEG EXIF `DateTimeOriginal` / `DateTimeDigitized` / `DateTime`
2. 影片 metadata：`ffprobe` 讀取 `creation_time` 等欄位
3. 檔名日期格式（例如 `VID_YYYYMMDD_HHMMSS`）
4. 檔案 birth time（macOS）或修改時間

## 使用方式

### 桌面 GUI

```bash
cd tools/date-restore
python3 main.py
```

### CLI

```bash
cd tools/date-restore
python3 date_restore.py <file_or_directory> [--dry-run] [--recursive] [--force]
```

範例：

```bash
# 先預覽，不實際改名
python3 date_restore.py ~/Movies/*.mp4 --dry-run

# 處理整個資料夾與子資料夾
python3 date_restore.py ~/Pictures --recursive

# 已有日期尾綴也重新處理
python3 date_restore.py ./media --force
```

## 參數

- `--dry-run`, `-n`：僅預覽，不實際改名
- `--recursive`, `-r`：遞迴處理資料夾
- `--force`, `-f`：即使檔名已有日期尾綴也處理

## 需求

- Python 3
- 建議安裝 FFmpeg / ffprobe（影片 metadata 需要）：
  - macOS: `brew install ffmpeg`
  - Ubuntu: `sudo apt install ffmpeg`
