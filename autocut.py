#!/usr/bin/env python3
"""autoCut custom wrapper around the upstream sentrysearch submodule."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import click

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    sys.stderr.write(
        "Missing dependency: python-dotenv\n"
        "Install the project package and its local-api extras first:\n"
        "  ./.venv/bin/python -m pip install -e ./sentrysearch[local-api]\n"
        "or with uv:\n"
        "  uv pip install -e ./sentrysearch[local-api]\n"
        "Then run autocut with the project virtualenv:\n"
        "  ./.venv/bin/python autocut.py ...\n"
    )
    raise SystemExit(1)

ROOT = Path(__file__).resolve().parent
SUBMODULE = ROOT / "sentrysearch"

if str(SUBMODULE) not in sys.path:
    sys.path.insert(0, str(SUBMODULE))

from sentrysearch.cli import cli as upstream_cli  # noqa: E402
from sentrysearch.chunker import _get_ffmpeg_executable  # noqa: E402
import sentrysearch.local_api_embedder as local_api_embedder  # noqa: E402
from sentrysearch.local_api_embedder import LocalApiEmbedder  # noqa: E402
from sentrysearch.openai_compat import DEFAULT_API_BASE, LocalLLMClient  # noqa: E402
from sentrysearch.store import SentryStore, detect_index  # noqa: E402
from sentrysearch.trimmer import trim_clip  # noqa: E402
from sentrysearch.v360_utils import convert_clip_to_flat, detect_360_projection  # noqa: E402

load_dotenv(ROOT / ".env")

DEFAULT_PROMPT = (
    "first-person perspective or over-the-shoulder user viewpoint moments"
)
DEFAULT_VIEW_PROMPT = (
    "first-person perspective or over-the-shoulder user viewpoint, "
    "prefer the direction the user is facing"
)
VIEW_CHOICES = ["auto", "front", "right", "back", "left"]
VIEW_TO_YAW = {"front": 0, "right": 90, "back": 180, "left": 270}


@click.group(
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
    invoke_without_command=False,
)
def cli() -> None:
    """autoCut CLI."""


@cli.command(
    "autocut",
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
@click.argument("video", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--prompt", default=DEFAULT_PROMPT, show_default=True,
              help="Instruction for selecting which clips to keep.")
@click.option("--view-prompt", default=DEFAULT_VIEW_PROMPT, show_default=True,
              help="Instruction for choosing the viewport direction for 360 chunks during indexing.")
@click.option("--view", type=click.Choice(VIEW_CHOICES), default="auto", show_default=True,
              help="Override final 360 output view for all selected clips.")
@click.option("--yaw", type=float, default=None,
              help="Override final 360 output yaw in degrees. Takes precedence over --view.")
@click.option("--count", default=3, show_default=True,
              help="Number of clips to include.")
@click.option("-o", "--output", default="autocut_output.mp4", show_default=True,
              type=click.Path(dir_okay=False, path_type=Path),
              help="Output path for the edited video.")
@click.option("--api-base-url", default=None,
              help="Local API base URL (default: env LOCAL_API_BASE or project default).")
@click.option("--hq-source", default=None,
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="High-quality source file to trim from instead of VIDEO.")
@click.option("--hq-dir", default=None,
              type=click.Path(exists=True, file_okay=False, path_type=Path),
              help="Directory containing matching HQ source files (auto-mapped by timestamp).")
@click.option("--360/--no-360", "is_360", default=None,
              help="Treat video as 360-degree video. Auto-detected when omitted.")
@click.option("--force-reindex", is_flag=True,
              help="Re-index this video so changed viewport prompts take effect.")
@click.option("--verbose", is_flag=True, help="Show debug info.")
def autocut_command(
    video: Path,
    prompt: str,
    view_prompt: str,
    view: str,
    yaw: float | None,
    count: int,
    output: Path,
    api_base_url: str | None,
    hq_source: Path | None,
    hq_dir: Path | None,
    is_360: bool | None,
    force_reindex: bool,
    verbose: bool,
) -> None:
    """Project-specific autocut flow built on top of upstream sentrysearch."""
    if hq_source and hq_dir:
        raise click.UsageError("Use only one of --hq-source or --hq-dir, not both.")

    video_path = str(video.resolve())
    output_path = str(output.expanduser().resolve())

    projection = None
    if is_360 is None:
        projection = detect_360_projection(video_path)
        if projection:
            is_360 = True
            click.echo(f"Auto-detected 360 video ({projection})", err=True)
        else:
            is_360 = False
    elif is_360:
        projection = detect_360_projection(video_path) or "equirect"

    _index_video(
        video_path=video_path,
        api_base_url=api_base_url,
        is_360=bool(is_360),
        projection=projection,
        view_prompt=view_prompt,
        force_reindex=force_reindex,
        verbose=verbose,
    )

    rows = _load_rows(video_path)
    if not rows:
        click.echo("No captions found for this video. Indexing may have failed.")
        raise SystemExit(1)

    selected = _select_clips(rows, prompt=prompt, count=count,
                             api_base_url=api_base_url, verbose=verbose)
    _render_autocut(
        selected,
        source_video=video_path,
        output_path=output_path,
        hq_source=str(hq_source.resolve()) if hq_source else None,
        hq_dir=str(hq_dir.resolve()) if hq_dir else None,
        view=view,
        yaw=yaw,
        detected_projection=projection,
    )


@cli.command(
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
@click.pass_context
def upstream(ctx: click.Context) -> None:
    """Pass through to the upstream sentrysearch CLI."""
    sys.argv = [sys.argv[0], *ctx.args]
    upstream_cli(prog_name="autocut")


def _fmt_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def _resolve_hq_source(video_path: str, hq_source: str | None, hq_dir: str | None) -> str | None:
    if hq_source:
        return os.path.abspath(os.path.expanduser(hq_source))
    if not hq_dir:
        return None

    directory = os.path.abspath(os.path.expanduser(hq_dir))
    base = os.path.basename(video_path)
    timestamp_match = re.search(r"(\d{8}_\d{6})", base)
    timestamp = timestamp_match.group(1) if timestamp_match else None
    seq_match = re.search(r"_(\d{3})(?:\.[^.]+)?$", base)
    seq = seq_match.group(1) if seq_match else None

    candidates = []
    if timestamp and seq:
        candidates += [
            f"VID_{timestamp}_00_{seq}.mp4",
            f"VID_{timestamp}_00_{seq}.mov",
            f"VID_{timestamp}_{seq}.mp4",
            f"VID_{timestamp}_{seq}.mov",
        ]
    if timestamp:
        candidates += [f"VID_{timestamp}.mp4", f"VID_{timestamp}.mov"]

    for name in candidates:
        candidate = os.path.join(directory, name)
        if os.path.isfile(candidate):
            return candidate

    if timestamp:
        for entry in sorted(os.listdir(directory)):
            if entry.startswith(f"VID_{timestamp}") and entry.lower().endswith((".mp4", ".mov", ".m4v")):
                return os.path.join(directory, entry)

    raise FileNotFoundError(
        f"Could not find HQ source for {video_path} in {directory}. Pass --hq-source explicitly."
    )


def _build_view_prompt(view_prompt: str) -> str:
    goal = view_prompt.strip()
    return (
        "This is a 360-degree video with frames from different viewing directions. "
        "Below each direction is labeled with its frames:\n\n"
        "Front (looking ahead):\n"
        "Right (90 degrees to the right):\n"
        "Back (behind):\n"
        "Left (90 degrees to the left):\n\n"
        f"Choose the direction that best matches this editing request: \"{goal}\". "
        "Prefer the requested viewpoint/content over generic interestingness. "
        "Then describe ONLY that chosen direction in 1-2 concise sentences, including the main subject, actions, setting, and notable objects/events.\n\n"
        "On the final line, write exactly: 'Best direction: <front|right|back|left>'"
    )


def _index_video(*, video_path: str, api_base_url: str | None, is_360: bool,
                 projection: str | None, view_prompt: str,
                 force_reindex: bool, verbose: bool) -> None:
    from sentrysearch.chunker import chunk_video

    click.echo("Indexing video...")
    original_360_prompt = local_api_embedder.CAPTION_360_PROMPT
    if is_360:
        local_api_embedder.CAPTION_360_PROMPT = _build_view_prompt(view_prompt)

    try:
        embedder = LocalApiEmbedder(
            api_base_url=api_base_url,
            is_360=is_360,
            projection=projection,
        )
    finally:
        local_api_embedder.CAPTION_360_PROMPT = original_360_prompt

    store = SentryStore(backend="local-api", model=None)

    if force_reindex:
        removed = store.remove_file(video_path)
        if removed:
            click.echo(f"Removed {removed} existing chunk(s) for reindex.", err=True)

    chunks = chunk_video(video_path, chunk_duration=30, overlap=5)
    new_chunks = 0
    for chunk in chunks:
        chunk_id = store.make_chunk_id(video_path, chunk["start_time"])
        if store.has_chunk(chunk_id):
            if is_360 and not force_reindex:
                click.echo(
                    f"Skipping existing chunk @ {_fmt_time(chunk['start_time'])}; use --force-reindex after changing --view-prompt.",
                    err=True,
                )
            continue

        click.echo(f"  Indexing chunk @ {_fmt_time(chunk['start_time'])}...")
        meta: dict = {}
        vec = embedder.embed_video_chunk(chunk["chunk_path"], metadata=meta, verbose=verbose)
        if vec is None:
            continue

        chunk_meta = {
            "source_file": video_path,
            "start_time": chunk["start_time"],
            "end_time": chunk["end_time"],
            "caption": meta.get("caption", ""),
            "is_360": meta.get("is_360", False),
            "best_yaw": meta.get("best_yaw", 0),
            "best_direction": meta.get("best_direction", ""),
            "projection": meta.get("projection", projection or "equirect"),
        }
        store.add_chunk(chunk_id, vec, chunk_meta)
        new_chunks += 1
        try:
            os.unlink(chunk["chunk_path"])
        except OSError:
            pass

    if chunks:
        shutil.rmtree(os.path.dirname(chunks[0]["chunk_path"]), ignore_errors=True)
    click.echo(f"Indexed {new_chunks} new chunk(s).")


def _load_rows(video_path: str) -> list[dict]:
    backend, detected_model = detect_index()
    if backend is None:
        return []
    store = SentryStore(backend=backend, model=detected_model)
    all_data = store.collection.get(include=["metadatas"])
    rows: list[dict] = []
    for i, _cid in enumerate(all_data.get("ids", [])):
        meta = all_data["metadatas"][i]
        if meta.get("source_file") != video_path:
            continue
        caption = meta.get("caption", "")
        if not caption:
            continue
        rows.append({
            "idx": i,
            "source_file": meta["source_file"],
            "start_time": float(meta["start_time"]),
            "end_time": float(meta["end_time"]),
            "caption": caption,
            "is_360": meta.get("is_360", False),
            "best_yaw": meta.get("best_yaw", 0),
            "best_direction": meta.get("best_direction", ""),
            "projection": meta.get("projection", "equirect"),
        })
    rows.sort(key=lambda r: r["start_time"])
    return rows


def _select_clips(rows: list[dict], *, prompt: str, count: int,
                  api_base_url: str | None, verbose: bool) -> list[dict]:
    click.echo(f"\nAsking LLM to select {count} clips for: '{prompt}'...")
    seg_lines = [
        f"#{r['idx']}: {_fmt_time(r['start_time'])}-{_fmt_time(r['end_time'])} - {r['caption']}"
        for r in rows
    ]
    llm_prompt = (
        "You are a video editor. Given these video segments with descriptions:\n\n"
        + "\n".join(seg_lines)
        + f"\n\nSelect the top {count} segments that best match: \"{prompt}\".\n"
          "Return only the index numbers (like 0, 1, 2), one per line, nothing else."
    )
    client = LocalLLMClient(api_base_url=api_base_url or DEFAULT_API_BASE)
    resp = client._client.chat.completions.create(
        model=client.model,
        messages=[{"role": "user", "content": [{"type": "text", "text": llm_prompt}]}],
        max_tokens=128,
        temperature=0.1,
    )
    answer = resp.choices[0].message.content or ""
    if verbose:
        click.echo(f"LLM response:\n{answer}")

    selected_indices = []
    valid_ids = {r["idx"]: r for r in rows}
    for token in re.findall(r"\d+", answer):
        idx = int(token)
        if idx in valid_ids:
            selected_indices.append(idx)
    selected_indices = list(dict.fromkeys(selected_indices))[:count]
    if not selected_indices:
        click.secho("LLM did not return valid indices, falling back to first N.", fg="yellow")
        selected_indices = [r["idx"] for r in rows[:count]]

    selected = [valid_ids[idx] for idx in selected_indices]
    click.secho(f"\nSelected {len(selected)} clips:", fg="green", bold=True)
    for s in selected:
        click.echo(f"  [{_fmt_time(s['start_time'])}-{_fmt_time(s['end_time'])}] {s['caption'][:100]}")
    return selected


def _render_autocut(selected: list[dict], *, source_video: str, output_path: str,
                    hq_source: str | None, hq_dir: str | None, view: str,
                    yaw: float | None, detected_projection: str | None) -> None:
    trim_source = _resolve_hq_source(source_video, hq_source, hq_dir)
    if trim_source:
        click.echo(f"Using HQ trim source: {trim_source}")

    output_dir = os.path.dirname(output_path) or "."
    os.makedirs(output_dir, exist_ok=True)
    clip_list_path = os.path.join(output_dir, "_autocut_concat.txt")
    clip_files: list[str] = []

    try:
        for i, s in enumerate(selected):
            clip_path = output_path.replace(".mp4", f"_{i}.mp4")
            if s.get("is_360"):
                effective_yaw = yaw
                effective_direction = None
                if effective_yaw is None and view != "auto":
                    effective_yaw = VIEW_TO_YAW[view]
                    effective_direction = view
                if effective_yaw is None:
                    effective_yaw = s.get("best_yaw", 0)
                    effective_direction = s.get("best_direction", "front")

                intermediate = clip_path.replace(".mp4", "_raw.mp4")
                trim_clip(
                    source_file=trim_source or s["source_file"],
                    start_time=s["start_time"],
                    end_time=s["end_time"],
                    output_path=intermediate,
                    padding=1.0,
                )
                proj = _projection_for_trim_source(trim_source or s["source_file"], s, detected_projection)
                click.echo(
                    f"Converting 360 clip from {effective_direction or f'yaw={effective_yaw}'} "
                    f"(yaw={effective_yaw}, proj={proj})..."
                )
                convert_clip_to_flat(intermediate, clip_path, yaw=effective_yaw, projection=proj)
                try:
                    os.unlink(intermediate)
                except OSError:
                    pass
            else:
                trim_clip(
                    source_file=trim_source or s["source_file"],
                    start_time=s["start_time"],
                    end_time=s["end_time"],
                    output_path=clip_path,
                    padding=1.0,
                )
            clip_files.append(clip_path)

        if not clip_files:
            raise RuntimeError("No clips were successfully trimmed.")

        with open(clip_list_path, "w", encoding="utf-8") as f:
            for cf in clip_files:
                f.write(f"file '{os.path.abspath(cf)}'\n")

        ffmpeg = _get_ffmpeg_executable()
        result = subprocess.run(
            [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", clip_list_path, "-c", "copy", output_path],
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
        click.secho(f"\n✓ Auto-cut complete: {output_path}", fg="green", bold=True)
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


def _projection_for_trim_source(trim_source: str, row: dict, detected_projection: str | None) -> str:
    detected = detect_360_projection(trim_source)
    if detected:
        return detected
    return row.get("projection") or detected_projection or "equirect"


if __name__ == "__main__":
    cli()
