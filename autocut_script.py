#!/usr/bin/env python3
"""autoCut Script Mode – feed videos, let AI write an edit script, render it."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

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

load_dotenv(ROOT / ".env")


# ── helpers ──────────────────────────────────────────────────────────
def _fmt_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


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


def _resolve_hq_source(video_path: str, hq_dir: str | None) -> str | None:
    if hq_dir:
        directory = os.path.abspath(os.path.expanduser(hq_dir))
        base = os.path.basename(video_path)
        ts_match = re.search(r"(\d{8}_\d{6})", base)
        if not ts_match:
            return None
        ts = ts_match.group(1)
        for f in os.listdir(directory):
            if ts in f and f.lower().endswith((".mp4", ".mov")) and not f.startswith("._"):
                return os.path.join(directory, f)
        return None
    if video_path.lower().endswith(".lrv"):
        base = os.path.basename(video_path)
        ts_match = re.search(r"(\d{8}_\d{6})", base)
        if not ts_match:
            return None
        ts = ts_match.group(1)
        for f in sorted(os.listdir(os.path.dirname(video_path) or ".")):
            if ts in f and f.lower().endswith((".mp4", ".mov")) and not f.startswith("._"):
                return os.path.join(os.path.dirname(video_path) or ".", f)
    return None


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


def format_catalog(rows: list[dict], max_chars: int = 3000) -> str:
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
    if len(text) > max_chars:
        text = text[:max_chars].rsplit("\n", 1)[0] + "\n  ... (truncated)"
    return text


# ── 3. ask LLM for script ────────────────────────────────────────────
def _repair_json(text: str) -> str:
    import re
    text = re.sub(r':\s*(\d{1,2}:\d{2})(?=\s*[,}\]])', r': "\1"', text)
    return text


def ask_script(catalog: str, prompt: str, verbose: bool, auto_prompt: bool = False) -> list[dict]:
    api_base = os.environ.get("LOCAL_API_BASE", "http://192.168.0.207:8080")
    api_key = os.environ.get("LOCAL_API_KEY", "not-needed")
    model = os.environ.get("LOCAL_API_MODEL", "")

    if auto_prompt:
        system = (
            "你是一個專業影片剪輯師。以下是所有素材的片段描述（時間軸、來源檔名、畫面內容）。\n"
            "請自行分析這些素材的內容，判斷最適合的主題與故事線。\n"
            "然後挑選片段編成一支有起承轉合的精彩短片。\n"
            "回傳純 JSON 陣列，格式如下（start_time 和 end_time 必須是數字秒數，例如 0 或 30，不可用 00:00 格式）：\n"
            "[\n"
            '  {"source_file": "檔案名", "start_time": 0, "end_time": 30, "narration": "這段在講什麼"},\n'
            "...\n"
            "]\n"
             "注意：\n"
             "1. source_file 必須與 catalog 中的檔名完全相同（例如 LRV_xxx.lrv 請勿寫成 VID_xxx.lrv）。\n"
             "2. start_time 和 end_time 必須是 catalog 裡出現的數值，不可自創。\n"
             "如果素材不足以編成有意義的影片，請回傳空陣列。"
        )
    else:
        system = (
            "你是一個專業影片剪輯師。以下是所有素材的片段描述（時間軸、來源檔名、畫面內容）。\n"
            "請根據使用者的要求，挑選最適合的片段，編成一支有起承轉合的影片。\n"
            "回傳純 JSON 陣列，格式如下（start_time 和 end_time 必須是數字秒數，例如 0 或 30，不可用 00:00 格式）：\n"
            "[\n"
            '  {"source_file": "檔案名", "start_time": 0, "end_time": 30, "narration": "這段在講什麼"},\n'
            "...\n"
            "]\n"
             "注意：\n"
             "1. source_file 必須與 catalog 中的檔名完全相同（例如 LRV_xxx.lrv 請勿寫成 VID_xxx.lrv）。\n"
             "2. start_time 和 end_time 必須是 catalog 裡出現的數值，不可自創。" + (
                " 使用者額外要求：" + prompt if prompt else ""
            )
        )

    user_msg = f"素材目錄：\n\n{catalog}"

    if verbose:
        click.echo(f"\n── LLM prompt ──", err=True)
        click.echo(f"System: {system[:200]}...", err=True)
        click.echo(f"User: {user_msg[:500]}...", err=True)

    try:
        from openai import OpenAI
        client = OpenAI(base_url=f"{api_base.rstrip('/')}/v1", api_key=api_key)
        resp = client.chat.completions.create(
            model=model or "gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.3,
            max_tokens=2048,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content
    except Exception as e:
        click.echo(f"LLM call failed: {e}", err=True)
        raise SystemExit(1)

    if verbose:
        click.echo(f"\n── LLM response ({len(content)} chars)──", err=True)
        click.echo(content[:1000], err=True)

    content = content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[-1]
        content = content.rsplit("```", 1)[0].strip()

    # repair common JSON mistakes from LLM output
    content = _repair_json(content)

    try:
        data = json.loads(content)
        if isinstance(data, dict):
            data = data.get("script") or data.get("clips") or list(data.values())[0]
        if not isinstance(data, list):
            raise ValueError("response is not a list")
        return data
    except (json.JSONDecodeError, ValueError) as e:
        click.echo(f"Failed to parse LLM response: {e}", err=True)
        hint = "The response was likely truncated. Try running again or with a more specific --prompt to reduce scope." if len(content) < 500 else ""
        if hint:
            click.echo(f"  {hint}", err=True)
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


def validate_script(script: list[dict], catalog_rows: list[dict]) -> list[dict]:
    valid: list[dict] = []
    for item in script:
        src = item.get("source_file", "")
        st = _parse_time(item.get("start_time", 0))
        et = _parse_time(item.get("end_time", 0))
        narration = item.get("narration", "")

        best: dict | None = None
        for r in catalog_rows:
            s_file_matches = (
                r["source_file"] == src
                or os.path.basename(r["source_file"]) == os.path.basename(src)
                or os.path.basename(r["source_file"]) == src
                or _source_key(r["source_file"]) == _source_key(src)
            )
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


# ── 4. render ────────────────────────────────────────────────────────
def render(selected: list[dict], *, output_path: str,
           hq_dir: str | None) -> None:
    from autocut import convert_clip_to_flat, detect_360_projection
    from sentrysearch.trimmer import trim_clip

    ffmpeg = _get_ffmpeg()
    output_dir = os.path.dirname(output_path) or "."
    os.makedirs(output_dir, exist_ok=True)
    clip_list_path = os.path.join(output_dir, "_script_concat.txt")
    clip_files: list[str] = []

    try:
        for i, s in enumerate(selected):
            clip_path = output_path.replace(".mp4", f"_{i}.mp4")
            trim_source = _resolve_hq_source(s["source_file"], hq_dir) or s["source_file"]

            if s.get("is_360"):
                yaw = s.get("best_yaw", 0)
                direction = s.get("best_direction", "front")
                intermediate = clip_path.replace(".mp4", "_raw.mp4")
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
                try:
                    os.unlink(intermediate)
                except OSError:
                    pass
            else:
                trim_clip(
                    source_file=trim_source,
                    start_time=s["start_time"],
                    end_time=s["end_time"],
                    output_path=clip_path,
                    padding=1.0,
                )
            clip_files.append(clip_path)

        if not clip_files:
            raise RuntimeError("No clips were successfully trimmed.")

        has_360 = any(s.get("is_360") for s in selected)
        with open(clip_list_path, "w", encoding="utf-8") as f:
            for cf in clip_files:
                f.write(f"file '{os.path.abspath(cf)}'\n")

        if has_360:
            # Mixed 360 (re-encoded to h.264) and non-360 clips (original codec)
            # may have incompatible codecs; always re-encode to a common format.
            result = subprocess.run(
                [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", clip_list_path,
                 "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                 "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                 "-c:a", "aac", "-b:a", "128k", output_path],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "ffmpeg concat failed")
        else:
            # All clips are the same source type; stream-copy is safe.
            result = subprocess.run(
                [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", clip_list_path,
                 "-c", "copy", output_path],
                capture_output=True, text=True,
            )
            if result.returncode != 0 or not os.path.isfile(output_path):
                click.echo("Stream copy failed, re-encoding...")
                result = subprocess.run(
                    [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", clip_list_path,
                     "-c:v", "mpeg4", "-q:v", "5", "-c:a", "aac", output_path],
                    capture_output=True, text=True,
                )
                if result.returncode != 0:
                    raise RuntimeError(result.stderr.strip() or "ffmpeg concat failed")

        click.secho(f"\n✓ Script edit complete: {output_path}", fg="green", bold=True)
    finally:
        for cf in clip_files:
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
@click.option("--verbose", is_flag=True)
def create(videos, prompt, output, backend, model,
           hq_dir, force_reindex, auto_prompt, verbose):
    """Index videos, ask AI for an edit script, render the result."""
    backend = backend or _auto_backend()
    model = model or _auto_model()
    output_path = str(Path(output).expanduser().resolve())

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

    catalog = format_catalog(rows)
    if verbose:
        click.echo(f"\n── Catalog ({len(catalog)} chars)──")
        click.echo(catalog[:2000])

    # 3. ask LLM
    click.echo("\n── 3. Asking AI for edit script ──")
    if auto_prompt:
        click.echo("  (AI will decide the theme and story automatically)")
    script = ask_script(catalog, prompt, verbose, auto_prompt=auto_prompt)
    click.echo(f"  AI suggested {len(script)} clip(s).")

    # 4. validate
    selected = validate_script(script, rows)
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
    render(selected, output_path=output_path, hq_dir=hq_dir)

    click.echo(f"\nDone: {output_path}")


if __name__ == "__main__":
    cli()
