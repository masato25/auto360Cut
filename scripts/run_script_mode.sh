#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -x .venv/bin/python ]; then
  echo "找不到 .venv。請先執行：bash scripts/install.sh" >&2
  exit 1
fi

if [ "$#" -eq 0 ]; then
  cat >&2 <<'USAGE'
用法：
  ./scripts/run_script_mode.sh <影片1> [影片2 ...] -o output.mp4 [其他 autocut_script.py create 參數]

範例：
  ./scripts/run_script_mode.sh ./videos/LRV_001.lrv --auto-prompt --output-layout portrait -o ./output.mp4
USAGE
  exit 2
fi

exec .venv/bin/python autocut_script.py create "$@"
