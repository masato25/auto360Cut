#!/usr/bin/env python3
"""
360 Video Converter - Core conversion engine
Supports .insv (Insta360) and 360 .mp4 (equirectangular) inputs
Outputs: Raw Dual Lens, Cubemap 3x2, Dual Fisheye, Tiny Planet
"""

import subprocess
import json
import os
import sys
import shutil
import tempfile
from pathlib import Path
from typing import Optional, Any

# ─── FFmpeg probe ──────────────────────────────────────────────────

def probe_video(input_path: str) -> Optional[dict]:
    """Use ffprobe to get video stream info."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-show_format",
        input_path
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return None
        return json.loads(result.stdout)
    except Exception:
        return None


def detect_input_type(input_path: str) -> str:
    """
    Detect input type by extension and content.
    Returns 'insv' or 'equirect'.
    """
    ext = Path(input_path).suffix.lower()
    if ext == ".insv":
        return "insv"

    # For .mp4, try to determine if it's equirectangular 360
    info = probe_video(input_path)
    if info:
        for stream in info.get("streams", []):
            if stream.get("codec_type") == "video":
                side_data_list = stream.get("side_data_list", [])
                for sd in side_data_list:
                    sd_type = sd.get("side_data_type", "")
                    if "spherical" in sd_type.lower() or "equirect" in sd_type.lower():
                        return "equirect"
                disposition = stream.get("disposition", {})
                if disposition.get("attached_pic") == 1:
                    continue
                tags = stream.get("tags", {})
                if tags:
                    for key, val in tags.items():
                        key_lower = key.lower()
                        if any(kw in key_lower for kw in ["spherical", "equirect", "360", "stereo"]):
                            return "equirect"

    if ext == ".mp4":
        return "equirect"

    return "unknown"


# ─── Supported conversions ─────────────────────────────────────────

def get_available_outputs(input_type: str) -> list[dict]:
    """Return list of output styles available for this input type."""
    outputs = {
        "insv": [
            {
                "id": "dual_lens",
                "label": "雙鏡頭 Dual Lens（Raw）",
                "description": "直接抽出兩顆鏡頭畫面左右並排，不縫合"
            },
        ],
        "equirect": [
            {
                "id": "cubemap",
                "label": "六宮格 Cubemap 3×2",
                "description": "360 影片展開為立方體六面圖"
            },
            {
                "id": "dual_fisheye",
                "label": "雙魚眼 Dual Fisheye（2宮格）",
                "description": "已縫合全景重新轉成雙魚眼外觀"
            },
            {
                "id": "tiny_planet",
                "label": "小行星 Tiny Planet",
                "description": "360 全景轉為立體投影小行星視角"
            },
        ]
    }
    return outputs.get(input_type, [])


# ─── Encoder helper ────────────────────────────────────────────────

def _get_encoder_params(quality: str) -> tuple[list[str], list[str]]:
    """
    Return (video_codec_args, audio_codec_args) based on platform and quality.
    macOS: h264_videotoolbox with bitrate.
    Other: libx264 with CRF.
    """
    bitrate_map = {"high": "18M", "medium": "14M", "low": "10M"}
    crf_map = {"high": "18", "medium": "23", "low": "28"}

    if sys.platform == "darwin":
        video_args = [
            "-c:v", "h264_videotoolbox",
            "-b:v", bitrate_map.get(quality, "14M"),
        ]
    else:
        video_args = [
            "-c:v", "libx264",
            "-crf", crf_map.get(quality, "23"),
            "-preset", "medium",
        ]

    audio_args = ["-c:a", "aac", "-b:a", "192k"]
    return video_args, audio_args


# ─── Shared utilities ──────────────────────────────────────────────

def _parse_size(size: str, default: tuple[int, int]) -> tuple[int, int]:
    """Parse a WIDTHxHEIGHT string and fall back to a sane default."""
    try:
        w, h = str(size).lower().split("x", 1)
        return int(w), int(h)
    except (AttributeError, TypeError, ValueError):
        return default


def _coerce_param(params: dict[str, Any], key: str, default: Any, cast):
    """Read a GUI/CLI parameter and cast it safely."""
    value = params.get(key, default)
    try:
        return cast(value)
    except (TypeError, ValueError):
        return default


def _run_ffmpeg(cmd: list[str], progress_callback=None) -> tuple[bool, str]:
    """Run ffmpeg command and return (success, message)."""
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        output_lines = []
        for line in iter(process.stdout.readline, ''):
            output_lines.append(line)
            if progress_callback and "time=" in line:
                try:
                    time_str = line.split("time=")[1].split()[0]
                    parts = time_str.split(":")
                    if len(parts) == 3:
                        secs = int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
                        progress_callback(secs)
                except (IndexError, ValueError):
                    pass

        process.wait()
        if process.returncode == 0:
            return True, "Conversion completed"
        else:
            stderr_text = "".join(output_lines[-10:])
            return False, f"FFmpeg error: {stderr_text}"
    except FileNotFoundError:
        return False, "FFmpeg not found. Please install FFmpeg first."
    except Exception as e:
        return False, f"Unexpected error: {str(e)}"


# ─── Conversion implementations ────────────────────────────────────

def convert_insv_to_raw_dual_lens(
    input_path: str,
    output_path: str,
    quality: str = "high",
    progress_callback=None
) -> tuple[bool, str]:
    """
    Extract raw dual-lens streams from .insv, scale and hstack side-by-side.
    No stitching — this is the raw lens preview.
    Output: 3840x1920 (two 1920x1920 frames side-by-side).
    """
    video_args, audio_args = _get_encoder_params(quality)

    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-filter_complex",
        "[0:v:0]scale=1920:1920[v0];[0:v:1]scale=1920:1920[v1];[v0][v1]hstack=inputs=2[v]",
        "-map", "[v]",
        "-map", "0:a?",
        "-pix_fmt", "yuv420p",
    ]
    cmd.extend(video_args)
    cmd.extend(audio_args)
    cmd.append(output_path)

    return _run_ffmpeg(cmd, progress_callback)


def convert_to_cubemap(
    input_path: str,
    output_path: str,
    size: str = "2880x1920",
    quality: str = "high",
    progress_callback=None
) -> tuple[bool, str]:
    """
    Convert equirectangular 360 MP4 to cubemap 3x2 layout.
    Default: 2880x1920 (6 faces arranged 3 columns × 2 rows).
    """
    video_args, audio_args = _get_encoder_params(quality)
    w, h = _parse_size(size, (2880, 1920))

    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-vf",
        f"v360=input=equirect:output=c3x2:w={w}:h={h}:interp=lanczos",
        "-pix_fmt", "yuv420p",
    ]
    cmd.extend(video_args)
    cmd.extend(audio_args)
    cmd.append(output_path)

    return _run_ffmpeg(cmd, progress_callback)


def convert_to_dual_fisheye(
    input_path: str,
    output_path: str,
    size: str = "3840x1920",
    quality: str = "high",
    progress_callback=None
) -> tuple[bool, str]:
    """
    Convert equirectangular 360 MP4 to dual fisheye (2-panel side-by-side).
    Uses the v360 filter with dfisheye output projection.
    Default: 3840x1920.
    """
    video_args, audio_args = _get_encoder_params(quality)
    w, h = _parse_size(size, (3840, 1920))

    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-vf",
        f"v360=input=equirect:output=dfisheye:w={w}:h={h}:interp=lanczos",
        "-pix_fmt", "yuv420p",
    ]
    cmd.extend(video_args)
    cmd.extend(audio_args)
    cmd.append(output_path)

    return _run_ffmpeg(cmd, progress_callback)


def convert_to_tiny_planet(
    input_path: str,
    output_path: str,
    size: str = "1920x1920",
    pitch: float = -90.0,
    quality: str = "high",
    progress_callback=None
) -> tuple[bool, str]:
    """
    Convert equirectangular 360 MP4 to tiny planet (stereographic projection).
    Default: pitch=-90 (looking down), d_fov=250 for the classic tiny-planet look.
    Output: 1920x1920 square.
    """
    video_args, audio_args = _get_encoder_params(quality)
    w, h = _parse_size(size, (1920, 1920))

    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-vf",
        f"v360=input=equirect:output=sg:w={w}:h={h}:pitch={pitch}:d_fov=250:interp=lanczos",
        "-pix_fmt", "yuv420p",
    ]
    cmd.extend(video_args)
    cmd.extend(audio_args)
    cmd.append(output_path)

    return _run_ffmpeg(cmd, progress_callback)


# ─── High-level conversion dispatch ────────────────────────────────

def run_conversion(
    input_path: str,
    output_style: str,
    output_dir: str,
    quality: str = "high",
    params: Optional[dict] = None,
    progress_callback=None
) -> tuple[bool, str, str]:
    """
    Run a conversion based on input file and desired output style.
    Returns (success, message, output_file_path).
    """
    params = params or {}
    os.makedirs(output_dir, exist_ok=True)

    input_stem = Path(input_path).stem
    output_ext = ".mp4"

    style_map = {
        "dual_lens": {
            "func": convert_insv_to_raw_dual_lens,
            "suffix": "_dual_lens_side_by_side"
        },
        "cubemap": {
            "func": convert_to_cubemap,
            "suffix": "_cubemap_3x2"
        },
        "dual_fisheye": {
            "func": convert_to_dual_fisheye,
            "suffix": "_dual_fisheye"
        },
        "tiny_planet": {
            "func": convert_to_tiny_planet,
            "suffix": "_tiny_planet"
        },
    }

    style = style_map.get(output_style)
    if not style:
        return False, f"Unknown output style: {output_style}", ""

    output_filename = f"{input_stem}{style['suffix']}_{_size_suffix(params, output_style)}{output_ext}"
    output_path = os.path.join(output_dir, output_filename)

    func_kwargs: dict[str, Any] = {
        "quality": quality,
        "progress_callback": progress_callback,
    }

    if output_style == "dual_lens":
        # Raw dual lens from .insv — no extra params
        pass
    elif output_style == "cubemap":
        func_kwargs["size"] = _coerce_param(params, "size", "2880x1920", str)
    elif output_style == "dual_fisheye":
        func_kwargs["size"] = _coerce_param(params, "size", "3840x1920", str)
    elif output_style == "tiny_planet":
        func_kwargs["size"] = _coerce_param(params, "size", "1920x1920", str)
        func_kwargs["pitch"] = _coerce_param(params, "pitch", -90.0, float)

    success, message = style["func"](
        input_path, output_path, **func_kwargs
    )

    if not success and os.path.exists(output_path):
        os.remove(output_path)

    return success, message, output_path if success else ""


def _size_suffix(params: dict, style: str) -> str:
    """Build a short size suffix for the output filename, e.g. '2880x1920'."""
    size = params.get("size", "")
    if size:
        return size
    defaults = {
        "dual_lens": "3840x1920",
        "cubemap": "2880x1920",
        "dual_fisheye": "3840x1920",
        "tiny_planet": "1920x1920",
    }
    return defaults.get(style, "")


# ─── CLI entry point ────────────────────────────────────────────────

def cli():
    import argparse

    parser = argparse.ArgumentParser(
        description="360 Video Converter - Convert insv/360 MP4 to various formats",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s input.insv dual_lens -o ./output
  %(prog)s input.mp4 cubemap -o ./output
  %(prog)s input.mp4 dual_fisheye --size 3840x1920
  %(prog)s input.mp4 tiny_planet --size 1920x1920
        """
    )
    parser.add_argument("input", help="Input video file (.insv or .mp4)")
    parser.add_argument("style", nargs="?",
                        choices=["dual_lens", "cubemap", "dual_fisheye", "tiny_planet"],
                        help="Output style (auto-detects available styles if omitted)")
    parser.add_argument("-o", "--output-dir", default="./output",
                        help="Output directory (default: ./output)")
    parser.add_argument("-q", "--quality", choices=["high", "medium", "low"],
                        default="high", help="Encoding quality (default: high)")
    parser.add_argument("--size", help="Output resolution (e.g. 2880x1920, 3840x1920, 1920x1920)")
    parser.add_argument("--pitch", type=float, default=-90.0, help="Pitch for tiny planet (default: -90)")
    parser.add_argument("--list-styles", action="store_true",
                        help="List available output styles for the input file")

    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"❌ Error: Input file not found: {args.input}")
        return 1

    input_type = detect_input_type(args.input)
    if input_type == "unknown":
        print(f"❌ Error: Unknown input format: {args.input}")
        return 1

    print(f"📁 Input type detected: {input_type.upper()}")

    available = get_available_outputs(input_type)
    if not available:
        print(f"❌ Error: No output styles available for {input_type.upper()} files.")
        return 1

    if args.list_styles:
        print(f"\n📋 Available output styles for {input_type.upper()}:\n")
        for s in available:
            print(f"  {s['id']:25s} {s['label']}")
            print(f"  {'':25s} {s['description']}")
            print()
        return 0

    if not args.style:
        print("❌ Error: Please specify an output style. Use --list-styles to see options.")
        return 1

    if args.style not in [s["id"] for s in available]:
        print(f"❌ Error: Style '{args.style}' is not available for {input_type.upper()} files.")
        print(f"   Available: {', '.join(s['id'] for s in available)}")
        return 1

    params = {}
    if args.size:
        params["size"] = args.size
    if args.style == "tiny_planet":
        params["pitch"] = args.pitch

    print(f"⚙️  Converting {args.input} ...")
    print(f"   Style: {args.style}")
    print(f"   Output: {args.output_dir}/")
    print()

    success, message, output_path = run_conversion(
        args.input, args.style, args.output_dir,
        quality=args.quality, params=params
    )

    if success:
        print(f"✅ Conversion completed!")
        print(f"📄 Output: {output_path}")
        return 0
    else:
        print(f"❌ Conversion failed: {message}")
        return 1


if __name__ == "__main__":
    exit(cli())
