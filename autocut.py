#!/usr/bin/env python3
"""autoCut custom wrapper around the upstream sentrysearch submodule."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from difflib import SequenceMatcher
from pathlib import Path

import click

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    sys.stderr.write(
        "Missing dependency: python-dotenv\n"
        "Install the base project dependencies first:\n"
        "  ./.venv/bin/python -m pip install -r requirements.txt\n\n"
        "Then install the sentrysearch editable package with the backend you need:\n"
        "  local-api:   ./.venv/bin/python -m pip install -e './sentrysearch[local-api]'\n"
        "  qwen-cloud:  ./.venv/bin/python -m pip install -e './sentrysearch[qwen-cloud]'\n"
        "  local:       ./.venv/bin/python -m pip install -e './sentrysearch[local]'\n\n"
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
from sentrysearch.embedder import get_embedder, reset_embedder  # noqa: E402
from sentrysearch.qwen_cloud_embedder import (  # noqa: E402
    DashScopeDependencyError,
    default_dashscope_embedding_model,
)
from sentrysearch.search import search_footage  # noqa: E402
from sentrysearch.store import SentryStore  # noqa: E402
from sentrysearch.trimmer import trim_clip  # noqa: E402

load_dotenv(ROOT / ".env")


def detect_360_projection(video_path: str) -> str | None:
    try:
        from sentrysearch.v360_utils import detect_360_projection as _detect_360_projection
    except ModuleNotFoundError:
        return None
    return _detect_360_projection(video_path)


def convert_clip_to_flat(*args, **kwargs):
    try:
        from sentrysearch.v360_utils import convert_clip_to_flat as _convert_clip_to_flat
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "360 viewport conversion is unavailable in the current sentrysearch version: "
            "missing sentrysearch.v360_utils"
        ) from exc
    if "yaw" in kwargs and kwargs["yaw"] is not None:
        kwargs["yaw"] = _normalize_v360_yaw(float(kwargs["yaw"]))
    return _convert_clip_to_flat(*args, **kwargs)


def _normalize_v360_yaw(yaw: float) -> float:
    """Normalize user-facing 0..360 yaw into ffmpeg v360's -180..180 range."""
    return ((yaw + 180.0) % 360.0) - 180.0

DEFAULT_PROMPT = (
    "first-person perspective or over-the-shoulder user viewpoint moments"
)
VIEW_CHOICES = ["auto", "front", "right", "back", "left"]
VIEW_TO_YAW = {"front": 0, "right": 90, "back": 180, "left": 270}
VIEWPORT_INDEX_VERSION = 2
MIN_DISTINCT_CLIP_GAP_SECONDS = 20.0
CAPTION_DUPLICATE_SIMILARITY = 0.86
RENDER_CLIP_PADDING_SECONDS = 1.0
DEFAULT_BACKEND = os.environ.get("AUTOCUT_BACKEND", "local-api")
DEFAULT_LOCAL_MODEL = os.environ.get("AUTOCUT_LOCAL_MODEL", "qwen8b")


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
@click.option("--view", type=click.Choice(VIEW_CHOICES), default="auto", show_default=True,
              help="Override final 360 output view for all selected clips.")
@click.option("--yaw", type=float, default=None,
              help="Override final 360 output yaw in degrees. Takes precedence over --view.")
@click.option("--count", default=3, show_default=True,
              help="Number of clips to include.")
@click.option("-o", "--output", default="autocut_output.mp4", show_default=True,
              type=click.Path(dir_okay=False, path_type=Path),
              help="Output path for the edited video.")
@click.option("--backend", type=click.Choice(["local", "local-api", "qwen-cloud", "gemini"]),
              default=DEFAULT_BACKEND, show_default=True,
              help="Embedding/search backend used for indexing and clip selection. Default is local-api for self-hosted HTTP services (llama.cpp).")
@click.option("--model", default=None,
              help="Model for --backend local, or override local model alias/ID.")
@click.option("--dashscope-model", default=None,
              help="Model for --backend qwen-cloud (default from sentrysearch/env).")
@click.option("--quantize/--no-quantize", default=None,
              help="Only for --backend local: enable or disable quantization explicitly.")
@click.option("--hq-source", default=None,
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="High-quality source file to trim from instead of VIDEO.")
@click.option("--hq-dir", default=None,
              type=click.Path(exists=True, file_okay=False, path_type=Path),
              help="Directory containing matching HQ source files (auto-mapped by timestamp).")
@click.option("--360/--no-360", "is_360", default=None,
              help="Treat video as 360-degree video. Auto-detected when omitted.")
@click.option("--face", default=None,
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="Reference face photo. Focus on clips containing this person.")
@click.option("--force-reindex", is_flag=True,
              help="Re-index this video so changed viewport prompts take effect.")
@click.option("--verbose", is_flag=True, help="Show debug info.")
def autocut_command(
    video: Path,
    prompt: str,
    view: str,
    yaw: float | None,
    count: int,
    output: Path,
    backend: str,
    model: str | None,
    dashscope_model: str | None,
    quantize: bool | None,
    hq_source: Path | None,
    hq_dir: Path | None,
    is_360: bool | None,
    face: Path | None,
    force_reindex: bool,
    verbose: bool,
) -> None:
    """Project-specific autocut flow built on top of upstream sentrysearch."""
    if hq_source and hq_dir:
        raise click.UsageError("Use only one of --hq-source or --hq-dir, not both.")

    video_path = str(video.resolve())
    output_path = str(output.expanduser().resolve())

    _validate_backend_options(backend, model, dashscope_model)
    resolved_model = _resolve_model(backend, model, dashscope_model)

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
        backend=backend,
        model=resolved_model,
        quantize=quantize,
        is_360=bool(is_360),
        projection=projection,
        viewport_prompt=prompt,
        force_reindex=force_reindex,
        verbose=verbose,
    )

    rows = _load_rows(video_path, backend=backend, model=resolved_model)
    if not rows:
        click.echo(
            "No captions found for this video after indexing. "
            "The vision/caption API likely returned empty captions.\n"
            "Try again with --verbose to see the local-api error, and verify your "
            "OpenAI-compatible vision server is running and supports image_url chat "
            "messages. If the cached chunks were stale, rerun with --force-reindex.",
            err=True,
        )
        raise SystemExit(1)

    selected = _select_clips(
        rows,
        prompt=prompt,
        count=count,
        backend=backend,
        model=resolved_model,
        quantize=quantize,
        verbose=verbose,
    )

    if face is not None:
        selected = _rerank_by_face(selected, face)

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


def _rerank_by_face(selected: list[dict], face: Path) -> list[dict]:
    """Stable face-based re-ranking.

    Keep the normal semantic-search result unchanged when no selected clip has
    usable face metadata.  This prevents `--face` from changing the output just
    because face data was missing or from sorting every clip with an equal 0.0
    score.
    """
    click.echo(f"Re-ranking by face similarity: {face}", err=True)
    try:
        from sentrysearch.face_utils import deserialize_encodings, encode_reference_face, face_similarity
        import json
    except ImportError as exc:
        click.echo(f"  face_recognition not available: {exc}", err=True)
        click.echo("  Install: pip install face_recognition", err=True)
        return selected

    ref_enc = encode_reference_face(str(face.resolve()))
    if ref_enc is None:
        click.echo("  No face detected in reference image. Keeping original clip order.", err=True)
        return selected

    scored: list[tuple[int, dict, float]] = []
    positive_scores = 0
    for idx, s in enumerate(selected):
        raw = s.get("face_encodings", "")
        if not raw:
            scored.append((idx, s, 0.0))
            continue
        try:
            stored = deserialize_encodings(json.loads(raw))
        except Exception:
            scored.append((idx, s, 0.0))
            continue
        best_score = max((face_similarity(ref_enc, stored_f) for stored_f in stored), default=0.0)
        if best_score > 0.0:
            positive_scores += 1
        scored.append((idx, s, best_score))

    if positive_scores == 0:
        click.echo("  No usable face matches in selected clips. Keeping original clip order.", err=True)
        return selected

    scored.sort(key=lambda x: (-x[2], x[0]))
    click.echo(f"  Face re-ranking applied (best score: {scored[0][2]:.3f})", err=True)
    for _idx, s, score in scored:
        click.echo(
            f"    face_score={score:.3f}  "
            f"[{_fmt_time(s['start_time'])}-{_fmt_time(s['end_time'])}] "
            f"{s.get('caption', '')[:60]}",
            err=True,
        )
    return [s for _idx, s, _score in scored]


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


def _validate_backend_options(backend: str, model: str | None, dashscope_model: str | None) -> None:
    if model is not None and dashscope_model is not None:
        raise click.UsageError("Use only one of --model or --dashscope-model, not both.")
    if backend in {"local", "local-api"} and dashscope_model is not None:
        raise click.UsageError("--dashscope-model only works with --backend qwen-cloud.")
    if backend in {"gemini", "qwen-cloud"} and model is not None:
        raise click.UsageError("--model only works with --backend local or local-api.")
    if backend == "gemini" and dashscope_model is not None:
        raise click.UsageError("--dashscope-model does not apply to --backend gemini.")


def _resolve_model(backend: str, model: str | None, dashscope_model: str | None) -> str | None:
    if backend in {"local", "local-api"}:
        return model or None
    if backend == "qwen-cloud":
        return dashscope_model or default_dashscope_embedding_model()
    return None


def _index_video(*, video_path: str, backend: str, model: str | None,
                 quantize: bool | None, is_360: bool,
                 projection: str | None, viewport_prompt: str,
                 force_reindex: bool, verbose: bool) -> None:
    from sentrysearch.chunker import chunk_video

    click.echo("Indexing video...")
    reset_embedder()
    embedder_kwargs: dict = {}
    if backend == "local":
        embedder_kwargs["model"] = model
        embedder_kwargs["quantize"] = quantize
    elif backend == "local-api":
        embedder_kwargs["model"] = model
    elif backend == "qwen-cloud":
        embedder_kwargs["model"] = model
    try:
        embedder = get_embedder(backend=backend, **embedder_kwargs)
    except DashScopeDependencyError as exc:
        raise click.ClickException(
            "qwen-cloud backend requires the dashscope SDK.\n\n"
            "Install it in the autoCut root virtualenv with one of:\n"
            "  ./.venv/bin/python -m pip install -e './sentrysearch[qwen-cloud]'\n"
            "  ./.venv/bin/python -m pip install -r requirements-qwen-cloud.txt\n\n"
            f"Original error: {exc}"
        ) from exc

    store = SentryStore(backend=backend, model=model)

    if force_reindex:
        removed = store.remove_file(video_path)
        if removed:
            click.echo(f"Removed {removed} existing chunk(s) for reindex.", err=True)
    elif store.is_indexed(video_path):
        click.echo(
            f"Already indexed, skipping: {os.path.basename(video_path)} "
            "(use --force-reindex to rebuild).",
            err=True,
        )
        return

    chunks = chunk_video(video_path, chunk_duration=30, overlap=5)
    new_chunks = 0
    rebuilt_chunks = 0
    skipped_chunks = 0
    to_index: list[tuple[dict, str]] = []
    for chunk in chunks:
        chunk_id = store.make_chunk_id(video_path, chunk["start_time"])
        existing_meta = _get_chunk_metadata(store, chunk_id)
        if existing_meta is not None:
            existing_caption = (existing_meta.get("caption") or "").strip()
            rebuild_reason = ""
            if not existing_caption:
                rebuild_reason = "cached caption is empty"
            elif is_360 and not _is_360_cache_current(existing_meta, viewport_prompt, projection):
                rebuild_reason = "360 viewport prompt/index settings changed"

            if not rebuild_reason:
                skipped_chunks += 1
                continue

            click.echo(
                f"  Rebuilding chunk @ {_fmt_time(chunk['start_time'])}: {rebuild_reason}.",
                err=True,
            )
            store.collection.delete(ids=[chunk_id])
            rebuilt_chunks += 1

        to_index.append((chunk, chunk_id))

    if is_360 and to_index:
        # ── 360: two-pass — caption all viewports first, then select with context ──
        all_view_data: list[dict] = []
        for chunk, _ in to_index:
            click.echo(f"  Indexing chunk @ {_fmt_time(chunk['start_time'])}...")
            view_data = _caption_all_360_views(
                embedder=embedder,
                chunk_path=chunk["chunk_path"],
                projection=projection or "equirect",
                verbose=verbose,
            )
            all_view_data.append(view_data)

        # Pre-compute each chunk's prompt-best caption for neighbor context
        context_captions: list[str] = []
        for view_data in all_view_data:
            best_view = _choose_best_360_view(embedder, view_data["captions"], viewport_prompt, verbose)
            context_captions.append(view_data["captions"].get(best_view, ""))

        for i, ((chunk, chunk_id), view_data) in enumerate(zip(to_index, all_view_data)):
            prev_caption = context_captions[i - 1] if i > 0 else None
            next_caption = context_captions[i + 1] if i < len(context_captions) - 1 else None
            best_view = _select_best_360_view_with_context(
                embedder, viewport_prompt,
                view_data["captions"], view_data["vectors"],
                prev_caption, next_caption,
                sharpness=view_data.get("sharpness"),
                verbose=verbose,
            )
            best_vec = view_data["vectors"].get(best_view)
            if best_vec is None:
                for view in VIEW_CHOICES:
                    if view in view_data["vectors"]:
                        best_view = view
                        best_vec = view_data["vectors"][view]
                        break
            if best_vec is None:
                continue

            combined_caption = "; ".join(
                f"{view}: {caption}" for view, caption in view_data["captions"].items() if caption
            )
            best_caption = view_data["captions"].get(best_view, "")
            all_faces: list[list[float]] = []
            for view in VIEW_CHOICES:
                all_faces.extend(view_data["face_encodings"].get(view, []))

            meta = {
                "caption": best_caption or combined_caption,
                "is_360": True,
                "best_yaw": VIEW_TO_YAW[best_view],
                "best_direction": best_view,
                "projection": projection or "equirect",
                "viewport_prompt": viewport_prompt,
                "viewport_index_version": VIEWPORT_INDEX_VERSION,
                "viewport_captions": combined_caption,
            }
            if all_faces:
                import json
                meta["face_encodings"] = json.dumps(all_faces)

            chunk_meta = {
                "source_file": video_path,
                "start_time": chunk["start_time"],
                "end_time": chunk["end_time"],
                "caption": meta.get("caption", ""),
                "is_360": True,
                "best_yaw": meta.get("best_yaw", 0),
                "best_direction": meta.get("best_direction", ""),
                "projection": projection or meta.get("projection", "equirect"),
                "viewport_prompt": meta.get("viewport_prompt", ""),
                "viewport_index_version": meta.get("viewport_index_version", 0),
                "viewport_captions": meta.get("viewport_captions", ""),
            }
            face_enc = meta.get("face_encodings")
            if face_enc:
                chunk_meta["face_encodings"] = face_enc
            store.add_chunk(chunk_id, best_vec, chunk_meta)
            new_chunks += 1
            try:
                os.unlink(chunk["chunk_path"])
            except OSError:
                pass

    elif to_index:
        # ── non-360: embed directly ──
        for chunk, chunk_id in to_index:
            click.echo(f"  Indexing chunk @ {_fmt_time(chunk['start_time'])}...")
            meta = {}
            vec = embedder.embed_video_chunk(chunk["chunk_path"], metadata=meta, verbose=verbose)
            if not is_360:
                faces = _detect_faces_in_viewport(chunk["chunk_path"], verbose)
                if faces:
                    import json
                    meta["face_encodings"] = json.dumps(faces)
            if vec is None:
                continue

            chunk_meta = {
                "source_file": video_path,
                "start_time": chunk["start_time"],
                "end_time": chunk["end_time"],
                "caption": meta.get("caption", ""),
                "is_360": False,
                "best_yaw": 0,
                "best_direction": "",
                "projection": "",
                "viewport_prompt": "",
                "viewport_index_version": 0,
                "viewport_captions": "",
            }
            face_enc = meta.get("face_encodings")
            if face_enc:
                chunk_meta["face_encodings"] = face_enc
            store.add_chunk(chunk_id, vec, chunk_meta)
            new_chunks += 1
            try:
                os.unlink(chunk["chunk_path"])
            except OSError:
                pass

    if chunks:
        shutil.rmtree(os.path.dirname(chunks[0]["chunk_path"]), ignore_errors=True)
    click.echo(
        f"Indexed {new_chunks} chunk(s): {rebuilt_chunks} rebuilt, {skipped_chunks} already valid."
    )


def _is_360_cache_current(meta: dict, viewport_prompt: str, projection: str | None) -> bool:
    return (
        meta.get("viewport_index_version") == VIEWPORT_INDEX_VERSION
        and meta.get("viewport_prompt") == viewport_prompt
        and bool(meta.get("best_direction"))
        and meta.get("projection", "equirect") == (projection or "equirect")
        and bool((meta.get("viewport_captions") or "").strip())
    )


def _detect_faces_in_viewport(viewport_path: str, verbose: bool) -> list[list[float]]:
    encodings: list[list[float]] = []
    try:
        from sentrysearch.face_utils import extract_frame, encode_face_array
        frame = extract_frame(viewport_path, time_sec=0.0)
        if frame is not None:
            face_vecs = encode_face_array(frame)
            if face_vecs and verbose:
                click.echo(f"    [face] detected {len(face_vecs)} face(s)", err=True)
            encodings = [v.tolist() for v in face_vecs]
    except Exception:
        if verbose:
            click.echo("    [face] detection skipped", err=True)
    return encodings


_face_recording_available = True


def _compute_sharpness(viewport_path: str) -> float:
    """Laplacian variance; higher = sharper. Returns 0 on failure.

    Keep this dependency-light: OpenCV is not required by autoCut's local-api
    install path, so compute the Laplacian with NumPy instead of cv2.
    """
    try:
        from sentrysearch.face_utils import extract_frame
        import numpy as np

        frame = extract_frame(viewport_path, time_sec=0.0)
        if frame is None:
            return 0.0

        arr = np.asarray(frame, dtype=np.float64)
        if arr.ndim == 3 and arr.shape[2] >= 3:
            gray = 0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]
        elif arr.ndim == 2:
            gray = arr
        else:
            return 0.0

        if gray.shape[0] < 3 or gray.shape[1] < 3:
            return 0.0

        lap = (
            gray[:-2, 1:-1]
            + gray[2:, 1:-1]
            + gray[1:-1, :-2]
            + gray[1:-1, 2:]
            - 4.0 * gray[1:-1, 1:-1]
        )
        return float(lap.var())
    except Exception:
        return 0.0


def _caption_all_360_views(*, embedder, chunk_path: str, projection: str,
                           verbose: bool) -> dict:
    """Render and caption all 4 viewports of a 360 chunk.

    Returns dict with keys: captions, vectors, face_encodings, sharpness
    """
    captions: dict[str, str] = {}
    vectors: dict[str, list[float]] = {}
    face_encodings: dict[str, list[list[float]]] = {}
    sharpness: dict[str, float] = {}
    tmp_paths: list[str] = []
    try:
        for view, yaw in VIEW_TO_YAW.items():
            fd, viewport_path = tempfile.mkstemp(suffix=f"_{view}.mp4")
            os.close(fd)
            tmp_paths.append(viewport_path)
            convert_clip_to_flat(chunk_path, viewport_path, yaw=yaw, projection=projection)
            view_meta: dict = {}
            vec = embedder.embed_video_chunk(viewport_path, metadata=view_meta, verbose=verbose)
            caption = (view_meta.get("caption") or "").strip()
            captions[view] = caption
            if vec is not None:
                vectors[view] = vec
            if verbose:
                click.echo(f"    [360] {view} yaw={yaw}: {caption[:90]}", err=True)
            faces = _detect_faces_in_viewport(viewport_path, verbose)
            if faces:
                face_encodings[view] = faces
            sharpness[view] = _compute_sharpness(viewport_path)
        return {
            "captions": captions, "vectors": vectors,
            "face_encodings": face_encodings, "sharpness": sharpness,
        }
    finally:
        for path in tmp_paths:
            try:
                os.unlink(path)
            except OSError:
                pass


def _choose_best_360_view(embedder, captions_by_view: dict[str, str], prompt: str, verbose: bool) -> str:
    """Select best viewport by prompt similarity alone (no context)."""
    query_vec = embedder.embed_query(prompt, verbose=verbose)
    best_view = "front"
    best_score = float("-inf")
    for view, caption in captions_by_view.items():
        if not caption:
            continue
        caption_vec = embedder.embed_query(caption, verbose=False)
        score = _cosine_similarity(query_vec, caption_vec)
        if score > best_score:
            best_score = score
            best_view = view
    return best_view


def _select_best_360_view_with_context(
    embedder, viewport_prompt: str,
    captions_by_view: dict[str, str],
    vectors: dict[str, list[float]],
    prev_caption: str | None,
    next_caption: str | None,
    sharpness: dict[str, float] | None,
    verbose: bool,
) -> str:
    """Select best viewport using prompt + context + sharpness."""
    query_vec = embedder.embed_query(viewport_prompt, verbose=verbose)
    best_view = "front"
    best_score = float("-inf")
    scores: list[tuple[str, float | None]] = []

    # Min-max normalize sharpness across views
    sharp_norm: dict[str, float] = {}
    if sharpness:
        sv = [s for s in sharpness.values() if s > 0]
        if sv:
            mn, mx = min(sv), max(sv)
            for v in sharpness:
                sharp_norm[v] = (sharpness[v] - mn) / (mx - mn + 1e-8)

    for view, caption in captions_by_view.items():
        if not caption:
            scores.append((view, None))
            continue
        caption_vec = embedder.embed_query(caption, verbose=False)
        prompt_score = _cosine_similarity(query_vec, caption_vec)

        context_bonus = 0.0
        if prev_caption:
            prev_vec = embedder.embed_query(prev_caption, verbose=False)
            context_bonus += 0.15 * _cosine_similarity(caption_vec, prev_vec)
        if next_caption:
            next_vec = embedder.embed_query(next_caption, verbose=False)
            context_bonus += 0.15 * _cosine_similarity(caption_vec, next_vec)

        sharp_bonus = 0.08 * sharp_norm.get(view, 0.0)
        score = prompt_score + context_bonus + sharp_bonus
        scores.append((view, score))
        if score > best_score:
            best_score = score
            best_view = view

    click.echo("    [360] viewport scores:", err=True)
    for view, score in scores:
        marker = " ← selected" if view == best_view and score is not None else ""
        if score is None:
            click.echo(f"      {view:>5}: no caption", err=True)
        else:
            s = sharpness.get(view, 0) if sharpness else 0
            click.echo(f"      {view:>5}: {score:.4f} (sharp={s:.0f}){marker}", err=True)
    return best_view


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    denom_a = sum(x * x for x in a) ** 0.5
    denom_b = sum(x * x for x in b) ** 0.5
    if denom_a == 0 or denom_b == 0:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / (denom_a * denom_b)


def _get_chunk_metadata(store: SentryStore, chunk_id: str) -> dict | None:
    results = store.collection.get(ids=[chunk_id], include=["metadatas"])
    ids = results.get("ids") or []
    if not ids:
        return None
    metadatas = results.get("metadatas") or []
    if not metadatas:
        return {}
    return metadatas[0] or {}


def _load_rows(video_path: str, *, backend: str, model: str | None) -> list[dict]:
    store = SentryStore(backend=backend, model=model)
    collections = [store.collection]

    # Compatibility: older local-api indexes used the vision/caption model name
    # in the collection name.  Current local-api collections are keyed by the
    # embeddings model, but autocut still needs to read rows that were just
    # indexed by a previous version or by an explicit --model run.
    if backend == "local-api":
        seen_names = {store.collection.name}
        for col in store._client.list_collections():  # noqa: SLF001 - compatibility scan
            if col.name.startswith("dashcam_chunks_local_api_") and col.name not in seen_names:
                collections.append(store._client.get_collection(col.name))  # noqa: SLF001
                seen_names.add(col.name)

    rows: list[dict] = []
    seen_ranges: set[tuple[float, float, str]] = set()
    for collection in collections:
        all_data = collection.get(include=["metadatas"])
        for i, _cid in enumerate(all_data.get("ids", [])):
            meta = all_data["metadatas"][i]
            if meta.get("source_file") != video_path:
                continue
            caption = meta.get("caption", "")
            if not caption:
                continue
            key = (float(meta["start_time"]), float(meta["end_time"]), meta["source_file"])
            if key in seen_ranges:
                continue
            seen_ranges.add(key)
            rows.append({
                "idx": i,
                "source_file": meta["source_file"],
                "start_time": key[0],
                "end_time": key[1],
                "caption": caption,
                "is_360": meta.get("is_360", False),
                "best_yaw": meta.get("best_yaw", 0),
                "best_direction": meta.get("best_direction", ""),
                "projection": meta.get("projection", "equirect"),
                "face_encodings": meta.get("face_encodings", ""),
            })
    rows.sort(key=lambda r: r["start_time"])
    return rows


def _normalize_caption_for_dedupe(caption: str) -> str:
    """Normalize captions so repeated speech across nearby chunks compares equal."""
    caption = caption.lower()
    caption = re.sub(r"\b(?:front|right|back|left|auto):", " ", caption)
    caption = re.sub(r"[^\w\s]+", " ", caption, flags=re.UNICODE)
    return re.sub(r"\s+", " ", caption).strip()


def _caption_similarity(a: str, b: str) -> float:
    a_norm = _normalize_caption_for_dedupe(a)
    b_norm = _normalize_caption_for_dedupe(b)
    if not a_norm or not b_norm:
        return 0.0
    if a_norm in b_norm or b_norm in a_norm:
        return 1.0
    return SequenceMatcher(None, a_norm, b_norm).ratio()


def _is_distinct_clip(candidate: dict, selected: list[dict]) -> bool:
    """Reject alternate-universe duplicates of the same spoken moment.

    Indexing uses overlapping 30s chunks (5s overlap).  Speech/caption models can
    describe the same line in adjacent chunks or in different 360 viewports, so a
    top-N request may otherwise return multiple clips with the same words but
    slightly different start times or angles.  Keep only the first/best hit for
    captions that are both temporally close/overlapping and textually near-identical.
    """
    c_start = float(candidate["start_time"])
    c_end = float(candidate["end_time"])
    c_caption = candidate.get("caption", "")
    for existing in selected:
        e_start = float(existing["start_time"])
        e_end = float(existing["end_time"])
        overlaps = c_start < e_end and e_start < c_end
        starts_near = abs(c_start - e_start) < MIN_DISTINCT_CLIP_GAP_SECONDS
        if not (overlaps or starts_near):
            continue
        if _caption_similarity(c_caption, existing.get("caption", "")) >= CAPTION_DUPLICATE_SIMILARITY:
            return False
    return True


def _append_distinct_clip(candidate: dict, selected: list[dict], seen_ranges: set[tuple[float, float]]) -> bool:
    key = (float(candidate["start_time"]), float(candidate["end_time"]))
    if key in seen_ranges or not _is_distinct_clip(candidate, selected):
        return False
    selected.append(candidate)
    seen_ranges.add(key)
    return True


def _select_clips(rows: list[dict], *, prompt: str, count: int,
                  backend: str, model: str | None,
                  quantize: bool | None, verbose: bool) -> list[dict]:
    click.echo(f"\nSelecting top {count} clips for: '{prompt}'...")
    reset_embedder()
    embedder_kwargs: dict = {}
    if backend == "local":
        embedder_kwargs["model"] = model
        embedder_kwargs["quantize"] = quantize
    elif backend == "local-api":
        embedder_kwargs["model"] = model
    elif backend == "qwen-cloud":
        embedder_kwargs["model"] = model
    try:
        get_embedder(backend=backend, **embedder_kwargs)
    except DashScopeDependencyError as exc:
        raise click.ClickException(
            "qwen-cloud backend requires the dashscope SDK.\n\n"
            "Install it in the autoCut root virtualenv with one of:\n"
            "  ./.venv/bin/python -m pip install -e './sentrysearch[qwen-cloud]'\n"
            "  ./.venv/bin/python -m pip install -r requirements-qwen-cloud.txt\n\n"
            f"Original error: {exc}"
        ) from exc

    store = SentryStore(backend=backend, model=model)
    matches = search_footage(prompt, store, n_results=max(count * 4, count), verbose=verbose)
    selected: list[dict] = []
    seen_ranges: set[tuple[float, float]] = set()
    row_lookup = {
        (float(r["start_time"]), float(r["end_time"])): r
        for r in rows
    }
    for match in matches:
        key = (float(match["start_time"]), float(match["end_time"]))
        row = row_lookup.get(key)
        if row is None:
            continue
        _append_distinct_clip(row, selected, seen_ranges)
        if len(selected) >= count:
            break

    if len(selected) < count:
        for row in rows:
            _append_distinct_clip(row, selected, seen_ranges)
            if len(selected) >= count:
                break

    # Search results are ranked by semantic relevance, which can jump backward in
    # the source video. Render the final autocut chronologically so the story does
    # not appear to rewind between selected clips.
    selected.sort(key=lambda s: (float(s["start_time"]), float(s["end_time"])))

    click.secho(f"\nSelected {len(selected)} clips in timeline order:", fg="green", bold=True)
    for s in selected:
        click.echo(f"  [{_fmt_time(s['start_time'])}-{_fmt_time(s['end_time'])}] {s['caption'][:100]}")
    return selected


def _copy_clip_with_times(row: dict, start_time: float, end_time: float) -> dict:
    adjusted = dict(row)
    adjusted["start_time"] = float(start_time)
    adjusted["end_time"] = float(end_time)
    return adjusted


def _dedupe_render_ranges(selected: list[dict], *, padding: float = RENDER_CLIP_PADDING_SECONDS) -> list[dict]:
    """Return timeline clips whose final padded render windows do not overlap.

    Indexing uses overlapping chunks, and render trimming also adds padding.  If two
    adjacent hits are close together, the final concatenated video can replay the
    same few seconds with a different 360 viewport.  Trim the shared boundary before
    calling trim_clip so internal cut points remain monotonic even after padding.
    """
    if not selected:
        return []

    adjusted = [_copy_clip_with_times(s, float(s["start_time"]), float(s["end_time"])) for s in selected]
    adjusted.sort(key=lambda s: (float(s["start_time"]), float(s["end_time"])))

    for prev, cur in zip(adjusted, adjusted[1:]):
        prev_start = float(prev["start_time"])
        prev_end = float(prev["end_time"])
        cur_start = float(cur["start_time"])
        cur_end = float(cur["end_time"])

        # trim_clip adds padding to both sides, so even back-to-back windows would
        # overlap by 2*padding unless the raw boundary is opened by that amount.
        padded_overlap = (prev_end + padding) - max(0.0, cur_start - padding)
        if padded_overlap <= 0:
            continue

        trim_from_prev = min(padded_overlap / 2.0, max(0.0, prev_end - prev_start))
        trim_from_cur = min(padded_overlap - trim_from_prev, max(0.0, cur_end - cur_start))
        remaining = padded_overlap - trim_from_prev - trim_from_cur
        if remaining > 1e-6:
            trim_more_prev = min(remaining, max(0.0, (prev_end - prev_start) - trim_from_prev))
            trim_from_prev += trim_more_prev
            remaining -= trim_more_prev
            trim_from_cur += min(remaining, max(0.0, (cur_end - cur_start) - trim_from_cur))

        prev["end_time"] = prev_end - trim_from_prev
        cur["start_time"] = cur_start + trim_from_cur

        if prev["end_time"] < prev["start_time"]:
            prev["end_time"] = prev["start_time"]
        if cur["start_time"] > cur["end_time"]:
            cur["start_time"] = cur["end_time"]

    return [s for s in adjusted if float(s["end_time"]) > float(s["start_time"])]


def _render_autocut(selected: list[dict], *, source_video: str, output_path: str,
                    hq_source: str | None, hq_dir: str | None, view: str,
                    yaw: float | None, detected_projection: str | None) -> None:
    selected = _dedupe_render_ranges(selected)
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
                    padding=RENDER_CLIP_PADDING_SECONDS,
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
                    padding=RENDER_CLIP_PADDING_SECONDS,
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
