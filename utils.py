"""Shared utilities used by autocut.py and autocut_script.py."""

from __future__ import annotations

import os
import re


def fmt_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def resolve_hq_source(
    video_path: str,
    hq_source: str | None = None,
    hq_dir: str | None = None,
) -> str | None:
    """Locate the high-quality version of video_path.

    Priority: explicit hq_source > hq_dir timestamp+seq matching > LRV sibling lookup.
    Returns None when not found; callers that must have an HQ file should raise.
    """
    if hq_source:
        return os.path.abspath(os.path.expanduser(hq_source))

    if hq_dir:
        directory = os.path.abspath(os.path.expanduser(hq_dir))
        base = os.path.basename(video_path)
        ts_match = re.search(r"(\d{8}_\d{6})", base)
        timestamp = ts_match.group(1) if ts_match else None
        seq_match = re.search(r"_(\d{3})(?:\.[^.]+)?$", base)
        seq = seq_match.group(1) if seq_match else None

        candidates: list[str] = []
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
            path = os.path.join(directory, name)
            if os.path.isfile(path):
                return path

        if timestamp:
            for entry in sorted(os.listdir(directory)):
                if (
                    entry.startswith(f"VID_{timestamp}")
                    and entry.lower().endswith((".mp4", ".mov", ".m4v"))
                    and not entry.startswith("._")
                ):
                    return os.path.join(directory, entry)

        return None

    # LRV sibling: look for a matching HQ file in the same directory
    if video_path.lower().endswith(".lrv"):
        base = os.path.basename(video_path)
        ts_match = re.search(r"(\d{8}_\d{6})", base)
        if ts_match:
            ts = ts_match.group(1)
            src_dir = os.path.dirname(video_path) or "."
            for f in sorted(os.listdir(src_dir)):
                if ts in f and f.lower().endswith((".mp4", ".mov")) and not f.startswith("._"):
                    return os.path.join(src_dir, f)

    return None
