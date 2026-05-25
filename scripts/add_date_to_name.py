#!/usr/bin/env python3
"""
Extract creation date from media files (images/videos) and append to filename.

For JPEG images: reads EXIF DateTimeOriginal or DateTime
For videos: reads creation_time from MP4/MOV metadata via ffprobe
For all files: tries filename pattern matching (Insta360: VID_YYYYMMDD_HHMMSS*)
Fallback: uses file birth time (macOS st_birthtime) or modification time

Usage:
    python scripts/add_date_to_name.py <file_or_directory> [--dry-run] [--recursive] [--force]
"""

import os
import sys
import json
import struct
import subprocess
import argparse
import re
from pathlib import Path
from datetime import datetime


# ═══════════════════════════════════════════════════════════════
# JPEG EXIF Reader (pure Python, no dependencies)
# ═══════════════════════════════════════════════════════════════

EXIF_DATETIME = 0x0132
EXIF_DATETIME_ORIGINAL = 0x9003
EXIF_DATETIME_DIGITIZED = 0x9004
EXIF_EXIF_IFD = 0x8769


def _read_exif_date_jpeg(filepath):
    """Extract date string from JPEG EXIF (DateTimeOriginal > DateTimeDigitized > DateTime)."""
    with open(filepath, 'rb') as f:
        data = f.read()

    # Find APP1 marker (0xFFE1)
    app1_offsets = []
    i = 0
    while True:
        idx = data.find(b'\xff\xe1', i)
        if idx < 0:
            break
        app1_offsets.append(idx)
        i = idx + 2

    for app1_start in app1_offsets:
        result = _parse_exif_from_app1(data, app1_start)
        if result:
            return result
    return None


def _parse_exif_from_app1(data, app1_start):
    """Parse EXIF data from a JPEG APP1 segment."""
    if app1_start + 4 > len(data):
        return None

    app1_len = struct.unpack('>H', data[app1_start + 2:app1_start + 4])[0]
    app1_end = app1_start + 2 + app1_len
    if app1_end > len(data):
        return None

    exif_header_start = app1_start + 4
    if data[exif_header_start:exif_header_start + 6] != b'Exif\x00\x00':
        return None

    tiff_start = exif_header_start + 6
    return _parse_tiff_exif(data, tiff_start)


def _parse_tiff_exif(data, tiff_start):
    """Parse TIFF/EXIF structure and return date string."""
    if tiff_start + 8 > len(data):
        return None

    byte_order = data[tiff_start:tiff_start + 2]
    if byte_order == b'II':
        endian = '<'
    elif byte_order == b'MM':
        endian = '>'
    else:
        return None

    magic = struct.unpack(endian + 'H', data[tiff_start + 2:tiff_start + 4])[0]
    if magic != 42:
        return None

    ifd_offset = struct.unpack(endian + 'I', data[tiff_start + 4:tiff_start + 8])[0]
    ifd0_addr = tiff_start + ifd_offset

    tags0, _ = _read_ifd(data, tiff_start, ifd0_addr, endian)

    date_str = None
    if EXIF_DATETIME in tags0:
        date_str = tags0[EXIF_DATETIME]

    exif_ifd_offset_val = tags0.get(EXIF_EXIF_IFD)
    if exif_ifd_offset_val is not None:
        exif_ifd_addr = tiff_start + exif_ifd_offset_val
        exif_tags, _ = _read_ifd(data, tiff_start, exif_ifd_addr, endian)
        if EXIF_DATETIME_ORIGINAL in exif_tags:
            date_str = exif_tags[EXIF_DATETIME_ORIGINAL]
        elif EXIF_DATETIME_DIGITIZED in exif_tags:
            date_str = exif_tags[EXIF_DATETIME_DIGITIZED] or date_str

    return date_str


def _read_ifd(data, tiff_start, ifd_addr, endian):
    """Read an IFD (Image File Directory) returning tag dict and next IFD offset."""
    if ifd_addr + 2 > len(data):
        return {}, 0

    num_entries = struct.unpack(endian + 'H', data[ifd_addr:ifd_addr + 2])[0]
    tags = {}
    entry_table_end = ifd_addr + 2 + num_entries * 12

    for i in range(num_entries):
        entry_start = ifd_addr + 2 + i * 12
        if entry_start + 12 > len(data):
            continue

        tag_id = struct.unpack(endian + 'H', data[entry_start:entry_start + 2])[0]
        tag_type = struct.unpack(endian + 'H', data[entry_start + 2:entry_start + 4])[0]
        tag_count = struct.unpack(endian + 'I', data[entry_start + 4:entry_start + 8])[0]

        # 4-byte value or offset field
        value_field = data[entry_start + 8:entry_start + 12]

        # Type 2 = ASCII string
        if tag_type == 2:
            if tag_count <= 4:
                raw = value_field[:tag_count - 1]
            else:
                val_off = struct.unpack(endian + 'I', value_field)[0]
                raw_start = tiff_start + val_off
                raw_end = min(raw_start + tag_count - 1, len(data))
                raw = data[raw_start:raw_end]
            tags[tag_id] = raw.decode('ascii', errors='replace')

        # Type 3 = unsigned short (2 bytes)
        elif tag_type == 3 and tag_count == 1:
            tags[tag_id] = struct.unpack(endian + 'H', value_field[:2])[0]

        # Type 4 = unsigned long (4 bytes)
        elif tag_type == 4 and tag_count == 1:
            tags[tag_id] = struct.unpack(endian + 'I', value_field)[0]

        # Type 7 = undefined (can contain sub-IFD offsets, skip)
        # Type 5 = rational (not needed for date extraction)

    next_ifd_offset = 0
    if entry_table_end + 4 <= len(data):
        next_ifd_offset = struct.unpack(endian + 'I', data[entry_table_end:entry_table_end + 4])[0]

    return tags, next_ifd_offset


# ═══════════════════════════════════════════════════════════════
# Video metadata via ffprobe
# ═══════════════════════════════════════════════════════════════

VIDEO_EXTENSIONS = {'.mp4', '.mov', '.m4v', '.avi', '.mkv', '.webm', '.ts', '.mts', '.m2ts', '.lrv', '.insv'}
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.heic', '.heif', '.webp', '.tiff', '.tif', '.bmp', '.gif'}


def _get_datetime_from_ffprobe(filepath):
    """Extract creation_time from video/image metadata using ffprobe."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", str(filepath)],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            return None

        data = json.loads(result.stdout)

        # Check format tags
        tags = data.get("format", {}).get("tags", {})
        date_str = _get_date_from_tags(tags)
        if date_str:
            return date_str

        # Check stream tags
        for stream in data.get("streams", []):
            stream_tags = stream.get("tags", {})
            date_str = _get_date_from_tags(stream_tags)
            if date_str:
                return date_str

    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        pass
    return None


def _get_date_from_tags(tags):
    """Try various tag names that might contain a date string."""
    for key in ("creation_time", "com.apple.quicktime.creationdate",
                "com.apple.quicktime.make", "date", "DateTimeOriginal"):
        val = tags.get(key)
        if val:
            cleaned = val.replace('\n', ' ').strip()
            if cleaned:
                return cleaned
    return None


# ═══════════════════════════════════════════════════════════════
# Filename-based date extraction (for known patterns)
# ═══════════════════════════════════════════════════════════════

FILENAME_DATE_PATTERNS = [
    # Insta360 / common camera pattern: VID_YYYYMMDD_HHMMSS_*
    re.compile(r'(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})'),
    # YYYY-MM-DD HH.MM.SS
    re.compile(r'(\d{4})-(\d{2})-(\d{2})[ _.-](\d{2})[.。-](\d{2})[.。-](\d{2})'),
    # YYYYMMDD_HHMMSS (simple)
    re.compile(r'(\d{4})(\d{2})(\d{2})[_-]?(\d{2})(\d{2})(\d{2})'),
    # YYYYMMDD (date only)
    re.compile(r'(\d{4})(\d{2})(\d{2})'),
]


def _parse_date_from_filename(stem):
    """Try to extract a datetime from the filename stem."""
    for pattern in FILENAME_DATE_PATTERNS:
        m = pattern.search(stem)
        if m:
            groups = m.groups()
            try:
                if len(groups) == 6:
                    return datetime(
                        int(groups[0]), int(groups[1]), int(groups[2]),
                        int(groups[3]), int(groups[4]), int(groups[5])
                    )
                elif len(groups) == 3:
                    return datetime(
                        int(groups[0]), int(groups[1]), int(groups[2]),
                        0, 0, 0
                    )
            except (ValueError, IndexError):
                continue
    return None


def _parse_datetime_string(date_str):
    """Try to parse various datetime string formats into a datetime object."""
    date_str = date_str.strip().strip('"').strip("'")

    # Common ISO formats
    for fmt in [
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y:%m:%d %H:%M:%S",
        "%Y-%m-%d",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d",
    ]:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue

    # Handle timezone-aware strings with Z
    if date_str.endswith('Z'):
        try:
            return datetime.strptime(date_str.rstrip('Z'), "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            pass
        try:
            return datetime.strptime(date_str.rstrip('Z'), "%Y-%m-%dT%H:%M:%S.%f")
        except ValueError:
            pass

    return None


# ═══════════════════════════════════════════════════════════════
# Main logic
# ═══════════════════════════════════════════════════════════════

def get_media_date(filepath):
    """
    Extract the best available date for a media file.

    Priority:
      1. EXIF DateTimeOriginal (JPEG images)
      2. ffprobe creation_time (videos)
      3. Filename-based date pattern
      4. File birth time (macOS st_birthtime)
      5. File modification time
    """
    ext = Path(filepath).suffix.lower()
    stem = Path(filepath).stem

    # 1. EXIF for JPEG images
    if ext in ('.jpg', '.jpeg'):
        exif_str = _read_exif_date_jpeg(filepath)
        if exif_str:
            dt = _parse_datetime_string(exif_str)
            if dt:
                return dt

    # 2. ffprobe for videos (and images as fallback)
    ff_date = _get_datetime_from_ffprobe(filepath)
    if ff_date:
        dt = _parse_datetime_string(ff_date)
        if dt:
            return dt

    # 3. Filename pattern
    dt = _parse_date_from_filename(stem)
    if dt:
        return dt

    # 4. File birth time / modification time
    try:
        st = os.stat(filepath)
        birth = getattr(st, 'st_birthtime', None)
        ts = birth if birth else st.st_mtime
        return datetime.fromtimestamp(ts)
    except OSError:
        pass

    return None


def format_date_suffix(dt):
    """Format a datetime into a string suitable for appending to filenames."""
    return dt.strftime("%Y%m%d_%H%M%S")


def has_date_in_filename(stem):
    """Check if the filename already contains a date suffix we added."""
    return bool(re.search(r'_\d{8}_\d{6}$', stem))


def process_file(filepath, dry_run=False, force=False):
    """Process a single file: extract date, append to filename."""
    filepath = Path(filepath)

    if not filepath.is_file():
        print(f"SKIP: not a file: {filepath}")
        return

    ext = filepath.suffix.lower()
    if ext not in VIDEO_EXTENSIONS and ext not in IMAGE_EXTENSIONS:
        print(f"SKIP: unsupported format: {filepath} ({ext})")
        return

    stem = filepath.stem

    # Skip if already has our date suffix
    if has_date_in_filename(stem) and not force:
        print(f"SKIP: already has date suffix: {filepath.name}")
        return

    dt = get_media_date(filepath)
    if dt is None:
        print(f"FAIL: could not extract date: {filepath.name}")
        return

    suffix = format_date_suffix(dt)
    new_name = f"{stem}_{suffix}{filepath.suffix}"
    new_path = filepath.with_name(new_name)

    if new_path.exists():
        print(f"SKIP: target exists: {new_name}")
        return

    if dry_run:
        print(f"[DRY RUN] {filepath.name}  ->  {new_name}  ({dt.strftime('%Y-%m-%d %H:%M:%S')})")
    else:
        filepath.rename(new_path)
        print(f"RENAMED: {filepath.name}  ->  {new_name}  ({dt.strftime('%Y-%m-%d %H:%M:%S')})")


def main():
    parser = argparse.ArgumentParser(
        description="Extract date from media files and append to filename"
    )
    parser.add_argument(
        "paths", nargs="+",
        help="File(s) or director(y/ies) to process"
    )
    parser.add_argument(
        "--dry-run", "-n", action="store_true",
        help="Show what would be renamed without doing it"
    )
    parser.add_argument(
        "--recursive", "-r", action="store_true",
        help="Process directories recursively"
    )
    parser.add_argument(
        "--force", "-f", action="store_true",
        help="Process even if filename already has a date suffix"
    )
    args = parser.parse_args()

    files_to_process = []
    for p in args.paths:
        path = Path(p)
        if path.is_file():
            files_to_process.append(path)
        elif path.is_dir():
            if args.recursive:
                for f in path.rglob("*"):
                    if f.is_file():
                        files_to_process.append(f)
            else:
                for f in path.glob("*"):
                    if f.is_file():
                        files_to_process.append(f)
        else:
            print(f"SKIP: not found: {path}")

    # Sort for consistent order
    files_to_process.sort()

    if not files_to_process:
        print("No files to process.")
        return

    for f in files_to_process:
        process_file(f, dry_run=args.dry_run, force=args.force)

    if args.dry_run:
        print(f"\nDry run complete. {len(files_to_process)} file(s) checked.")


if __name__ == "__main__":
    main()
