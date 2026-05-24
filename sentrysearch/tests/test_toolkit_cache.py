"""Tests for sentrysearch._toolkit_cache."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from sentrysearch import _toolkit_cache
from sentrysearch._toolkit_cache import (
    LastClip,
    LastSearch,
    read_last_clip,
    read_last_search,
    write_last_clip,
    write_last_search,
)


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    """Redirect the cache files into tmp_path so tests never touch ~/.cache."""
    cache_dir = tmp_path / "sentry-toolkit"
    cache_file = cache_dir / "last_clip.json"
    search_file = cache_dir / "last_search.json"
    monkeypatch.setattr(_toolkit_cache, "_cache_path", lambda: cache_file)
    monkeypatch.setattr(_toolkit_cache, "_last_search_path", lambda: search_file)
    return cache_file


@pytest.fixture
def _isolated_search_cache(tmp_path, monkeypatch):
    """Direct accessor to the redirected search-receipt path for assertions."""
    return tmp_path / "sentry-toolkit" / "last_search.json"


def _result(source: str, start: float = 0.0, end: float = 30.0,
            score: float = 0.5) -> dict:
    return {
        "source_file": source,
        "start_time": start,
        "end_time": end,
        "similarity_score": score,
    }


def test_round_trip(tmp_path):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x")
    write_last_clip(clip)

    got = read_last_clip()
    assert got is not None
    assert got.path == clip
    assert got.saved_by == "sentrysearch"
    assert got.saved_at.tzinfo is not None
    assert abs(got.age_seconds) < 5


def test_custom_saved_by(tmp_path):
    clip = tmp_path / "clip.mp4"
    write_last_clip(clip, saved_by="sentryblur")
    got = read_last_clip()
    assert got is not None
    assert got.saved_by == "sentryblur"


def test_read_missing_returns_none():
    assert read_last_clip() is None


def test_read_corrupt_json_returns_none(_isolated_cache):
    _isolated_cache.parent.mkdir(parents=True, exist_ok=True)
    _isolated_cache.write_text("{not valid json")
    assert read_last_clip() is None


def test_read_wrong_version_returns_none(_isolated_cache):
    _isolated_cache.parent.mkdir(parents=True, exist_ok=True)
    _isolated_cache.write_text(json.dumps({
        "version": 999,
        "path": "/tmp/x.mp4",
        "saved_at": "2026-04-28T15:30:00Z",
        "saved_by": "sentrysearch",
    }))
    assert read_last_clip() is None


def test_read_missing_field_returns_none(_isolated_cache):
    _isolated_cache.parent.mkdir(parents=True, exist_ok=True)
    _isolated_cache.write_text(json.dumps({"version": 1, "path": "/tmp/x.mp4"}))
    assert read_last_clip() is None


def test_relative_path_rejected():
    with pytest.raises(ValueError):
        write_last_clip(Path("relative/clip.mp4"))


def test_atomic_write_preserves_previous_on_crash(tmp_path, monkeypatch, _isolated_cache):
    # First, write a valid cache.
    clip1 = tmp_path / "first.mp4"
    write_last_clip(clip1)
    assert read_last_clip().path == clip1

    # Simulate a crash mid-write: tempfile gets created, rename fails.
    def boom(src, dst):
        raise OSError("simulated crash before rename")

    monkeypatch.setattr(_toolkit_cache.os, "replace", boom)

    clip2 = tmp_path / "second.mp4"
    with pytest.raises(OSError):
        write_last_clip(clip2)

    # Previous cache must still be intact and readable.
    got = read_last_clip()
    assert got is not None
    assert got.path == clip1

    # No leftover .tmp files in the cache dir.
    leftovers = [p for p in _isolated_cache.parent.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []


def test_atomic_write_no_prior_cache_returns_none_on_crash(tmp_path, monkeypatch, _isolated_cache):
    def boom(src, dst):
        raise OSError("simulated crash")

    monkeypatch.setattr(_toolkit_cache.os, "replace", boom)

    clip = tmp_path / "clip.mp4"
    with pytest.raises(OSError):
        write_last_clip(clip)

    assert read_last_clip() is None


def test_age_seconds(tmp_path):
    clip = tmp_path / "clip.mp4"
    saved_at = datetime.now(timezone.utc) - timedelta(seconds=42)
    lc = LastClip(path=clip, saved_at=saved_at, saved_by="sentrysearch")
    assert 41 <= lc.age_seconds <= 43


def test_file_exists(tmp_path):
    real = tmp_path / "real.mp4"
    real.write_bytes(b"x")
    missing = tmp_path / "missing.mp4"

    now = datetime.now(timezone.utc)
    assert LastClip(path=real, saved_at=now, saved_by="x").file_exists is True
    assert LastClip(path=missing, saved_at=now, saved_by="x").file_exists is False


def test_write_creates_parent_dir(tmp_path, _isolated_cache):
    assert not _isolated_cache.parent.exists()
    clip = tmp_path / "clip.mp4"
    write_last_clip(clip)
    assert _isolated_cache.is_file()


def test_payload_format_on_disk(tmp_path, _isolated_cache):
    clip = tmp_path / "clip.mp4"
    write_last_clip(clip)
    data = json.loads(_isolated_cache.read_text())
    assert data["version"] == 1
    assert data["path"] == str(clip)
    assert data["saved_by"] == "sentrysearch"
    assert data["saved_at"].endswith("Z")


# ----------------------------------------------------------------------------
# LastSearch (search receipt)
# ----------------------------------------------------------------------------


def test_search_round_trip_text_query():
    results = [
        _result("/v/a-front.mp4", 0.0, 30.0, 0.41),
        _result("/v/a-back.mp4", 0.0, 30.0, 0.36),
    ]
    write_last_search(query="honda fit", results=results)

    got = read_last_search()
    assert got is not None
    assert got.query == "honda fit"
    assert got.image_path is None
    assert got.is_image_query is False
    assert got.results == results
    assert got.saved_by == "sentrysearch"
    assert abs(got.age_seconds) < 5


def test_search_round_trip_image_query(tmp_path):
    img = tmp_path / "query.jpg"
    img.write_bytes(b"x")
    write_last_search(query=None, image_path=img, results=[_result("/v/x.mp4")])

    got = read_last_search()
    assert got is not None
    assert got.query is None
    assert got.image_path == img
    assert got.is_image_query is True


def test_search_requires_exactly_one_query_form():
    with pytest.raises(ValueError):
        write_last_search(query=None, image_path=None, results=[])
    with pytest.raises(ValueError):
        write_last_search(
            query="x", image_path=Path("/abs/img.jpg"), results=[],
        )


def test_search_relative_image_path_rejected():
    with pytest.raises(ValueError):
        write_last_search(
            query=None, image_path=Path("relative.jpg"), results=[],
        )


def test_search_result_missing_key_rejected():
    bad = [{"source_file": "/v/x.mp4", "start_time": 0.0}]  # missing keys
    with pytest.raises(ValueError):
        write_last_search(query="q", results=bad)


def test_search_read_missing_returns_none():
    assert read_last_search() is None


def test_search_read_corrupt_returns_none(_isolated_search_cache):
    _isolated_search_cache.parent.mkdir(parents=True, exist_ok=True)
    _isolated_search_cache.write_text("{nope")
    assert read_last_search() is None


def test_search_read_wrong_version_returns_none(_isolated_search_cache):
    _isolated_search_cache.parent.mkdir(parents=True, exist_ok=True)
    _isolated_search_cache.write_text(json.dumps({
        "version": 999, "saved_at": "2026-04-28T15:30:00Z",
        "saved_by": "sentrysearch", "query": "q", "image_path": None,
        "results": [],
    }))
    assert read_last_search() is None


def test_search_read_both_query_forms_returns_none(_isolated_search_cache):
    _isolated_search_cache.parent.mkdir(parents=True, exist_ok=True)
    _isolated_search_cache.write_text(json.dumps({
        "version": 1, "saved_at": "2026-04-28T15:30:00Z",
        "saved_by": "sentrysearch",
        "query": "q", "image_path": "/abs/i.jpg",
        "results": [],
    }))
    assert read_last_search() is None


def test_search_read_neither_query_form_returns_none(_isolated_search_cache):
    _isolated_search_cache.parent.mkdir(parents=True, exist_ok=True)
    _isolated_search_cache.write_text(json.dumps({
        "version": 1, "saved_at": "2026-04-28T15:30:00Z",
        "saved_by": "sentrysearch",
        "query": None, "image_path": None,
        "results": [],
    }))
    assert read_last_search() is None


def test_search_read_malformed_result_returns_none(_isolated_search_cache):
    _isolated_search_cache.parent.mkdir(parents=True, exist_ok=True)
    _isolated_search_cache.write_text(json.dumps({
        "version": 1, "saved_at": "2026-04-28T15:30:00Z",
        "saved_by": "sentrysearch",
        "query": "q", "image_path": None,
        "results": [{"source_file": "/v/x.mp4"}],  # missing keys
    }))
    assert read_last_search() is None


def test_search_payload_format_on_disk(_isolated_search_cache):
    write_last_search(query="lexus suv", results=[_result("/v/x-back.mp4")])
    data = json.loads(_isolated_search_cache.read_text())
    assert data["version"] == 1
    assert data["query"] == "lexus suv"
    assert data["image_path"] is None
    assert data["saved_by"] == "sentrysearch"
    assert data["saved_at"].endswith("Z")
    assert data["results"][0]["source_file"] == "/v/x-back.mp4"


def test_search_atomic_write_preserves_previous_on_crash(monkeypatch):
    write_last_search(query="first", results=[_result("/v/a.mp4")])
    assert read_last_search().query == "first"

    def boom(src, dst):
        raise OSError("simulated crash")

    monkeypatch.setattr(_toolkit_cache.os, "replace", boom)

    with pytest.raises(OSError):
        write_last_search(query="second", results=[_result("/v/b.mp4")])

    got = read_last_search()
    assert got is not None
    assert got.query == "first"
