#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -x .venv/bin/python ]; then
  echo "找不到 .venv。請先執行：bash scripts/install.sh" >&2
  exit 1
fi

exec .venv/bin/python autocut_gui.py "$@"
