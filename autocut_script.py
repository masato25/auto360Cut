#!/usr/bin/env python3
"""autoCut Script Mode – feed videos, let AI write an edit script, render it."""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import click

ROOT = Path(__file__).resolve().parent
SUBMODULE = ROOT / "sentrysearch"
if str(SUBMODULE) not in sys.path:
    sys.path.insert(0, str(SUBMODULE))

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    sys.stderr.write("Install base deps first: pip install -r requirements.txt\n")
    raise SystemExit(1)

from enhancement import (  # noqa: E402
    ENHANCE_PRESETS,
    apply_enhancement,
    build_enhance_plan,
    ffmpeg_video_encode_args,
    get_enhance_settings,
    write_enhance_plan,
)
from utils import fmt_time as _fmt_time, resolve_hq_source as _resolve_hq_source  # noqa: E402

load_dotenv(ROOT / ".env")


# ── helpers ──────────────────────────────────────────────────────────
def _get_ffmpeg() -> str:
    from sentrysearch.chunker import _get_ffmpeg_executable
    ff = _get_ffmpeg_executable()
    if not ff:
        raise RuntimeError("ffmpeg not found")
    return ff


def _auto_backend() -> str:
    return os.environ.get("AUTOCUT_BACKEND", "local-api")


def _auto_model() -> str | None:
    return os.environ.get("LOCAL_API_MODEL") or None


# ── 1. index ─────────────────────────────────────────────────────────
def index_videos(videos: list[str], backend: str, model: str | None,
                 force_reindex: bool, verbose: bool) -> None:
    from autocut import (
        _index_video, detect_360_projection, _validate_backend_options, _resolve_model,
    )
    _validate_backend_options(backend, model, None)
    resolved = _resolve_model(backend, model, None)
    viewport_prompt = "Choose the viewport angle whose content would work best in a video sequence — prioritize dynamic, engaging views with people, faces, or interesting foreground action. Avoid blank walls, corridors, or empty scenes. Consider what would look good edited together with surrounding shots."
    for v in videos:
        proj = detect_360_projection(v)
        is_360 = proj is not None
        _index_video(
            video_path=v, backend=backend, model=resolved,
            quantize=None, is_360=is_360, projection=proj,
            viewport_prompt=viewport_prompt,
            force_reindex=force_reindex, verbose=verbose,
        )


# ── 2. collect captions ──────────────────────────────────────────────
def collect_rows(videos: list[str], backend: str, model: str | None) -> list[dict]:
    from autocut import _load_rows
    all_rows: list[dict] = []
    for v in videos:
        rows = _load_rows(v, backend=backend, model=model)
        for r in rows:
            if r not in all_rows:
                all_rows.append(r)
    return all_rows


def format_catalog(rows: list[dict], max_chars: int | None = None) -> str:
    lines: list[str] = []
    by_file: dict[str, list[dict]] = {}
    for r in rows:
        by_file.setdefault(r["source_file"], []).append(r)
    for f in sorted(by_file, key=lambda p: os.path.basename(p)):
        chunks = sorted(by_file[f], key=lambda c: c["start_time"])
        lines.append(f"[{os.path.basename(f)}]")
        for c in chunks:
            cap = (c.get("caption") or "").strip()[:80]
            lines.append(f"  {_fmt_time(c['start_time'])}-{_fmt_time(c['end_time'])} | {cap}")
        lines.append("")
    text = "\n".join(lines)
    if max_chars and max_chars > 0 and len(text) > max_chars:
        text = text[:max_chars].rsplit("\n", 1)[0] + "\n  ... (truncated)"
    return text


# ── 3. ask LLM for script ────────────────────────────────────────────
def _repair_json(text: str) -> str:
    import re
    text = re.sub(r':\s*(\d{1,2}:\d{2})(?=\s*[,}\]])', r': "\1"', text)
    return text


def _coerce_script_response(data: object) -> list[dict]:
    if isinstance(data, dict):
        data = data.get("clips") or data.get("script") or data.get("items") or list(data.values())[0]
    if not isinstance(data, list):
        raise ValueError("response is not a list")
    return data


def _parse_json_or_recover_clips(content: str) -> list[dict]:
    """Parse LLM JSON, recovering complete clip objects if the response is truncated."""
    try:
        return _coerce_script_response(json.loads(content))
    except json.JSONDecodeError as original_error:
        decoder = json.JSONDecoder()
        clips: list[dict] = []
        # Recover any complete top-level objects. This handles responses like:
        # [{...}, {...}, {"source_file": "truncated
        for match in re.finditer(r'\{', content):
            try:
                obj, _ = decoder.raw_decode(content[match.start():])
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and {"source_file", "start_time", "end_time"} <= set(obj):
                clips.append(obj)
        if clips:
            click.echo(
                f"Recovered {len(clips)} complete clip(s) from a truncated LLM response.",
                err=True,
            )
            return clips
        raise original_error


def _script_api_defaults() -> tuple[str, str, str, int | None]:
    """Return OpenAI/ChatGPT-compatible API settings used only for script writing."""
    api_base = (
        os.environ.get("AUTOCUT_SCRIPT_API_BASE")
        or os.environ.get("OPENAI_BASE_URL")
        or os.environ.get("OPENAI_API_BASE")
        or os.environ.get("LOCAL_API_BASE")
        or "http://192.168.0.207:8080"
    )
    api_key = (
        os.environ.get("AUTOCUT_SCRIPT_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("LOCAL_API_KEY")
        or "not-needed"
    )
    model = (
        os.environ.get("AUTOCUT_SCRIPT_API_MODEL")
        or os.environ.get("OPENAI_MODEL")
        or os.environ.get("OPENAI_API_MODEL")
        or os.environ.get("LOCAL_API_MODEL")
        or "gpt-3.5-turbo"
    )
    env_max_tokens = os.environ.get("AUTOCUT_SCRIPT_API_MAX_TOKENS", "").strip()
    max_tokens: int | None = None
    if env_max_tokens:
        try:
            max_tokens = int(env_max_tokens)
            if max_tokens <= 0:
                click.echo("  ⚠ AUTOCUT_SCRIPT_API_MAX_TOKENS must be positive; ignoring it.", err=True)
                max_tokens = None
        except ValueError:
            click.echo("  ⚠ AUTOCUT_SCRIPT_API_MAX_TOKENS must be an integer; ignoring it.", err=True)
    return api_base, api_key, model, max_tokens


def _safe_script_max_tokens(max_tokens: int | None) -> int | None:
    if max_tokens is None:
        return None
    if max_tokens <= 0:
        click.echo("  ⚠ --script-api-max-tokens must be positive; ignoring it.", err=True)
        return None
    return max_tokens


def _normalize_openai_base_url(api_base: str) -> str:
    base_url = api_base.strip().rstrip("/")
    if not base_url:
        raise ValueError("script API base URL is empty")
    if not base_url.endswith("/v1"):
        base_url = f"{base_url}/v1"
    return base_url


def _check_api_tcp_connectivity(base_url: str, timeout: float = 3.0) -> tuple[bool, str]:
    """Check whether the script API host:port is reachable before SDK call."""
    parsed = urlparse(base_url)
    host = parsed.hostname
    if not host:
        return False, f"cannot parse host from API URL: {base_url}"
    if parsed.port:
        port = parsed.port
    elif parsed.scheme == "https":
        port = 443
    else:
        port = 80
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, f"{host}:{port} reachable"
    except OSError as exc:
        return False, f"cannot connect to {host}:{port} ({exc})"


_HIGHLIGHT_INSTRUCTION = (
    "\nEditing strategy: Treat this as a highlight edit, not an even summary. "
    "Do not distribute selections evenly across files and do not keep mediocre shots just for completeness. "
    "Review the entire catalog and select only clips with strong information value, emotion, action, facial expression, beautiful visuals, transition value, or story progression. "
    "Avoid long, repetitive, waiting, empty, badly shaky, unclear, low-value filler, or overly similar clips. "
    "If multiple clips show the same event, usually keep only the strongest, clearest, or most useful one for story continuity. "
    "The final rhythm should feel like a polished highlight video: a strong opening, varied middle, and satisfying ending. "
    "Prefer short and precise over long and loose."
)

_JSON_CONTRACT = (
    "Return ONLY a valid JSON array. Do not wrap it in markdown and do not add explanations.\n"
    "Each item must use this exact schema:\n"
    "[\n"
    '  {"source_file": "exact filename from catalog", "start_time": 0, "end_time": 30, "narration": "繁體中文段落說明"}\n'
    "]\n"
    "Strict rules:\n"
    "1. source_file must exactly match a filename in the catalog, character-for-character. For example, do not change LRV_xxx.lrv to VID_xxx.lrv.\n"
    "2. start_time and end_time must be numeric seconds taken from catalog segment boundaries. Never use HH:MM:SS or MM:SS strings.\n"
    "3. Select from the entire catalog, not only the first few files or first few minutes.\n"
    "4. narration must be written in Traditional Chinese.\n"
    "5. If the material is insufficient for a meaningful edit, return []."
)


def _build_weight_instruction(weight_files: dict[str, int] | None) -> str:
    """Build a prompt instruction for mandatory source files."""
    if not weight_files:
        return ""
    mandatory = sorted(fname for fname, w in weight_files.items() if w > 0)
    if not mandatory:
        return ""
    lines = [
        "\n**Mandatory source files:** The following source files MUST each contribute at least one clip to the final edit.",
        "Treat all of them as equally required; do not rank them by preference or prominence.",
    ]
    for fname in mandatory:
        lines.append(f"  - {fname}")
    return "\n".join(lines)


def _build_script_system_prompt(
    auto_prompt: bool,
    prompt: str,
    target_duration_minutes: float | None,
    weight_files: dict[str, int] | None = None,
) -> str:
    duration_instruction = ""
    if target_duration_minutes and target_duration_minutes > 0:
        duration_instruction = (
            f"\nTarget final duration is about {target_duration_minutes:g} minutes. Try to get close, but do not pad the edit. "
            "Highlight quality is more important than hitting the exact duration: when there are many strong clips, it is acceptable to be slightly longer; "
            "when there are not enough strong clips, return a shorter edit instead of adding mediocre filler."
        )
    weight_instruction = _build_weight_instruction(weight_files)

    if auto_prompt:
        return (
            "You are a professional video editor. You will receive a catalog of source-video segments with timeline seconds, exact source filenames, and visual descriptions.\n"
            "Analyze all available material yourself, infer the best theme and story arc, then choose clips for a tight highlight video with a clear beginning, development, turn, and ending.\n"
            f"{_HIGHLIGHT_INSTRUCTION}\n"
            f"{duration_instruction}\n"
            f"{weight_instruction}\n"
            f"{_JSON_CONTRACT}"
        )
    return (
        "You are a professional video editor. You will receive a catalog of source-video segments with timeline seconds, exact source filenames, and visual descriptions.\n"
        "Follow the user's request while still prioritizing a tight highlight edit with a clear beginning, development, turn, and ending.\n"
        f"{_HIGHLIGHT_INSTRUCTION}\n"
        f"{duration_instruction}\n"
        f"{weight_instruction}\n"
        f"{_JSON_CONTRACT}"
        + ("\nAdditional user request: " + prompt if prompt else "")
    )


def _call_script_api(
    base_url: str,
    api_key: str,
    model: str,
    system: str,
    user_msg: str,
    max_tokens: int | None,
    verbose: bool,
) -> str:
    """Call the OpenAI-compatible chat API, falling back to curl on network errors."""

    def _is_unsupported_token_param_error(err: object) -> bool:
        text = str(err).lower()
        return "unsupported parameter" in text and ("max_tokens" in text or "max_output_tokens" in text)

    def _call_via_curl() -> str:
        def _run(send_max_tokens: bool) -> dict:
            payload: dict = {
                "model": model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user_msg}],
                "response_format": {"type": "json_object"},
            }
            if send_max_tokens and max_tokens is not None:
                payload["max_tokens"] = max_tokens
            result = subprocess.run(
                ["curl", "-s", "--max-time", "120",
                 f"{base_url}/chat/completions",
                 "-H", "Content-Type: application/json",
                 "-H", f"Authorization: Bearer {api_key}",
                 "-d", json.dumps(payload)],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                raise ConnectionError(f"curl exit code {result.returncode}: {result.stderr.strip()}")
            return json.loads(result.stdout)

        data = _run(send_max_tokens=True)
        if "error" in data and max_tokens is not None and _is_unsupported_token_param_error(data["error"]):
            click.echo("  ⚠ token limit parameter not supported; retrying without it.", err=True)
            data = _run(send_max_tokens=False)
        if "error" in data:
            raise RuntimeError(f"API error: {data['error']}")
        return data["choices"][0]["message"]["content"]

    try:
        from openai import OpenAI, APIStatusError
        click.echo(f"  Script API: {base_url}  Model: {model}", err=True)
        ok, detail = _check_api_tcp_connectivity(base_url)
        if ok:
            if verbose:
                click.echo(f"  API connectivity: {detail}", err=True)
            client = OpenAI(base_url=base_url, api_key=api_key, timeout=120.0)
            call_kwargs: dict = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_msg},
                ],
                "response_format": {"type": "json_object"},
            }
            if max_tokens is not None:
                call_kwargs["max_tokens"] = max_tokens
            try:
                resp = client.chat.completions.create(**call_kwargs)
            except APIStatusError as api_err:
                if "max_tokens" in call_kwargs and _is_unsupported_token_param_error(api_err):
                    call_kwargs.pop("max_tokens", None)
                    click.echo("  ⚠ token limit parameter not supported; retrying without it.", err=True)
                    resp = client.chat.completions.create(**call_kwargs)
                else:
                    raise
            return resp.choices[0].message.content
        else:
            if verbose:
                click.echo(f"  API connectivity: {detail} — falling back to curl", err=True)
            return _call_via_curl()
    except (OSError, ConnectionError):
        click.echo("  ⚠ Python network blocked; falling back to curl...", err=True)
        return _call_via_curl()
    except Exception as e:
        click.echo(f"LLM call failed: {type(e).__name__}: {e}", err=True)
        click.echo(
            "  Check script API settings: --script-api-base / --script-api-model, "
            "or .env AUTOCUT_SCRIPT_API_BASE / AUTOCUT_SCRIPT_API_MODEL.",
            err=True,
        )
        click.echo(
            "  For a local server, verify it is running and reachable from this Mac, e.g.:\n"
            f"    curl {base_url}/models\n"
            "  If the service is on another machine, check IP address, port, firewall, and that it listens on 0.0.0.0 not only 127.0.0.1.",
            err=True,
        )
        click.echo(
            "  Example for OpenAI: --script-api-base https://api.openai.com/v1 "
            "--script-api-model gpt-4o-mini --script-api-key $OPENAI_API_KEY",
            err=True,
        )
        raise SystemExit(1)


def ask_script(
    catalog: str,
    prompt: str,
    verbose: bool,
    auto_prompt: bool = False,
    *,
    script_api_base: str | None = None,
    script_api_key: str | None = None,
    script_api_model: str | None = None,
    script_api_max_tokens: int | None = None,
    target_duration_minutes: float | None = None,
    weight_files: dict[str, int] | None = None,
) -> list[dict]:
    default_api_base, default_api_key, default_model, default_max_tokens = _script_api_defaults()
    api_base = script_api_base or default_api_base
    api_key = script_api_key or default_api_key
    model = script_api_model or default_model
    max_tokens = _safe_script_max_tokens(
        script_api_max_tokens if script_api_max_tokens is not None else default_max_tokens
    )

    system = _build_script_system_prompt(auto_prompt, prompt, target_duration_minutes, weight_files=weight_files)
    user_msg = f"素材目錄：\n\n{catalog}"
    base_url = _normalize_openai_base_url(api_base)

    if verbose:
        click.echo("\n── LLM prompt ──", err=True)
        click.echo(f"System: {system[:200]}...", err=True)
        click.echo(f"User: {user_msg[:500]}...", err=True)
        click.echo(
            f"Script API: {api_base}  Model: {model}"
            + (f"  Max tokens: {max_tokens}" if max_tokens else "  Max tokens: default/API-managed"),
            err=True,
        )

    content = _call_script_api(base_url, api_key, model, system, user_msg, max_tokens, verbose)

    if verbose:
        click.echo(f"\n── LLM response ({len(content)} chars)──", err=True)
        click.echo(content[:1000], err=True)

    content = content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[-1]
        content = content.rsplit("```", 1)[0].strip()
    content = _repair_json(content)

    try:
        return _parse_json_or_recover_clips(content)
    except (json.JSONDecodeError, ValueError) as e:
        click.echo(f"Failed to parse LLM response: {e}", err=True)
        if len(content) < 500:
            click.echo(
                "  The response was likely truncated. Try running again or with a more specific --prompt to reduce scope.",
                err=True,
            )
        click.echo(f"Raw ({len(content)} chars): {content[:500]}", err=True)
        raise SystemExit(1)


def _parse_time(val: str | int | float) -> float:
    if isinstance(val, (int, float)):
        return float(val)
    val = val.strip()
    if ":" in val:
        parts = val.split(":")
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    return float(val)


def _source_key(filename: str) -> str:
    """Normalize filename for fuzzy matching (strip LRV_/VID_ prefix and extension)."""
    base = os.path.basename(filename)
    for prefix in ("LRV_", "VID_", "lrv_", "vid_"):
        if base.startswith(prefix):
            base = base[len(prefix):]
            break
    base = base.rsplit(".", 1)[0]
    return base


def _source_match_keys(filename: str) -> set[str]:
    path = str(filename or "")
    base = os.path.basename(path)
    keys = {path, base, _source_key(path)}
    try:
        resolved = str(Path(path).expanduser().resolve())
    except Exception:
        resolved = path
    keys.add(resolved)
    keys.add(os.path.basename(resolved))
    keys.add(_source_key(resolved))
    return {k for k in keys if k}


def _source_matches(left: str, right: str) -> bool:
    return bool(_source_match_keys(left) & _source_match_keys(right))


def validate_script(script: list[dict], catalog_rows: list[dict]) -> list[dict]:
    valid: list[dict] = []
    for item in script:
        src = item.get("source_file", "")
        st = _parse_time(item.get("start_time", 0))
        et = _parse_time(item.get("end_time", 0))
        narration = item.get("narration", "")

        best: dict | None = None
        for r in catalog_rows:
            s_file_matches = _source_matches(r["source_file"], src)
            if not s_file_matches:
                continue
            if abs(r["start_time"] - st) > 1.0:
                continue
            if abs(r["end_time"] - et) > 1.0:
                continue
            if best is None or (
                abs(r["start_time"] - st) < abs(best["start_time"] - st)
                and abs(r["end_time"] - et) < abs(best["end_time"] - et)
            ):
                best = r

        if best:
            best["narration"] = narration or best.get("caption", "")
            valid.append(best)
        else:
            click.echo(f"  ⚠ skipping invalid: {os.path.basename(src)} {_fmt_time(st)}-{_fmt_time(et)}", err=True)

    return valid


def _ensure_weighted_files(
    selected: list[dict],
    rows: list[dict],
    weight_files: dict[str, int] | None,
) -> list[dict]:
    """Ensure every mandatory source file contributes at least one clip.

    If a mandatory file is missing from *selected*, automatically add its
    best-scoring segment (longest / most descriptive caption) from *rows*.
    """
    if not weight_files:
        return selected

    mandatory = {fname for fname, w in weight_files.items() if w > 0}
    mandatory_keys = {mf: _source_match_keys(mf) for mf in mandatory}
    if not mandatory:
        return selected

    # Build lookup: which source files are already represented
    represented: set[str] = set()
    for s in selected:
        src = s.get("source_file", "")
        represented.update(_source_match_keys(src))

    def _file_matches_weighted(src: str) -> str | None:
        """Return the matching weight_files key if *src* matches a mandatory file."""
        src_keys = _source_match_keys(src)
        for mf, mf_keys in mandatory_keys.items():
            if src_keys & mf_keys:
                return mf
        return None

    missing = [mf for mf, mf_keys in mandatory_keys.items() if not (mf_keys & represented)]

    if not missing:
        return selected

    # For each missing file, find the best chunk from rows
    by_file: dict[str, list[dict]] = {}
    for r in rows:
        src = r.get("source_file", "")
        mf = _file_matches_weighted(src)
        if mf:
            by_file.setdefault(mf, []).append(r)

    for mf in missing:
        candidates = sorted(
            by_file.get(mf, []),
            key=lambda c: (
                c.get("end_time", 0) - c.get("start_time", 0),
                len(c.get("caption", "") or ""),
            ),
            reverse=True,
        )
        if candidates:
            best = dict(candidates[0])
            best["narration"] = best.get("narration") or best.get("caption", "") or f"[mandatory: {os.path.basename(mf) or mf}]"
            selected.append(best)
            label = mf if os.path.basename(mf) == mf else f"{os.path.basename(mf)} ({mf})"
            click.echo(f"  ℹ auto-added mandatory file: {label} ({_fmt_time(best['start_time'])}-{_fmt_time(best['end_time'])})", err=True)

    return selected


# ── 4. render ────────────────────────────────────────────────────────
OUTPUT_LAYOUT_CHOICES = ("landscape", "portrait")
CAPTION_DURATION_ENV = "AUTOCUT_CAPTION_DURATION_SECONDS"
BAND_TEXT_ENV = "AUTOCUT_BAND_TEXT"
BAND_BOX_COLOR_ENV = "AUTOCUT_BAND_BOX_COLOR"
DEFAULT_CAPTION_DURATION = 3.0
DEFAULT_BAND_BOX_COLOR = "black@1.0"
MUSIC_DIR_ENV = "AUTOCUT_MUSIC_DIR"
DEFAULT_MUSIC_VOLUME = 0.18
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus", ".aiff", ".aif"}
# Backward-compatible name for older callers/tests.
DEFAULT_OPENING_CAPTION_DURATION = DEFAULT_CAPTION_DURATION


def _render_layout_filter(layout: str) -> tuple[str, int | None, int | None]:
    """Return ffmpeg filter and dimensions for script-mode output layout."""
    if layout == "portrait":
        return (
            "scale=1080:1920:force_original_aspect_ratio=decrease,"
            "pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,format=yuv420p",
            1080,
            1920,
        )
    if layout == "landscape":
        return (
            "scale=1280:720:force_original_aspect_ratio=decrease,"
            "pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,format=yuv420p",
            1280,
            720,
        )
    raise ValueError(f"unknown output layout: {layout}")


def _choose_output_layout(requested_layout: str) -> str:
    if requested_layout not in OUTPUT_LAYOUT_CHOICES:
        raise ValueError(
            f"unknown output layout: {requested_layout}; choose 'landscape' or 'portrait'"
        )
    return requested_layout


def _escape_drawtext_text(text: str) -> str:
    """Escape user text for ffmpeg drawtext's text= value."""
    return (
        text.replace("\\", r"\\")
        .replace(":", r"\:")
        .replace("'", r"\'")
        .replace("%", r"\%")
        .replace("\n", r"\n")
        .replace("\r", "")
    )


def _opening_caption_dimensions(layout: str) -> tuple[int, int]:
    _, width, height = _render_layout_filter(layout)
    if width is None or height is None:
        raise ValueError(f"unknown output layout: {layout}")
    return width, height


def _normalize_caption_duration(duration: float | int | str | None = None) -> float:
    """Return the title/closing-card duration.

    One shared duration is used for both opening and closing captions.  It
    defaults to 3 seconds and can be changed with AUTOCUT_CAPTION_DURATION_SECONDS.
    """
    raw = duration
    if raw is None:
        raw = os.environ.get(CAPTION_DURATION_ENV, "").strip() or DEFAULT_CAPTION_DURATION
    try:
        normalized = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{CAPTION_DURATION_ENV} must be a positive number") from exc
    if normalized <= 0:
        raise ValueError(f"{CAPTION_DURATION_ENV} must be positive")
    return normalized


def _normalize_opening_caption_duration(duration: float | int | str | None = None) -> float:
    """Backward-compatible wrapper for the shared caption duration."""
    return _normalize_caption_duration(duration)


_CJK_FONT_CANDIDATES = (
    # macOS
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    # Linux
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKtc-Regular.otf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    # Windows
    r"C:\\Windows\\Fonts\\msjh.ttc",
    r"C:\\Windows\\Fonts\\mingliu.ttc",
    r"C:\\Windows\\Fonts\\simhei.ttf",
)


def _opening_caption_fontfile() -> str | None:
    """Return a UTF-8/CJK-capable font file for ffmpeg drawtext, if available."""
    configured = os.environ.get("AUTOCUT_OPENING_CAPTION_FONT", "").strip()
    if configured:
        return configured
    for candidate in _CJK_FONT_CANDIDATES:
        if os.path.isfile(candidate):
            return candidate
    return None


def _escape_drawtext_option_value(value: str) -> str:
    """Escape a generic ffmpeg drawtext option value such as fontfile."""
    return value.replace("\\", r"\\").replace(":", r"\:").replace("'", r"\'")


def _caption_drawtext_filter(text: str, *, layout: str, position: str = "center", box_color: str | None = None) -> str:
    caption = (text or "").strip()
    if not caption:
        raise ValueError("caption text is empty")
    if position not in {"center", "bottom-right"}:
        raise ValueError(f"unknown caption position: {position}")
    font_size = 56 if layout == "portrait" else 42
    border_width = 24
    if position == "bottom-right":
        # Smaller channel/name band in the lower-right corner.
        font_size = 42 if layout == "portrait" else 30
        border_width = 16
        x_expr = "w-text_w-48"
        y_expr = "h-text_h-48"
    else:
        x_expr = "(w-text_w)/2"
        y_expr = "(h-text_h)/2"
    escaped_text = _escape_drawtext_text(caption)
    fontfile = _opening_caption_fontfile()
    font_option = ""
    if fontfile:
        font_option = f"fontfile='{_escape_drawtext_option_value(fontfile)}':"
    box_color = (box_color or DEFAULT_BAND_BOX_COLOR).strip() or DEFAULT_BAND_BOX_COLOR
    return (
        "format=yuv420p,"
        "drawtext="
        f"{font_option}"
        f"text='{escaped_text}':"
        "fontcolor=white:"
        f"fontsize={font_size}:"
        "line_spacing=14:"
        f"x={x_expr}:"
        f"y={y_expr}:"
        f"box=1:boxcolor={_escape_drawtext_option_value(box_color)}:boxborderw={border_width}:"
        f"fix_bounds=1"
    )


def _opening_caption_drawtext_filter(text: str, *, layout: str) -> str:
    return _caption_drawtext_filter(text, layout=layout, position="center", box_color="black@1.0")


def _band_caption_drawtext_filter(text: str, *, layout: str, box_color: str | None = None) -> str:
    return _caption_drawtext_filter(text, layout=layout, position="bottom-right", box_color=box_color)


def _render_opening_caption_clip(
    ffmpeg: str,
    *,
    text: str,
    output_path: str,
    layout: str,
    duration: float | int | None = None,
    band_text: str | None = None,
    band_box_color: str | None = None,
) -> str:
    """Create a short white title/closing card matching the script-mode output format."""
    caption = (text or "").strip()
    if not caption:
        raise ValueError("opening caption text is empty")
    duration = _normalize_opening_caption_duration(duration)
    width, height = _opening_caption_dimensions(layout)
    filters = [_opening_caption_drawtext_filter(caption, layout=layout)]
    band = (band_text or "").strip()
    if band:
        filters.append(_band_caption_drawtext_filter(band, layout=layout, box_color=band_box_color))
    vf = ",".join(filters)
    result = subprocess.run(
        [
            ffmpeg, "-y",
            "-f", "lavfi", "-i", f"color=c=white:s={width}x{height}:r=30:d={duration:g}",
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-t", f"{duration:g}",
            "-vf", vf,
            *ffmpeg_video_encode_args(ffmpeg, preset_speed="fast", crf="18"),
            "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
            "-shortest", "-movflags", "+faststart",
            output_path,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not os.path.isfile(output_path):
        raise RuntimeError(result.stderr.strip() or "ffmpeg opening caption render failed")
    return output_path


def _music_candidates(music_dir: str | None = None) -> list[str]:
    """Return supported audio files from the configured music directory."""
    directory = (music_dir or os.environ.get(MUSIC_DIR_ENV, "")).strip()
    if not directory:
        return []
    root = Path(directory).expanduser()
    if not root.is_dir():
        return []
    files = [
        str(path.resolve())
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS
    ]
    return sorted(files, key=lambda p: p.lower())


def _select_music_file(
    *,
    selected: list[dict],
    output_path: str,
    music_dir: str | None = None,
) -> str | None:
    """Pick a deterministic music file for this edit.

    The selection is automatic but stable: the same clip list/output name maps to
    the same track, while different edits tend to rotate through the library.
    """
    candidates = _music_candidates(music_dir)
    if not candidates:
        return None
    seed_parts = [os.path.basename(output_path)]
    for clip in selected:
        seed_parts.append(str(clip.get("source_file", "")))
        seed_parts.append(str(clip.get("start_time", "")))
        seed_parts.append(str(clip.get("end_time", "")))
    digest = hashlib.sha256("|".join(seed_parts).encode("utf-8")).hexdigest()
    return candidates[int(digest[:12], 16) % len(candidates)]


def _normalize_music_volume(volume: float | int | str | None) -> float:
    raw = volume
    if raw is None:
        raw = os.environ.get("AUTOCUT_MUSIC_VOLUME", "").strip() or DEFAULT_MUSIC_VOLUME
    try:
        normalized = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("AUTOCUT_MUSIC_VOLUME must be a non-negative number") from exc
    if normalized < 0:
        raise ValueError("AUTOCUT_MUSIC_VOLUME must be non-negative")
    return normalized


def _apply_background_music(
    ffmpeg: str,
    input_path: str,
    output_path: str,
    music_path: str,
    *,
    volume: float | int | str | None = None,
) -> str:
    """Mix selected music under the existing video audio, looping to output duration."""
    music_volume = _normalize_music_volume(volume)
    result = subprocess.run(
        [
            ffmpeg, "-y",
            "-i", input_path,
            "-stream_loop", "-1", "-i", music_path,
            "-filter_complex",
            f"[1:a]volume={music_volume:g}[bgm];[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=2[a]",
            "-map", "0:v:0", "-map", "[a]",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
            "-shortest", "-movflags", "+faststart",
            output_path,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not os.path.isfile(output_path):
        raise RuntimeError(result.stderr.strip() or "ffmpeg background music mix failed")
    return output_path


def _normalize_clip_for_concat(ffmpeg: str, input_path: str, output_path: str, *, layout: str) -> str:
    """Re-encode a clip to one stable format before concat.

    The concat demuxer is fragile when neighboring clips have different
    dimensions/codecs/time bases.  This is especially visible when a 360 clip
    was flattened to H.264 but the next non-360 clip is stream-copied from the
    camera: playback can keep showing the previous frame while audio advances.
    """
    vf, width, height = _render_layout_filter(layout)
    scale_args = []
    if width and height:
        scale_args = ["-s", f"{width}x{height}"]
    result = subprocess.run(
        [
            ffmpeg, "-y", "-i", input_path,
            "-vf", vf,
            *scale_args,
            *ffmpeg_video_encode_args(ffmpeg, preset_speed="medium", crf="18"),
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart",
            output_path,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not os.path.isfile(output_path):
        raise RuntimeError(result.stderr.strip() or "ffmpeg clip normalization failed")
    return output_path


def render(selected: list[dict], *, output_path: str,
           hq_dir: str | None, output_layout: str,
           enhance: str = "none", enhance_plan_path: str | None = None,
           opening_caption: str | None = None,
           opening_caption_duration: float | int | None = None,
           closing_caption: str | None = None,
           closing_caption_duration: float | int | None = None,
           opening_band: str | None = None,
           closing_band: str | None = None,
           band_box_color: str | None = None,
           auto_music: bool = False,
           music_dir: str | None = None,
           music_volume: float | int | str | None = None) -> None:
    from sentrysearch.trimmer import trim_clip

    ffmpeg = _get_ffmpeg()
    output_dir = os.path.dirname(output_path) or "."
    os.makedirs(output_dir, exist_ok=True)
    clip_list_path = os.path.join(output_dir, "_script_concat.txt")
    clip_files: list[str] = []
    temp_files: list[str] = []
    resolved_layout = _choose_output_layout(output_layout)
    if resolved_layout == "portrait":
        click.echo("  Output layout: portrait 1080x1920")
    else:
        click.echo("  Output layout: landscape 1280x720")
    enhance_settings = get_enhance_settings(enhance)
    if enhance_settings.preset != "none":
        click.echo(f"  Enhance preset: {enhance_settings.preset} — {enhance_settings.description}")
    opening_caption_text = (opening_caption or "").strip()
    closing_caption_text = (closing_caption or "").strip()
    env_band_text = os.environ.get(BAND_TEXT_ENV, "").strip()
    # AUTOCUT_BAND_TEXT is the current single source for the lower-right band:
    # once set, both opening and closing caption cards use the same band text.
    # Legacy CLI/API arguments still work only when the shared env setting is empty.
    opening_band_text = env_band_text or (opening_band or "").strip()
    closing_band_text = env_band_text or (closing_band or "").strip()
    resolved_band_box_color = (band_box_color or os.environ.get(BAND_BOX_COLOR_ENV, "").strip() or DEFAULT_BAND_BOX_COLOR)
    caption_duration: float | None = None
    if opening_caption_text or closing_caption_text:
        # One shared setting for both opening and closing captions.  GUI/CLI do
        # not expose per-caption duration; set AUTOCUT_CAPTION_DURATION_SECONDS
        # in .env to change it from the default 3 seconds.
        explicit_duration = opening_caption_duration if opening_caption_duration is not None else closing_caption_duration
        caption_duration = _normalize_caption_duration(explicit_duration)
    if opening_caption_text:
        opening_caption_duration = caption_duration
        click.echo(f"  Opening caption: {opening_caption_text} ({opening_caption_duration:g}s)")
    if closing_caption_text:
        closing_caption_duration = caption_duration
        click.echo(f"  Closing caption: {closing_caption_text} ({closing_caption_duration:g}s)")
    if opening_band_text or closing_band_text:
        click.echo(f"  Band box color: {resolved_band_box_color}")
        if opening_band_text:
            click.echo(f"  Opening band: {opening_band_text}")
        if closing_band_text:
            click.echo(f"  Closing band: {closing_band_text}")
    selected_music: str | None = None
    if auto_music:
        selected_music = _select_music_file(
            selected=selected,
            output_path=output_path,
            music_dir=music_dir,
        )
        if selected_music:
            click.echo(f"  Auto music: {os.path.basename(selected_music)}")
        else:
            directory = (music_dir or os.environ.get(MUSIC_DIR_ENV, "")).strip()
            if directory:
                click.echo(f"  ⚠ Auto music enabled but no supported audio files found in: {directory}", err=True)
            else:
                click.echo(f"  ⚠ Auto music enabled but {MUSIC_DIR_ENV} is not set.", err=True)

    try:
        if opening_caption_text:
            title_path = output_path.replace(".mp4", "_opening_caption.mp4")
            click.echo("  Rendering opening caption...")
            _render_opening_caption_clip(
                ffmpeg,
                text=opening_caption_text,
                output_path=title_path,
                layout=resolved_layout,
                duration=opening_caption_duration,
                band_text=opening_band_text,
                band_box_color=resolved_band_box_color,
            )
            clip_files.append(title_path)

        for i, s in enumerate(selected):
            clip_path = output_path.replace(".mp4", f"_{i}.mp4")
            trim_source = _resolve_hq_source(s["source_file"], hq_dir=hq_dir) or s["source_file"]

            if s.get("is_360"):
                from autocut import convert_clip_to_flat, detect_360_projection

                yaw = s.get("best_yaw", 0)
                direction = s.get("best_direction", "front")
                intermediate = clip_path.replace(".mp4", "_raw.mp4")
                temp_files.append(intermediate)
                trim_clip(
                    source_file=trim_source,
                    start_time=s["start_time"],
                    end_time=s["end_time"],
                    output_path=intermediate,
                    padding=1.0,
                )
                proj = detect_360_projection(trim_source) or s.get("projection", "equirect")
                click.echo(f"  Converting 360 ({direction}, yaw={yaw})...")
                convert_clip_to_flat(intermediate, clip_path, yaw=yaw, projection=proj)
            else:
                trim_clip(
                    source_file=trim_source,
                    start_time=s["start_time"],
                    end_time=s["end_time"],
                    output_path=clip_path,
                    padding=1.0,
                )

            normalized_path = output_path.replace(".mp4", f"_{i}_norm.mp4")
            click.echo("  Normalizing clip for concat/output layout...")
            _normalize_clip_for_concat(ffmpeg, clip_path, normalized_path, layout=resolved_layout)
            temp_files.append(clip_path)
            clip_files.append(normalized_path)

        if closing_caption_text:
            closing_path = output_path.replace(".mp4", "_closing_caption.mp4")
            click.echo("  Rendering closing caption...")
            _render_opening_caption_clip(
                ffmpeg,
                text=closing_caption_text,
                output_path=closing_path,
                layout=resolved_layout,
                duration=closing_caption_duration,
                band_text=closing_band_text,
                band_box_color=resolved_band_box_color,
            )
            clip_files.append(closing_path)

        if not clip_files:
            raise RuntimeError("No clips were successfully trimmed.")

        with open(clip_list_path, "w", encoding="utf-8") as f:
            for cf in clip_files:
                f.write(f"file '{os.path.abspath(cf)}'\n")

        # Clips were already normalized to identical video/AAC parameters, so
        # stream-copy concat is safe and avoids a second generation loss.
        result = subprocess.run(
            [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", clip_list_path,
             "-c", "copy", output_path],
            capture_output=True, text=True,
        )
        if result.returncode != 0 or not os.path.isfile(output_path):
            raise RuntimeError(result.stderr.strip() or "ffmpeg concat failed")

        if selected_music:
            music_output_path = output_path.replace(".mp4", "_music.mp4")
            temp_files.append(music_output_path)
            click.echo("  Mixing background music...")
            _apply_background_music(
                ffmpeg,
                output_path,
                music_output_path,
                selected_music,
                volume=music_volume,
            )
            os.replace(music_output_path, output_path)

        if enhance_settings.preset != "none":
            plan = build_enhance_plan(
                preset=enhance_settings.preset,
                input_path=output_path,
                output_path=output_path,
                context="script",
                extra={
                    "clip_count": len(selected),
                    "output_layout": resolved_layout,
                    "opening_caption": opening_caption_text,
                    "opening_caption_duration": opening_caption_duration if opening_caption_text else None,
                    "closing_caption": closing_caption_text,
                    "closing_caption_duration": closing_caption_duration if closing_caption_text else None,
                    "opening_band": opening_band_text,
                    "closing_band": closing_band_text,
                    "band_box_color": resolved_band_box_color if (opening_band_text or closing_band_text) else None,
                    "auto_music": bool(selected_music),
                    "music_file": selected_music,
                    "music_volume": _normalize_music_volume(music_volume) if selected_music else None,
                },
            )
            plan_path = write_enhance_plan(plan, enhance_plan_path)
            click.echo(f"  Enhancement plan: {plan_path}")
            click.echo("  Applying enhancement pass...")
            apply_enhancement(ffmpeg, output_path, output_path, preset=enhance_settings.preset)

        click.secho(f"\n✓ Script edit complete: {output_path}", fg="green", bold=True)
    finally:
        for cf in clip_files + temp_files:
            try:
                os.unlink(cf)
            except OSError:
                pass
        try:
            os.unlink(clip_list_path)
        except OSError:
            pass


# ── CLI ──────────────────────────────────────────────────────────────
@click.group()
def cli():
    """autoCut Script Mode – AI writes an edit script from your footage."""


@cli.command("index")
@click.argument("videos", nargs=-1, required=True,
                type=click.Path(exists=True, dir_okay=False))
@click.option("--backend", default=None,
              help="Backend (default: from .env AUTOCUT_BACKEND).")
@click.option("--model", default=None,
              help="Model override.")
@click.option("--force-reindex", is_flag=True,
              help="Re-index all videos.")
@click.option("--verbose", is_flag=True)
def index_command(videos, backend, model, force_reindex, verbose):
    """Index videos only, without creating or rendering an edit."""
    backend = backend or _auto_backend()
    model = model or _auto_model()

    click.echo(f"autoCut Index — {len(videos)} video(s)")
    click.echo(f"Backend: {backend}")
    click.echo("\n── Indexing videos ──")
    for v in videos:
        click.echo(f"  {os.path.basename(v)}")
    index_videos(list(videos), backend, model, force_reindex, verbose)
    click.secho("\n✓ Indexing complete. You can now use 一般剪輯 / 腳本模式 / 一鍵腳本 faster.", fg="green", bold=True)


@cli.command()
@click.argument("videos", nargs=-1, required=True,
                type=click.Path(exists=True, dir_okay=False))
@click.option("-p", "--prompt", default="",
              help="Describe the story or style you want.")
@click.option("-o", "--output", default="script_output.mp4",
              show_default=True, help="Output path.")
@click.option("--backend", default=None,
              help="Backend (default: from .env AUTOCUT_BACKEND).")
@click.option("--model", default=None,
              help="Model override.")
@click.option("--hq-dir", default=None,
              type=click.Path(exists=True, file_okay=False),
              help="HQ source directory for final trim.")
@click.option("--force-reindex", is_flag=True,
              help="Re-index all videos.")
@click.option("--auto-prompt", is_flag=True,
              help="Let AI decide the story theme automatically (no user prompt needed).")
@click.option("--script-api-base", default=None,
              help="OpenAI-compatible API base URL for script generation (e.g. https://api.openai.com/v1).")
@click.option("--script-api-key", default=None,
              help="API key for script generation. Defaults to AUTOCUT_SCRIPT_API_KEY / OPENAI_API_KEY / LOCAL_API_KEY.")
@click.option("--script-api-model", default=None,
              help="Chat model for script generation. Defaults to AUTOCUT_SCRIPT_API_MODEL / OPENAI_MODEL / LOCAL_API_MODEL.")
@click.option("--script-api-max-tokens", default=None, type=int,
              help="Optional max output tokens for script generation. Default: do not send a token limit unless AUTOCUT_SCRIPT_API_MAX_TOKENS is set.")
@click.option("--catalog-max-chars", default=None, type=int,
              help="Maximum characters of caption catalog sent to AI. Default: unlimited. Use 0 for unlimited.")
@click.option("--target-duration-minutes", default=None, type=float,
              help="Optional target final video duration in minutes for the script writer.")
@click.option("--output-layout", type=click.Choice(OUTPUT_LAYOUT_CHOICES), default="landscape", show_default=True,
              help="Final video shape: landscape (橫式) or portrait (直式).")
@click.option("--weight", "weight_args", multiple=True,
              metavar="FILE[:FLAG]",
              help="Mark a source file as mandatory (e.g. --weight 'vid.mp4' or --weight 'vid.mp4:1'). "
                   "Mandatory files are guaranteed to appear in the final edit. "
                   "May be repeated for multiple files.")
@click.option("--opening-caption", default=None,
              help="Optional opening caption/title card text to insert before the first clip.")
@click.option("--opening-caption-duration", default=None, type=float, hidden=True,
              help="Deprecated. Caption duration is now shared via AUTOCUT_CAPTION_DURATION_SECONDS.")
@click.option("--closing-caption", default=None,
              help="Optional closing caption/title card text to append after the last clip.")
@click.option("--closing-caption-duration", default=None, type=float, hidden=True,
              help="Deprecated. Caption duration is now shared via AUTOCUT_CAPTION_DURATION_SECONDS.")
@click.option("--opening-band", default=None, hidden=True,
              help="Deprecated: use .env AUTOCUT_BAND_TEXT. If AUTOCUT_BAND_TEXT is set, it applies to opening and closing cards.")
@click.option("--closing-band", default=None, hidden=True,
              help="Deprecated: use .env AUTOCUT_BAND_TEXT. If AUTOCUT_BAND_TEXT is set, it applies to opening and closing cards.")
@click.option("--band-box-color", default=None,
              help=f"FFmpeg drawtext box color for opening/closing band. Default: {BAND_BOX_COLOR_ENV} or {DEFAULT_BAND_BOX_COLOR}.")
@click.option("--enhance", type=click.Choice(ENHANCE_PRESETS), default="none", show_default=True,
              help="Apply a final preset-based video/audio enhancement pass.")
@click.option("--enhance-plan", default=None,
              type=click.Path(dir_okay=False),
              help="Write enhancement plan JSON here. Defaults to OUTPUT.enhance-plan.json when --enhance is used.")
@click.option("--auto-music", is_flag=True,
              help=f"Automatically choose background music from {MUSIC_DIR_ENV}.")
@click.option("--music-dir", default=None, hidden=True,
              type=click.Path(exists=True, file_okay=False),
              help=f"Directory of music files. Defaults to {MUSIC_DIR_ENV}.")
@click.option("--music-volume", default=None, type=float, hidden=True,
              help=f"Background music volume multiplier. Default: AUTOCUT_MUSIC_VOLUME or {DEFAULT_MUSIC_VOLUME:g}.")
@click.option("--verbose", is_flag=True)
def create(videos, prompt, output, backend, model,
           hq_dir, force_reindex, auto_prompt, script_api_base,
           script_api_key, script_api_model, script_api_max_tokens,
           catalog_max_chars, target_duration_minutes, output_layout,
           weight_args,
           opening_caption, opening_caption_duration,
           closing_caption, closing_caption_duration,
           opening_band, closing_band, band_box_color,
           enhance, enhance_plan, auto_music, music_dir, music_volume, verbose):
    """Index videos, ask AI for an edit script, render the result."""
    backend = backend or _auto_backend()
    model = model or _auto_model()
    output_path = str(Path(output).expanduser().resolve())

    # Parse --weight args as mandatory flags: "filename" or legacy "filename:weight"
    weight_files: dict[str, int] | None = None
    if weight_args:
        weight_files = {}
        for w_arg in weight_args:
            if ":" in w_arg:
                fname, w_str = w_arg.rsplit(":", 1)
                try:
                    w = int(w_str)
                except ValueError:
                    click.echo(f"  ⚠ invalid required flag in '{w_arg}'; skipping.", err=True)
                    continue
            else:
                fname = w_arg
                w = 1
            fname = str(fname).strip()
            if w > 0 and fname:
                weight_files[fname] = 1
        if weight_files:
            readable_required = [os.path.basename(k) if os.path.basename(k) else k for k in weight_files]
            click.echo(f"  Mandatory files: {readable_required}")

    click.echo(f"autoCut Script Mode — {len(videos)} video(s)")
    click.echo(f"Backend: {backend}  Output: {output_path}")

    # 1. index
    click.echo("\n── 1. Indexing videos ──")
    for v in videos:
        click.echo(f"  {os.path.basename(v)}")
    index_videos(list(videos), backend, model, force_reindex, verbose)

    # 2. collect
    click.echo("\n── 2. Reading captions ──")
    rows = collect_rows(list(videos), backend, model)
    if not rows:
        click.echo("No indexed data found.", err=True)
        raise SystemExit(1)
    click.echo(f"  {len(rows)} chunk(s) loaded.")

    catalog_limit = None if catalog_max_chars is None or catalog_max_chars <= 0 else catalog_max_chars
    catalog = format_catalog(rows, max_chars=catalog_limit)
    click.echo(f"  Catalog: {len(catalog)} chars" + (" (unlimited)" if catalog_limit is None else f" (limited to {catalog_limit})"))
    if verbose:
        click.echo(f"\n── Catalog ({len(catalog)} chars)──")
        click.echo(catalog[:4000])

    # 3. ask LLM
    click.echo("\n── 3. Asking AI for edit script ──")
    if auto_prompt:
        click.echo("  (AI will decide the theme and story automatically)")
    script = ask_script(
        catalog,
        prompt,
        verbose,
        auto_prompt=auto_prompt,
        script_api_base=script_api_base,
        script_api_key=script_api_key,
        script_api_model=script_api_model,
        script_api_max_tokens=script_api_max_tokens,
        target_duration_minutes=target_duration_minutes,
        weight_files=weight_files,
    )
    click.echo(f"  AI suggested {len(script)} clip(s).")

    # 4. validate
    selected = validate_script(script, rows)
    # Ensure mandatory files are represented
    selected = _ensure_weighted_files(selected, rows, weight_files)
    click.echo(f"  {len(selected)} valid clip(s).")
    for s in selected:
        narration = s.get("narration", "")
        click.echo(f"    [{_fmt_time(s['start_time'])}-{_fmt_time(s['end_time'])}] "
                   f"{os.path.basename(s['source_file'])}"
                   f"{' — ' + narration if narration else ''}")

    if not selected:
        click.echo("No valid clips to render.", err=True)
        raise SystemExit(1)

    # 5. render
    click.echo("\n── 4. Rendering ──")
    render(
        selected,
        output_path=output_path,
        hq_dir=hq_dir,
        output_layout=output_layout,
        enhance=enhance,
        enhance_plan_path=str(Path(enhance_plan).expanduser().resolve()) if enhance_plan else None,
        opening_caption=opening_caption,
        opening_caption_duration=opening_caption_duration,
        closing_caption=closing_caption,
        closing_caption_duration=closing_caption_duration,
        opening_band=opening_band,
        closing_band=closing_band,
        band_box_color=band_box_color,
        auto_music=auto_music,
        music_dir=music_dir,
        music_volume=music_volume,
    )

    click.echo(f"\nDone: {output_path}")


if __name__ == "__main__":
    cli()
