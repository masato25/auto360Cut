#!/usr/bin/env python3
"""Check whether auto360Cut is ready for non-developer use."""

from __future__ import annotations

import importlib.util
import os
import shutil
import socket
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def status(ok: bool, label: str, detail: str = "") -> bool:
    icon = "✓" if ok else "✗"
    print(f"{icon} {label}" + (f" — {detail}" if detail else ""))
    return ok


def warn(label: str, detail: str = "") -> None:
    print(f"! {label}" + (f" — {detail}" if detail else ""))


def can_connect(url: str, timeout: float = 1.5) -> bool:
    parsed = urlparse(url)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if not host:
        return False
    if host == "0.0.0.0":
        host = "127.0.0.1"
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def main() -> int:
    print("auto360Cut setup check\n")
    ok_all = True

    version = sys.version_info
    ok_all &= status(
        version.major == 3 and 11 <= version.minor <= 14,
        "Python version",
        f"{version.major}.{version.minor}.{version.micro} (need 3.11–3.14)",
    )

    in_venv = Path(sys.prefix).resolve() != Path(getattr(sys, "base_prefix", sys.prefix)).resolve()
    ok_all &= status(in_venv, "Virtual environment", sys.prefix)

    ok_all &= status(ENV_FILE.exists(), ".env file", str(ENV_FILE) if ENV_FILE.exists() else "run: cp .env.example .env")
    env = load_env(ENV_FILE)

    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    ok_all &= status(bool(ffmpeg), "ffmpeg", ffmpeg or "install ffmpeg and put it on PATH")
    ok_all &= status(bool(ffprobe), "ffprobe", ffprobe or "usually installed together with ffmpeg")

    required_modules = ["click", "dotenv", "sentrysearch"]
    for module in required_modules:
        ok_all &= status(has_module(module), f"Python package: {module}")

    try:
        import tkinter  # noqa: F401
        status(True, "tkinter GUI support")
    except Exception as exc:  # pragma: no cover - platform specific
        warn("tkinter GUI support", f"GUI may not open ({exc}); CLI still works")

    backend = env.get("AUTOCUT_BACKEND", "local-api")
    print(f"\nConfigured backend: {backend}")
    if backend in {"local-api", "local"}:
        base = env.get("LOCAL_API_BASE", "")
        model = env.get("LOCAL_API_MODEL", "")
        ok_all &= status(bool(base), "LOCAL_API_BASE", base or "set your local VLM server URL")
        ok_all &= status(bool(model), "LOCAL_API_MODEL", model or "set the model served by your local API")
        if base:
            connected = can_connect(base)
            if connected:
                status(True, "Local VLM server reachable", base)
            else:
                warn("Local VLM server not reachable now", f"start it before indexing/searching: {base}")
    elif backend == "gemini":
        key = env.get("GEMINI_API_KEY", "")
        ok_all &= status(bool(key and "your-" not in key), "GEMINI_API_KEY")
    elif backend == "qwen-cloud":
        key = env.get("DASHSCOPE_API_KEY", "")
        ok_all &= status(bool(key and "your-" not in key), "DASHSCOPE_API_KEY")
    else:
        warn("Unknown AUTOCUT_BACKEND", backend)

    script_api = env.get("AUTOCUT_SCRIPT_API_BASE", "")
    script_model = env.get("AUTOCUT_SCRIPT_API_MODEL", "")
    print("\nScript writer LLM:")
    ok_all &= status(bool(script_api), "AUTOCUT_SCRIPT_API_BASE", script_api or "needed for script/one-click mode")
    ok_all &= status(bool(script_model and script_model != "your-openai-compatible-llm"), "AUTOCUT_SCRIPT_API_MODEL", script_model or "needed for script/one-click mode")
    if script_api and not can_connect(script_api):
        warn("Script LLM endpoint not reachable now", script_api)

    print("\nResult:")
    if ok_all:
        print("✓ Basic setup looks ready. You can run: ./scripts/run_gui.sh")
        return 0
    print("✗ Setup is incomplete. Fix the items marked ✗ above, then run this check again.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
