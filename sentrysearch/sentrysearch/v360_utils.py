"""360 video detection and flat conversion utilities."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile


def _get_ffprobe() -> str:
    """Find the ffprobe executable."""
    if sys.platform == "darwin":
        candidates = [
            "/usr/local/bin/ffprobe",
            "/opt/homebrew/bin/ffprobe",
            "/usr/bin/ffprobe",
        ]
        for c in candidates:
            if os.path.isfile(c):
                return c
    return "ffprobe"


def _get_ffmpeg() -> str:
    """Find the ffmpeg executable."""
    if sys.platform == "darwin":
        candidates = [
            "/usr/local/bin/ffmpeg",
            "/opt/homebrew/bin/ffmpeg",
            "/usr/bin/ffmpeg",
        ]
        for c in candidates:
            if os.path.isfile(c):
                return c
    return "ffmpeg"


def _has_spherical_side_data(video_path: str) -> bool:
    """Check if the video has spherical side_data (standard equirect)."""
    try:
        result = subprocess.run(
            [_get_ffprobe(), "-v", "error",
             "-show_entries", "stream=side_data",
             "-of", "default=noprint_wrappers=1",
             video_path],
            capture_output=True, text=True, timeout=30,
        )
        return "spherical" in result.stdout.lower()
    except Exception:
        return False


def _has_insta360_handler(video_path: str) -> bool:
    """Check if the video has Insta360 handler_name (INS)."""
    try:
        result = subprocess.run(
            [_get_ffprobe(), "-v", "error",
             "-show_entries", "stream_tags=handler_name",
             "-of", "default=noprint_wrappers=1",
             video_path],
            capture_output=True, text=True, timeout=30,
        )
        return "INS" in result.stdout
    except Exception:
        return False


def _is_2_1_aspect_ratio(video_path: str) -> bool:
    """Check if video resolution is exactly 2:1."""
    try:
        result = subprocess.run(
            [_get_ffprobe(), "-v", "error",
             "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-of", "csv=p=0",
             video_path],
            capture_output=True, text=True, timeout=30,
        )
        parts = result.stdout.strip().split(",")
        if len(parts) >= 2:
            w, h = int(parts[0]), int(parts[1])
            return h > 0 and w / h == 2.0
        return False
    except Exception:
        return False


def detect_360_projection(video_path: str) -> str | None:
    """Detect 360 projection type.

    Returns ``"equirect"``, ``"dfisheye"``, or ``None``.
    """
    if _has_spherical_side_data(video_path):
        return "equirect"
    if not _is_2_1_aspect_ratio(video_path):
        return None
    if _has_insta360_handler(video_path):
        return "dfisheye"
    return "equirect"


def convert_clip_to_flat(
    input_path: str,
    output_path: str,
    yaw: float = 0,
    projection: str = "equirect",
) -> str:
    """Convert a 360 clip to a natural-looking 16:9 flat viewport.

    ``v360`` otherwise keeps the source frame dimensions. For 360 sources this
    is commonly 2:1, which makes the final flat view look squeezed/narrow when
    played as a normal video. Force a standard 1280x720 viewport and use a
    moderate 95° horizontal FOV, which is closer to a natural road/front view
    than the previous very-wide 110° crop.
    """
    width = 1280
    height = 720
    h_fov = 95
    v_fov = 60

    if projection == "dfisheye":
        filter_str = (
            f"v360=dfisheye:flat:yaw={yaw}:pitch=0:roll=0:"
            f"ih_fov=200:iv_fov=200:h_fov={h_fov}:v_fov={v_fov}:"
            f"w={width}:h={height}"
        )
    else:
        filter_str = (
            f"v360=equirect:flat:yaw={yaw}:pitch=0:roll=0:"
            f"h_fov={h_fov}:v_fov={v_fov}:w={width}:h={height}"
        )

    result = subprocess.run(
        [
            _get_ffmpeg(), "-y",
            "-i", input_path,
            "-vf", filter_str,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-c:a", "aac",
            "-b:a", "128k",
            output_path,
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or not os.path.isfile(output_path):
        raise RuntimeError(
            f"360-to-flat conversion failed: {result.stderr.strip()}"
        )
    return output_path
