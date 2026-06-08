# auto360Cut

![auto360Cut icon](./docs/images/ai360cuticon.png)

English | [简体中文](./README.zh-CN.md) | [繁體中文](./README.zh-TW.md)

auto360Cut is a local video-editing workflow that uses AI to understand video content first, then exports edited results from a prompt or an automatically generated script. It is especially useful for Insta360 / 360 camera footage, and it also works with regular MP4 videos.

Core idea: **analyze quickly with LRV/low-resolution files, then render high-quality results from HQ MP4 files.**

## Interface demo

![auto360Cut interface demo 1](./docs/images/demopg1.png)

![auto360Cut interface demo 2](./docs/images/demopg2.png)

## Key features

- Semantic video segment search: find the shots you want with text descriptions.
- Automatic editing: select segments, concatenate them, and export MP4 files.
- Script mode: let an LLM plan an edit across multiple videos.
- 360 view selection: automatically choose directions such as front/right/back/left based on the prompt, then flatten the output.
- HQ output: LRV files are used for AI analysis, while HQ MP4 files exported from Studio are used for the final result.
- GUI: operate the workflow from a graphical interface.
- Optional face-based ranking, background music, intro/outro title cards, and output enhancement.

## Quick start

```bash
# 1. Install
bash scripts/install.sh

# 2. Edit .env and fill in your AI endpoint/model/key
cp .env.example .env  # Skip this if install.sh already created it

# 3. Check the environment
./scripts/check_setup.sh

# 4. Open the GUI (recommended)
./scripts/run_gui.sh
```

For more complete steps, see [`docs/quickstart.zh.md`](./docs/quickstart.zh.md).

## AI backend setup

Edit `.env`. The recommended backend is local-api, meaning an OpenAI-compatible VLM server running locally or on your LAN:

```env
AUTOCUT_BACKEND=local-api
LOCAL_API_BASE=http://127.0.0.1:8080
LOCAL_API_MODEL=your-VLM-model

AUTOCUT_SCRIPT_API_BASE=http://127.0.0.1:8080/v1
AUTOCUT_SCRIPT_API_KEY=not-needed
AUTOCUT_SCRIPT_API_MODEL=your-text-LLM-model
```

Gemini / Qwen Cloud / DeepSeek (for script LLM) are also supported. Examples are available in [`.env.example`](./.env.example).

## Recommended usage: GUI

```bash
./scripts/run_gui.sh
```

The GUI lets you choose videos, prompts, HQ sources, face reference photos, output settings, and more. If tkinter is not installed, macOS Homebrew Python users can run:

```bash
brew install python-tk@3.12
```

Replace `3.12` with your Python version.

## Script / one-click editing mode

Edit multiple source videos into one video:

```bash
./scripts/run_script_mode.sh ./videos/LRV_001.lrv ./videos/LRV_002.lrv \
  --auto-prompt \
  --output-layout portrait \
  -o ./output.mp4
```

Specify your own editing direction:

```bash
./scripts/run_script_mode.sh ./videos/LRV_001.lrv \
  -p "Create a fast-paced travel highlight video suitable for social short-form video" \
  --output-layout portrait \
  --enhance vivid \
  -o ./travel_short.mp4
```

## Single-video CLI

```bash
.venv/bin/python autocut.py autocut ./videos/LRV_001.lrv \
  --prompt "first-person perspective, exciting travel moments" \
  --count 3 \
  -o ./preview.mp4
```

Use HQ MP4 for the final output:

```bash
.venv/bin/python autocut.py autocut ./videos/LRV_001.lrv \
  --hq-dir ./hq \
  --prompt "first-person perspective, exciting travel moments" \
  --count 3 \
  -o ./final_hq.mp4
```

## Insta360 / 360 footage workflow

```text
Camera footage
├─ .lrv    → used by auto360Cut for indexing, captions, semantic search, and view selection
├─ .insv   → keep as the original file; export with Insta360 Studio when needed
└─ HQ .mp4 → used by auto360Cut for final cropping and rendering
```

Recommended workflow:

1. Use `.lrv` as the input so AI analysis is fast.
2. Export a high-quality equirectangular MP4 from `.insv` with Insta360 Studio.
3. Specify the HQ source folder in the GUI or CLI.
4. auto360Cut generates the final video from the HQ MP4.

## Optional features

### Face recognition

```bash
.venv/bin/python -m pip install -e "./sentrysearch[face]"
```

Add `--face ref.jpg` when using it. Search results will prioritize segments that contain that person.

### Output enhancement

```bash
.venv/bin/python autocut.py autocut ./videos/LRV_001.lrv \
  --prompt "best travel highlights" \
  --enhance vivid \
  -o ./enhanced.mp4
```

Available presets: `none`, `light`, `vivid`, `cinematic`.

## Documentation

- Quick start: [`docs/quickstart.zh.md`](./docs/quickstart.zh.md)
- 360 guide: [`docs/360-video-guide.zh.md`](./docs/360-video-guide.zh.md)
- Development notes: [`docs/development.zh.md`](./docs/development.zh.md)
- `sentrysearch` fork: [`sentrysearch/README.md`](./sentrysearch/README.md)

## FAQ

### `Symbol not found: _XML_SetAllocTrackerActivationThreshold`

macOS Homebrew Python 3.14 may load the older system expat library. Prefer using:

```bash
bash scripts/install.sh
```

The install script handles this automatically. To handle it manually, install Homebrew expat and set `DYLD_LIBRARY_PATH` when creating the venv.

### `externally-managed-environment`

Do not install packages into the system Python. Use this project's `.venv`:

```bash
bash scripts/install.sh
```

### local-api cannot connect

Make sure the AI server is running and that `.env` uses an address the client can reach. The server can listen on `0.0.0.0`, but `.env` should usually use:

```env
LOCAL_API_BASE=http://127.0.0.1:8080
```

Or use the actual LAN IP address.
