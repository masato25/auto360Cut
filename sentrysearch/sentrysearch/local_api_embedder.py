"""OpenAI-compatible API backend for self-hosted LLM servers.

Connects to any OpenAI-compatible API (llama.cpp, vLLM, TGI, etc.)
via the ``openai`` Python package.

Environment variables
--------------------
LOCAL_API_BASE
    Base URL of the OpenAI-compatible API (e.g. http://192.168.0.207:8080).
LOCAL_API_MODEL
    Model name/ID (e.g. the GGUF filename or model path).
LOCAL_API_KEY
    Optional API key (default "not-needed" for most local servers).
EMBED_DIMENSIONS
    Embedding dimension (default 768).
"""

from __future__ import annotations

import base64
import os
import subprocess
import sys
import tempfile
import time

from dotenv import load_dotenv

from .base_embedder import BaseEmbedder

load_dotenv()

DEFAULT_API_BASE = "http://localhost:8080"
DEFAULT_MODEL = "default"
DEFAULT_DIMENSIONS = 768
VALID_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


class LocalApiError(RuntimeError):
    """Raised when the local API call fails."""


def _get_settings() -> tuple[str, str, str | None]:
    base = os.environ.get("LOCAL_API_BASE", "").strip() or DEFAULT_API_BASE
    model = os.environ.get("LOCAL_API_MODEL", "").strip() or DEFAULT_MODEL
    key = os.environ.get("LOCAL_API_KEY") or "not-needed"
    return base, model, key


def _read_image_b64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _extract_frame(video_path: str, seek_sec: float = 0.0) -> str | None:
    """Extract a single JPEG frame from *video_path* at *seek_sec*."""
    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    tmp.close()
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y", "-ss", str(seek_sec),
                "-i", video_path,
                "-vframes", "1",
                "-q:v", "2",
                tmp.name,
            ],
            capture_output=True, text=True,
        )
        if result.returncode != 0 or not os.path.isfile(tmp.name) or os.path.getsize(tmp.name) == 0:
            return None
        return tmp.name
    except Exception:
        if os.path.isfile(tmp.name):
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
        return None


def _extract_frame_middle(video_path: str) -> str | None:
    """Try to extract a frame from the middle of the video."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", video_path],
            capture_output=True, text=True, timeout=30,
        )
        duration = float(result.stdout.strip())
        return _extract_frame(video_path, duration / 2)
    except Exception:
        return _extract_frame(video_path, 0.0)


class LocalApiEmbedder(BaseEmbedder):
    """OpenAI-compatible API backend."""

    def __init__(
        self,
        model: str | None = None,
        dimensions: int | None = None,
    ):
        from openai import OpenAI

        base, env_model, key = _get_settings()
        self._api_base = base.rstrip("/")
        self._model = model or env_model
        self._dimensions = dimensions or int(
            os.environ.get("EMBED_DIMENSIONS", str(DEFAULT_DIMENSIONS))
        )

        self._client = OpenAI(base_url=f"{self._api_base}/v1", api_key=key)
        self._embeddings_model = os.environ.get(
            "LOCAL_API_EMBEDDINGS_MODEL",
            self._model,
        )
        self._caption_system_prompt = (
            "You are a scene description assistant. Describe what is happening "
            "in this video frame in one short sentence (max 30 words). "
            "Focus on actions, objects, and the user's perspective."
        )

    def _embed_text(self, text: str) -> list[float]:
        try:
            resp = self._client.embeddings.create(
                model=self._embeddings_model,
                input=text,
            )
            return resp.data[0].embedding
        except Exception as exc:
            raise LocalApiError(
                f"Text embedding failed (model={self._embeddings_model}): {exc}"
            ) from exc

    def _caption_via_vision(self, image_b64: str, verbose: bool = False) -> str:
        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {
                        "role": "system",
                        "content": self._caption_system_prompt,
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_b64}",
                                },
                            },
                        ],
                    },
                ],
                max_tokens=64,
                temperature=0.1,
            )
            return resp.choices[0].message.content.strip() or ""
        except Exception as exc:
            if verbose:
                print(
                    f"    [verbose] vision caption failed: {exc}",
                    file=sys.stderr,
                )
            return ""

    def embed_video_chunk(
        self,
        chunk_path: str,
        metadata: dict | None = None,
        verbose: bool = False,
    ) -> list[float]:
        frame_path = _extract_frame_middle(chunk_path)
        if frame_path is None:
            if verbose:
                print(
                    "    [verbose] frame extraction failed, using empty caption",
                    file=sys.stderr,
                )
            caption = ""
        else:
            try:
                image_b64 = _read_image_b64(frame_path)
                caption = self._caption_via_vision(image_b64, verbose=verbose)
            finally:
                try:
                    os.unlink(frame_path)
                except OSError:
                    pass

        if metadata is not None:
            metadata["caption"] = caption

        if verbose:
            size_kb = os.path.getsize(chunk_path) / 1024
            print(
                f"    [verbose] chunk={size_kb:.0f}KB, caption={caption[:60]!r}",
                file=sys.stderr,
            )

        t0 = time.monotonic()
        if caption:
            vec = self._embed_text(caption)
        else:
            vec = [0.0] * self._dimensions
        elapsed = time.monotonic() - t0

        if verbose:
            print(
                f"    [verbose] dims={len(vec)}, embedding_time={elapsed:.2f}s",
                file=sys.stderr,
            )

        return vec[: self._dimensions]

    def embed_query(self, query_text: str, verbose: bool = False) -> list[float]:
        if verbose:
            t0 = time.monotonic()

        vec = self._embed_text(query_text)

        if verbose:
            elapsed = time.monotonic() - t0
            print(
                f"  [verbose] query embedding: dims={len(vec)}, "
                f"api_time={elapsed:.2f}s",
                file=sys.stderr,
            )

        return vec[: self._dimensions]

    def embed_image(
        self,
        image_path: str,
        metadata: dict | None = None,
        verbose: bool = False,
    ) -> list[float]:
        ext = os.path.splitext(image_path)[1].lower()
        if ext not in VALID_IMAGE_EXTS:
            raise ValueError(
                f"Unsupported image type {ext!r}. "
                f"local-api accepts: {', '.join(sorted(VALID_IMAGE_EXTS))}."
            )

        image_b64 = _read_image_b64(image_path)
        caption = self._caption_via_vision(image_b64, verbose=verbose)

        if metadata is not None:
            metadata["caption"] = caption

        if verbose:
            size_kb = os.path.getsize(image_path) / 1024
            print(
                f"    [verbose] image={size_kb:.0f}KB, caption={caption[:60]!r}",
                file=sys.stderr,
            )

        t0 = time.monotonic()
        if caption:
            vec = self._embed_text(caption)
        else:
            vec = [0.0] * self._dimensions
        elapsed = time.monotonic() - t0

        if verbose:
            print(
                f"  [verbose] image embedding: dims={len(vec)}, "
                f"inference_time={elapsed:.2f}s",
                file=sys.stderr,
            )

        return vec[: self._dimensions]

    def dimensions(self) -> int:
        return self._dimensions
