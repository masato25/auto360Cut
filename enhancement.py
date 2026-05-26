"""Preset-based ffmpeg enhancement helpers for autoCut outputs.

The module intentionally keeps the first version deterministic and local:
no ML model downloads, no scene analysis side effects.  It builds an explicit
plan JSON so users can see exactly which filters/codec settings were used.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ENHANCE_PRESETS = ("none", "light", "vivid", "cinematic")


@dataclass(frozen=True)
class EnhanceSettings:
    preset: str
    video_filter: str | None
    audio_filter: str | None
    video_codec: str
    crf: str
    preset_speed: str
    audio_bitrate: str
    description: str


_PRESETS: dict[str, EnhanceSettings] = {
    "none": EnhanceSettings(
        preset="none",
        video_filter=None,
        audio_filter=None,
        video_codec="libx264",
        crf="23",
        preset_speed="fast",
        audio_bitrate="128k",
        description="No enhancement pass.",
    ),
    "light": EnhanceSettings(
        preset="light",
        video_filter="eq=contrast=1.04:saturation=1.08:brightness=0.01,unsharp=5:5:0.45:3:3:0.2",
        audio_filter="loudnorm=I=-16:TP=-1.5:LRA=11",
        video_codec="libx264",
        crf="21",
        preset_speed="medium",
        audio_bitrate="160k",
        description="Subtle contrast/saturation/sharpening plus loudness normalization.",
    ),
    "vivid": EnhanceSettings(
        preset="vivid",
        video_filter="eq=contrast=1.08:saturation=1.18:brightness=0.015,unsharp=5:5:0.65:3:3:0.25",
        audio_filter="loudnorm=I=-16:TP=-1.5:LRA=10",
        video_codec="libx264",
        crf="20",
        preset_speed="medium",
        audio_bitrate="192k",
        description="Punchier colors and sharpening for travel/action footage.",
    ),
    "cinematic": EnhanceSettings(
        preset="cinematic",
        video_filter="eq=contrast=1.10:saturation=1.05:brightness=-0.005,unsharp=5:5:0.35:3:3:0.15",
        audio_filter="highpass=f=80,loudnorm=I=-16:TP=-1.5:LRA=12",
        video_codec="libx264",
        crf="20",
        preset_speed="medium",
        audio_bitrate="192k",
        description="Slightly deeper contrast with restrained saturation and cleaned voice/music lows.",
    ),
}


def get_enhance_settings(preset: str) -> EnhanceSettings:
    normalized = (preset or "none").lower()
    if normalized not in _PRESETS:
        choices = ", ".join(ENHANCE_PRESETS)
        raise ValueError(f"unknown enhance preset: {preset}; choose one of: {choices}")
    return _PRESETS[normalized]


def build_enhance_plan(*, preset: str, input_path: str, output_path: str,
                       context: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = get_enhance_settings(preset)
    plan: dict[str, Any] = {
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "context": context,
        "input": os.path.abspath(input_path),
        "output": os.path.abspath(output_path),
        "settings": asdict(settings),
    }
    if extra:
        plan["extra"] = extra
    return plan


def write_enhance_plan(plan: dict[str, Any], plan_path: str | None = None) -> str:
    output = plan_path or f"{plan['output']}.enhance-plan.json"
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return output


def ffmpeg_enhance_args(settings: EnhanceSettings) -> list[str]:
    args: list[str] = []
    if settings.video_filter:
        args.extend(["-vf", settings.video_filter])
    if settings.audio_filter:
        args.extend(["-af", settings.audio_filter])
    args.extend([
        "-c:v", settings.video_codec,
        "-preset", settings.preset_speed,
        "-crf", settings.crf,
        "-c:a", "aac",
        "-b:a", settings.audio_bitrate,
        "-ar", "48000",
        "-ac", "2",
        "-movflags", "+faststart",
    ])
    return args


def apply_enhancement(ffmpeg: str, input_path: str, output_path: str, *, preset: str) -> None:
    settings = get_enhance_settings(preset)
    if settings.preset == "none":
        return
    tmp_output = f"{output_path}.enhance.tmp.mp4"
    try:
        result = subprocess.run(
            [ffmpeg, "-y", "-i", input_path, *ffmpeg_enhance_args(settings), tmp_output],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not os.path.isfile(tmp_output):
            raise RuntimeError(result.stderr.strip() or "ffmpeg enhancement failed")
        os.replace(tmp_output, output_path)
    finally:
        try:
            os.unlink(tmp_output)
        except OSError:
            pass
