import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("autocut_module", ROOT / "autocut.py")
autocut = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(autocut)


def _row(start, caption, direction="front"):
    return {
        "idx": int(start),
        "source_file": "video.mp4",
        "start_time": float(start),
        "end_time": float(start + 30),
        "caption": caption,
        "is_360": True,
        "best_yaw": 0,
        "best_direction": direction,
        "projection": "equirect",
        "face_encodings": "",
    }


def test_select_clips_skips_nearby_duplicate_speech_with_different_view_or_start():
    duplicate_a = _row(0, "front: Alice says hello and asks where are we going", "front")
    duplicate_b = _row(5, "right: Alice says hello and asks where are we going", "right")
    distinct = _row(55, "Bob opens the door and talks about lunch", "back")
    rows = [duplicate_a, duplicate_b, distinct]

    mock_store = MagicMock()
    with patch.object(autocut, "get_embedder"), \
         patch.object(autocut, "SentryStore", return_value=mock_store), \
         patch.object(autocut, "search_footage", return_value=[duplicate_a, duplicate_b, distinct]):
        selected = autocut._select_clips(
            rows,
            prompt="people talking",
            count=2,
            backend="local-api",
            model=None,
            quantize=None,
            verbose=False,
        )

    assert selected == [duplicate_a, distinct]


def test_select_clips_returns_matches_in_timeline_order_not_search_rank_order():
    downstairs = _row(0, "I am still downstairs near the stairs", "front")
    upstairs = _row(60, "I have already walked upstairs", "front")
    rows = [downstairs, upstairs]

    mock_store = MagicMock()
    with patch.object(autocut, "get_embedder"), \
         patch.object(autocut, "SentryStore", return_value=mock_store), \
         patch.object(autocut, "search_footage", return_value=[upstairs, downstairs]):
        selected = autocut._select_clips(
            rows,
            prompt="walking upstairs",
            count=2,
            backend="local-api",
            model=None,
            quantize=None,
            verbose=False,
        )

    assert selected == [downstairs, upstairs]


def test_dedupe_render_ranges_removes_adjacent_padded_overlap():
    first = _row(0, "front: first moment", "front")
    second = _row(25, "right: next moment", "right")

    adjusted = autocut._dedupe_render_ranges([first, second], padding=1.0)

    assert adjusted[0]["start_time"] == 0
    assert adjusted[0]["end_time"] == 26.5
    assert adjusted[1]["start_time"] == 28.5
    assert adjusted[1]["end_time"] == 55
    # Including trim_clip padding, the rendered boundary is exactly non-overlapping.
    assert adjusted[0]["end_time"] + 1.0 == adjusted[1]["start_time"] - 1.0
    assert first["end_time"] == 30
    assert second["start_time"] == 25


def test_dedupe_render_ranges_opens_back_to_back_boundary_for_padding():
    first = _row(0, "front: first moment", "front")
    second = _row(30, "right: next moment", "right")

    adjusted = autocut._dedupe_render_ranges([first, second], padding=1.0)

    assert adjusted[0]["end_time"] == 29.0
    assert adjusted[1]["start_time"] == 31.0
    assert adjusted[0]["end_time"] + 1.0 == adjusted[1]["start_time"] - 1.0
