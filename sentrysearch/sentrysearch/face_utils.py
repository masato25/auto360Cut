import os
import subprocess
import sys
import tempfile
import types

import numpy as np

from sentrysearch.chunker import _get_ffmpeg_executable


# pkg_resources shim for face_recognition_models on Python >=3.14
if "pkg_resources" not in sys.modules:
    _pr = types.ModuleType("pkg_resources")
    def _resource_filename(package, resource_name):
        import importlib.resources as rsrc
        from contextlib import ExitStack
        _st = ExitStack()
        ref = rsrc.files(package).joinpath(resource_name)
        return str(_st.enter_context(rsrc.as_file(ref)))
    _pr.resource_filename = _resource_filename
    sys.modules["pkg_resources"] = _pr


def _get_ffmpeg() -> str:
    ffmpeg = _get_ffmpeg_executable()
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found")
    return ffmpeg


def extract_frame(video_path: str, time_sec: float = 0.0) -> np.ndarray | None:
    ffmpeg = _get_ffmpeg()
    cmd = [
        ffmpeg, "-ss", str(time_sec), "-i", video_path,
        "-vframes", "1", "-f", "image2pipe", "-pix_fmt", "rgb24",
        "-vcodec", "rawvideo", "-",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=30)
    except subprocess.TimeoutExpired:
        return None
    if result.returncode != 0:
        return None

    import struct
    import subprocess as sp

    probe_cmd = [
        ffmpeg, "-i", video_path,
        "-vframes", "1", "-f", "null", "-",
    ]
    try:
        width, height = _probe_resolution(video_path)
    except Exception:
        width, height = 640, 480

    raw = result.stdout
    expected = width * height * 3
    if len(raw) < expected:
        return None
    arr = np.frombuffer(raw[:expected], dtype=np.uint8).reshape((height, width, 3))
    return arr


def _probe_resolution(video_path: str) -> tuple[int, int]:
    ffmpeg = _get_ffmpeg()
    cmd = [
        ffmpeg, "-i", video_path,
        "-vframes", "1", "-f", "null", "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    import re
    match = re.search(r"Stream.*Video.* (\d+)x(\d+)", result.stderr)
    if match:
        return int(match.group(1)), int(match.group(2))
    return 640, 480


def detect_face_encodings(frame: np.ndarray) -> list[tuple[np.ndarray, tuple]]:
    try:
        import face_recognition
    except ImportError:
        raise RuntimeError(
            "face_recognition not installed.\n"
            "  pip install face_recognition"
        )
    locations = face_recognition.face_locations(frame)
    if not locations:
        return []
    encodings = face_recognition.face_encodings(frame, locations)
    return list(zip(encodings, locations))


def encode_reference_face(image_path: str) -> np.ndarray | None:
    try:
        import face_recognition
    except ImportError:
        raise RuntimeError(
            "face_recognition not installed.\n"
            "  pip install face_recognition"
        )
    img = face_recognition.load_image_file(image_path)
    locations = face_recognition.face_locations(img)
    if not locations:
        return None
    encodings = face_recognition.face_encodings(img, locations)
    if not encodings:
        return None
    return encodings[0]


def encode_face_array(frame: np.ndarray) -> list[np.ndarray]:
    try:
        import face_recognition
    except ImportError:
        raise RuntimeError(
            "face_recognition not installed.\n"
            "  pip install face_recognition"
        )
    locations = face_recognition.face_locations(frame)
    if not locations:
        return []
    return face_recognition.face_encodings(frame, locations)


def face_similarity(ref_encoding: np.ndarray, target_encoding: np.ndarray) -> float:
    dot = np.dot(ref_encoding, target_encoding)
    norm = np.linalg.norm(ref_encoding) * np.linalg.norm(target_encoding)
    if norm == 0:
        return 0.0
    return float(dot / norm)


def serialize_encodings(encodings: list[np.ndarray]) -> list[list[float]]:
    return [e.tolist() for e in encodings]


def deserialize_encodings(data: list[list[float]]) -> list[np.ndarray]:
    return [np.array(e, dtype=np.float64) for e in data]
