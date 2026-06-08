# auto360Cut

![auto360Cut icon](./docs/images/ai360cuticon.png)

[English](./README.md) | 简体中文 | [繁體中文](./README.zh-TW.md)

auto360Cut 是一个本地视频剪辑工作流：用 AI 先理解视频内容，再根据 prompt 或自动脚本输出剪辑成品。它特别适合 Insta360 / 360 相机素材，也可以处理普通 MP4。

核心思路：**用 LRV/低分辨率文件快速分析，用 HQ MP4 输出高画质成品。**

## 界面 Demo

![auto360Cut 界面 Demo 1](./docs/images/demopg1.png)

![auto360Cut 界面 Demo 2](./docs/images/demopg2.png)

## 主要功能

- 语义搜索视频片段：用文字描述找出想要的画面。
- 自动剪辑：选择片段、拼接并输出 MP4。
- 脚本模式：把多支视频交给 LLM 规划剪辑脚本。
- 360 视角选择：根据 prompt 自动选择 front/right/back/left 等方向并平面化输出。
- HQ 输出：LRV 负责 AI 分析，Studio 导出的 HQ MP4 负责最终成品。
- GUI：普通用户可以用图形界面操作。
- 可选人脸排序、背景音乐、片头片尾字幕卡、输出增强。

## 快速开始

```bash
# 1. 安装
bash scripts/install.sh

# 2. 编辑 .env，填入你的 AI endpoint/model/key
cp .env.example .env  # install.sh 已创建时可跳过

# 3. 检查环境
./scripts/check_setup.sh

# 4. 打开 GUI（推荐）
./scripts/run_gui.sh
```

更完整步骤请看：[`docs/quickstart.zh.md`](./docs/quickstart.zh.md)。

## AI 后端设置

编辑 `.env`。最推荐使用 local-api，也就是本机或局域网内的 OpenAI-compatible VLM server：

```env
AUTOCUT_BACKEND=local-api
LOCAL_API_BASE=http://127.0.0.1:8080
LOCAL_API_MODEL=你的-VLM-model

AUTOCUT_SCRIPT_API_BASE=http://127.0.0.1:8080/v1
AUTOCUT_SCRIPT_API_KEY=not-needed
AUTOCUT_SCRIPT_API_MODEL=你的-文本-LLM-model
```

也支持 Gemini / Qwen Cloud / DeepSeek（脚本 LLM）。示例都在 [`.env.example`](./.env.example)。

## 推荐使用方式：GUI

```bash
./scripts/run_gui.sh
```

GUI 可用来选择视频、prompt、HQ 来源、人脸照片、输出设置等。若 tkinter 未安装，macOS Homebrew Python 可用：

```bash
brew install python-tk@3.12
```

请把 `3.12` 换成你的 Python 版本。

## 脚本 / 一键剪辑模式

多素材剪成一支视频：

```bash
./scripts/run_script_mode.sh ./videos/LRV_001.lrv ./videos/LRV_002.lrv \
  --auto-prompt \
  --output-layout portrait \
  -o ./output.mp4
```

自己指定剪辑方向：

```bash
./scripts/run_script_mode.sh ./videos/LRV_001.lrv \
  -p "剪成一支节奏快、适合社交平台短视频的旅行精华" \
  --output-layout portrait \
  --enhance vivid \
  -o ./travel_short.mp4
```

## 单支视频 CLI

```bash
.venv/bin/python autocut.py autocut ./videos/LRV_001.lrv \
  --prompt "first-person perspective, exciting travel moments" \
  --count 3 \
  -o ./preview.mp4
```

使用 HQ MP4 做最终输出：

```bash
.venv/bin/python autocut.py autocut ./videos/LRV_001.lrv \
  --hq-dir ./hq \
  --prompt "first-person perspective, exciting travel moments" \
  --count 3 \
  -o ./final_hq.mp4
```

## Insta360 / 360 素材流程

```text
相机素材
├─ .lrv    → 给 auto360Cut 做索引、caption、语义搜索、视角判断
├─ .insv   → 保留原始文件，需要时用 Insta360 Studio 导出
└─ HQ .mp4 → 给 auto360Cut 做最后裁切与输出
```

建议流程：

1. 用 `.lrv` 当输入，让 AI 快速分析。
2. 用 Insta360 Studio 从 `.insv` 导出高画质 equirectangular MP4。
3. 在 GUI 或 CLI 指定 HQ 来源文件夹。
4. auto360Cut 会从 HQ MP4 生成成品。

## 可选功能

### 人脸识别

```bash
.venv/bin/python -m pip install -e "./sentrysearch[face]"
```

使用时加 `--face ref.jpg`，搜索结果会优先排序包含该人物的片段。

### 输出增强

```bash
.venv/bin/python autocut.py autocut ./videos/LRV_001.lrv \
  --prompt "best travel highlights" \
  --enhance vivid \
  -o ./enhanced.mp4
```

可用 preset：`none`、`light`、`vivid`、`cinematic`。

## 文档

- 快速开始：[`docs/quickstart.zh.md`](./docs/quickstart.zh.md)
- 360 使用指南：[`docs/360-video-guide.zh.md`](./docs/360-video-guide.zh.md)
- 开发说明：[`docs/development.zh.md`](./docs/development.zh.md)
- `sentrysearch` fork：[`sentrysearch/README.md`](./sentrysearch/README.md)

## 常见问题

### `Symbol not found: _XML_SetAllocTrackerActivationThreshold`

macOS Homebrew Python 3.14 可能加载到系统旧版 expat。优先使用：

```bash
bash scripts/install.sh
```

安装脚本会自动处理。若要手动处理，请安装 Homebrew expat 并在创建 venv 时设置 `DYLD_LIBRARY_PATH`。

### `externally-managed-environment`

不要把软件包装进系统 Python。请使用本项目 `.venv`：

```bash
bash scripts/install.sh
```

### local-api 连不上

确认 AI server 已启动，且 `.env` 使用 client 可以连到的地址。server 监听可用 `0.0.0.0`，但 `.env` 建议填：

```env
LOCAL_API_BASE=http://127.0.0.1:8080
```

或填实际局域网 IP。
