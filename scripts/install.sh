#!/bin/bash
set -euo pipefail

REQUIRED_MAJOR=3
MIN_REQUIRED_MINOR=11
MAX_REQUIRED_MINOR=14

VENV_DIR=".venv"

# --- helpers ---
info()  { printf "\033[36m%s\033[0m\n" "$*"; }
ok()    { printf "\033[32m✓ %s\033[0m\n" "$*"; }
warn()  { printf "\033[33m! %s\033[0m\n" "$*"; }
err()   { printf "\033[31m✗ %s\033[0m\n" "$*" >&2; }
step()  { printf "\n\033[1;34m▶ %s\033[0m\n" "$*"; }

cleanup() {
  if [ -n "${TMP_PYTHON:-}" ] && [ -f "$TMP_PYTHON" ]; then
    rm -f "$TMP_PYTHON"
  fi
}
trap cleanup EXIT

# --- 1. check python version ---
step "Checking Python version"

if ! command -v python3 &>/dev/null; then
  err "python3 not found. Install Python $REQUIRED_MAJOR.$MIN_REQUIRED_MINOR or later."
  exit 1
fi

PYTHON=$(command -v python3)
RAW_VERSION=$("$PYTHON" --version 2>&1 | awk '{print $2}')
MAJOR=$(echo "$RAW_VERSION" | cut -d. -f1)
MINOR=$(echo "$RAW_VERSION" | cut -d. -f2)
FULL="$MAJOR.$MINOR"

if [ "$MAJOR" -ne "$REQUIRED_MAJOR" ] || [ "$MINOR" -lt "$MIN_REQUIRED_MINOR" ] || [ "$MINOR" -gt "$MAX_REQUIRED_MINOR" ]; then
  err "Python $FULL is not supported. Need $REQUIRED_MAJOR.$MIN_REQUIRED_MINOR – $REQUIRED_MAJOR.$MAX_REQUIRED_MINOR"
  info "  Install a compatible Python:"
  info "    brew install python@3.12"
  exit 1
fi

ok "Python $FULL at $PYTHON"

# --- 2. check pyexpat (macOS + Python 3.14 workaround) ---
EXPAT_FIX=0
if [ "$MINOR" -ge 14 ]; then
  step "Checking libexpat compatibility (Python 3.14+)"
  if ! DYLD_LIBRARY_PATH="" "$PYTHON" -c "from xml.parsers import expat" 2>/dev/null; then
    warn "pyexpat failed: Python 3.14 needs a newer libexpat than macOS provides."
    info "  Attempting automatic fix..."

    if command -v brew &>/dev/null; then
      if [ ! -f /opt/homebrew/Cellar/expat/2.8.1/lib/libexpat.1.dylib ]; then
        info "  Installing expat via Homebrew..."
        brew install expat
      fi
      EXPAT_LIB="/opt/homebrew/Cellar/expat/2.8.1/lib"
      if [ -f "$EXPAT_LIB/libexpat.1.dylib" ]; then
        ok "expat found at $EXPAT_LIB"
        EXPAT_FIX=1
      else
        EXPAT_LIB=$(ls -d /opt/homebrew/Cellar/expat/*/lib 2>/dev/null | head -1)
        if [ -n "$EXPAT_LIB" ] && [ -f "$EXPAT_LIB/libexpat.1.dylib" ]; then
          ok "expat found at $EXPAT_LIB"
          EXPAT_FIX=1
        fi
      fi
    fi

    if [ "$EXPAT_FIX" -eq 0 ]; then
      err "Could not fix pyexpat automatically."
      info "  Install expat manually: brew install expat"
      info "  Then re-run this script."
      exit 1
    fi
  else
    ok "pyexpat works"
  fi
fi

# --- 3. create venv ---
step "Creating virtual environment"

if [ -d "$VENV_DIR" ]; then
  warn "Removing existing $VENV_DIR"
  rm -rf "$VENV_DIR"
fi

if [ "$EXPAT_FIX" -eq 1 ]; then
  DYLD_LIBRARY_PATH="$EXPAT_LIB" "$PYTHON" -m venv "$VENV_DIR"
  # Create wrapper so expat fix is always active
  mv "$VENV_DIR/bin/python" "$VENV_DIR/bin/python.real"
  cat > "$VENV_DIR/bin/python" << WRAPPER
#!/bin/bash
export DYLD_LIBRARY_PATH=$EXPAT_LIB
exec "\${BASH_SOURCE[0]}.real" "\$@"
WRAPPER
  chmod +x "$VENV_DIR/bin/python"

  # also wrap python3 symlink if it exists
  if [ -L "$VENV_DIR/bin/python3" ]; then
    rm -f "$VENV_DIR/bin/python3"
    ln -s python "$VENV_DIR/bin/python3"
  fi
else
  "$PYTHON" -m venv "$VENV_DIR"
fi

ok "Virtual environment created at $VENV_DIR"
VENV_PYTHON="$VENV_DIR/bin/python"

# --- 4. upgrade pip ---
step "Upgrading pip"
$VENV_PYTHON -m pip install --upgrade pip -q --no-cache-dir
ok "pip upgraded"

# --- 5. install dependencies ---
step "Installing dependencies"

PS3="Select backend: "
options=(
  "local-api  (self-hosted llama.cpp / OpenAI-compatible server) [RECOMMENDED]"
  "qwen-cloud (Alibaba DashScope API)"
  "local      (local GPU inference via HuggingFace Transformers)"
  "local-quantized (local with 4-bit quantization, NVIDIA only)"
  "gemini     (Google Gemini API)"
)
select opt in "${options[@]}"; do
  case $REPLY in
    1) BACKEND="local-api"; break;;
    2) BACKEND="qwen-cloud"; break;;
    3) BACKEND="local"; break;;
    4) BACKEND="local-quantized"; break;;
    5) BACKEND="gemini"; break;;
    *) warn "Invalid choice. Select 1-5.";;
  esac
done

info "  Installing requirements (base)..."
  $VENV_PYTHON -m pip install -r requirements.txt -q --no-cache-dir

if [ "$BACKEND" = "gemini" ]; then
  info "  Installing sentrysearch (base only, Gemini backend)..."
  $VENV_PYTHON -m pip install -e ./sentrysearch -q --no-cache-dir
elif [ "$BACKEND" = "local-api" ]; then
  info "  Installing sentrysearch[local-api]..."
  $VENV_PYTHON -m pip install -r requirements-local-api.txt -q --no-cache-dir
elif [ "$BACKEND" = "qwen-cloud" ]; then
  info "  Installing sentrysearch[qwen-cloud]..."
  $VENV_PYTHON -m pip install -r requirements-qwen-cloud.txt -q --no-cache-dir
elif [ "$BACKEND" = "local" ] || [ "$BACKEND" = "local-quantized" ]; then
  EXTRA="$BACKEND"
  [ "$BACKEND" = "local-quantized" ] && EXTRA="local-quantized"
  info "  Installing sentrysearch[$EXTRA]..."
  $VENV_PYTHON -m pip install -e "./sentrysearch[$EXTRA]" -q --no-cache-dir
fi

ok "Dependencies installed"

# --- 6. .env ---
step "Environment configuration"

if [ ! -f .env ]; then
  cp .env.example .env
  ok "Created .env from .env.example — edit it with your settings."
else
  ok ".env already exists"
fi

# --- 7. verify ---
step "Verifying installation"

if $VENV_PYTHON -c "from sentrysearch.cli import cli; print('sentrysearch OK')" 2>/dev/null; then
  ok "sentrysearch imports correctly"
else
  err "sentrysearch import failed"
  exit 1
fi

# --- done ---
printf "\n\033[1;32m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m\n"
printf "\033[1;32m  ✓ Installation complete!\033[0m\n"
printf "\033[1;32m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m\n"
printf "\n"
printf "  Run autoCut:\n"
printf "    %s autocut.py <video> --prompt \"...\" -o output.mp4\n" "$VENV_PYTHON"
printf "\n"
printf "  Edit your .env file to configure API endpoints.\n"
printf "\n"
