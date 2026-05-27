"""Preset-based ffmpeg enhancement helpers for autoCut outputs.

The module intentionally keeps the first version deterministic and local:
no ML model downloads, no scene analysis side effects.  It builds an explicit
plan JSON so users can see exactly which filters/codec settings were used.

Two-pass loudnorm
-----------------
When an audio filter contains ``loudnorm``, a *measurement* pass runs first
(``loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json``) to collect the actual
integrated loudness, true-peak, LRA and offset.  Those measured values are then
fed back into the real encode pass so the normalisation is sample-accurate
rather than estimated — especially important when clips from different cameras
or audio sources are concatenated.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ENHANCE_PRESETS = ("none", "light", "vivid", "cinematic")


# ── settings dataclass ────────────────────────────────────────────────
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


# ── preset registry ───────────────────────────────────────────────────
_PRESETS: dict[str, EnhanceSettings] = {
    "none": EnhanceSettings(
        preset="none",
        video_filter=None,
        audio_filter="loudnorm=I=-16:TP=-1.5:LRA=11",
        video_codec="libx264",
        crf="23",
        preset_speed="fast",
        audio_bitrate="128k",
        description="Audio loudness normalisation only (no video filter).",
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


# ── public helpers ────────────────────────────────────────────────────
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


# ── ffmpeg arg builders ───────────────────────────────────────────────
def _loudnorm_measure_args(audio_filter: str) -> list[str]:
    """First-pass loudnorm: measure only, print JSON stats to stderr.

    Extracts the target I, TP, LRA from *audio_filter* so the measurement
    pass uses the same targets as the real encode.
    """
    target_m = _LOUDNORM_TARGET_RE.search(audio_filter)
    i = target_m.group(1) if target_m else "-16"
    tp = target_m.group(2) if target_m else "-1.5"
    lra = target_m.group(3) if target_m else "11"
    return [
        "-af", f"loudnorm=I={i}:TP={tp}:LRA={lra}:print_format=json",
        "-f", "null", "-",
    ]


_LOUDNORM_STATS_RE = re.compile(
    r'"input_i"\s*:\s*"([\d.\-]+)".*'
    r'"input_tp"\s*:\s*"([\d.\-]+)".*'
    r'"input_lra"\s*:\s*"([\d.\-]+)".*'
    r'"input_thresh"\s*:\s*"([\d.\-]+)".*'
    r'"target_offset"\s*:\s*"([\d.\-]+)"',
    re.DOTALL,
)


def _measure_loudnorm(ffmpeg: str, input_path: str,
                     audio_filter: str) -> dict[str, str] | None:
    """Run a null-encode to collect loudnorm statistics.

    Uses the same I/TP/LRA targets as *audio_filter* so the measurement
    corresponds to what the actual encode will use.

    Returns a dict with keys ``measured_I``, ``measured_TP``, ``measured_LRA``,
    ``measured_thresh``, ``measured_offset``, or ``None`` if the measurement
    pass failed (e.g. no audio stream).
    """
    result = subprocess.run(
        [ffmpeg, "-y", "-i", input_path, *_loudnorm_measure_args(audio_filter)],
        capture_output=True, text=True,
    )
    # loudnorm JSON is printed to stderr
    combined = result.stderr + result.stdout
    m = _LOUDNORM_STATS_RE.search(combined)
    if not m:
        return None
    return {
        "measured_I": m.group(1),
        "measured_TP": m.group(2),
        "measured_LRA": m.group(3),
        "measured_thresh": m.group(4),
        "measured_offset": m.group(5),
    }


_LOUDNORM_TARGET_RE = re.compile(r"loudnorm=I=([^:]+):TP=([^:]+):LRA=([^:,\]]+)")


def _build_loudnorm_filter(audio_filter: str, measured: dict[str, str]) -> str:
    """Replace the loudnorm portion of an audio filter chain with measured values.

    Preserves the original target I, TP and LRA from the filter so the second
    pass uses the same targets as the measurement pass.
    """
    target_m = _LOUDNORM_TARGET_RE.search(audio_filter)
    i_target = target_m.group(1) if target_m else "-16"
    tp_target = target_m.group(2) if target_m else "-1.5"
    lra_target = target_m.group(3) if target_m else "11"

    return re.sub(
        r"loudnorm=I=[^:]+:TP=[^:]+:LRA=[^:,\]]+",
        (
            f"loudnorm=I={i_target}:TP={tp_target}:LRA={lra_target}"
            f":measured_I={measured['measured_I']}"
            f":measured_TP={measured['measured_TP']}"
            f":measured_LRA={measured['measured_LRA']}"
            f":measured_thresh={measured['measured_thresh']}"
            f":measured_offset={measured['measured_offset']}"
            f":print_format=summary"
        ),
        audio_filter,
    )


def ffmpeg_enhance_args(settings: EnhanceSettings,
                        measured: dict[str, str] | None = None) -> list[str]:
    """Build the ffmpeg argument list for an enhancement encode.

    When *measured* is provided (from a prior two-pass loudnorm measurement),
    the loudnorm filter in *settings.audio_filter* is rewritten to use
    measured values for sample-accurate normalisation.
    """
    args: list[str] = []
    if settings.video_filter:
        args.extend(["-vf", settings.video_filter])
    af = settings.audio_filter
    if af and measured:
        af = _build_loudnorm_filter(af, measured)
    if af:
        args.extend(["-af", af])
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


# ── main entry point ──────────────────────────────────────────────────
def apply_enhancement(ffmpeg: str, input_path: str, output_path: str, *,
                      preset: str) -> None:
    """Apply a preset enhancement pass to *input_path*, atomically replacing
    *output_path*.

    When the preset includes a ``loudnorm`` audio filter, a two-pass workflow
    is used: a measurement pass collects the true integrated loudness of the
    file, and the encode pass uses those measured values for accurate
    normalisation.
    """
    settings = get_enhance_settings(preset)

    measured: dict[str, str] | None = None
    if settings.audio_filter and "loudnorm" in settings.audio_filter:
        measured = _measure_loudnorm(ffmpeg, input_path, settings.audio_filter)
        if measured is None:
            # Audio stream missing or measurement failed — fall back to
            # single-pass loudnorm (still better than nothing).
            pass

    tmp_output = f"{output_path}.enhance.tmp.mp4"
    try:
        result = subprocess.run(
            [ffmpeg, "-y", "-i", input_path,
             *ffmpeg_enhance_args(settings, measured=measured), tmp_output],
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


# ── convenience: audio-only normalisation (no video re-encode overhead) ──
def apply_audio_normalize(ffmpeg: str, input_path: str,
                          output_path: str) -> None:
    """Minimal audio loudness normalisation pass using two-pass loudnorm.

    Video is stream-copied so this is fast and lossless for the picture.
    Useful as a "safety net" after concat even when ``--enhance none``.
    """
    measured = _measure_loudnorm(ffmpeg, input_path, af)
    af = "loudnorm=I=-16:TP=-1.5:LRA=11"
    if measured:
        af = _build_loudnorm_filter(af, measured)

    tmp_output = f"{output_path}.audio-norm.tmp.mp4"
    try:
        result = subprocess.run(
            [ffmpeg, "-y", "-i", input_path,
             "-af", af,
             "-c:v", "copy",
             "-c:a", "aac",
             "-b:a", "128k",
             "-ar", "48000",
             "-ac", "2",
             "-movflags", "+faststart",
             tmp_output],
            capture_output=True, text=True,
        )
        if result.returncode != 0 or not os.path.isfile(tmp_output):
            raise RuntimeError(result.stderr.strip() or "ffmpeg audio normalize failed")
        os.replace(tmp_output, output_path)
    finally:
        try:
            os.unlink(tmp_output)
        except OSError:
            pass
