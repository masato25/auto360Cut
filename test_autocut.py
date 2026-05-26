from autocut import (
    VIEWPORT_INDEX_VERSION,
    _cosine_similarity,
    _is_360_cache_current,
    _normalize_v360_yaw,
)


# ── _normalize_v360_yaw ───────────────────────────────────────────────────────

def test_yaw_zero_stays_zero() -> None:
    assert _normalize_v360_yaw(0) == 0.0


def test_yaw_90_stays_90() -> None:
    assert _normalize_v360_yaw(90) == 90.0


def test_yaw_180_becomes_negative_180() -> None:
    # 180 user-facing → ffmpeg -180 (same direction, canonical form)
    assert _normalize_v360_yaw(180) == -180.0


def test_yaw_270_becomes_neg90() -> None:
    assert _normalize_v360_yaw(270) == -90.0


def test_yaw_360_wraps_to_0() -> None:
    assert _normalize_v360_yaw(360) == 0.0


# ── _cosine_similarity ────────────────────────────────────────────────────────

def test_cosine_identical_vectors() -> None:
    v = [1.0, 0.0, 0.0]
    assert abs(_cosine_similarity(v, v) - 1.0) < 1e-9


def test_cosine_orthogonal_vectors() -> None:
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert abs(_cosine_similarity(a, b)) < 1e-9


def test_cosine_opposite_vectors() -> None:
    a = [1.0, 0.0]
    b = [-1.0, 0.0]
    assert abs(_cosine_similarity(a, b) + 1.0) < 1e-9


def test_cosine_zero_vector_returns_zero() -> None:
    assert _cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


# ── _is_360_cache_current ─────────────────────────────────────────────────────

def _valid_meta() -> dict:
    return {
        "viewport_index_version": VIEWPORT_INDEX_VERSION,
        "viewport_prompt": "default prompt",
        "best_direction": "front",
        "projection": "equirect",
        "viewport_captions": "some captions",
    }


def test_360_cache_current_with_valid_meta() -> None:
    assert _is_360_cache_current(_valid_meta(), "default prompt", None) is True


def test_360_cache_stale_on_wrong_version() -> None:
    meta = _valid_meta()
    meta["viewport_index_version"] = VIEWPORT_INDEX_VERSION - 1
    assert _is_360_cache_current(meta, "default prompt", None) is False


def test_360_cache_stale_on_prompt_mismatch() -> None:
    assert _is_360_cache_current(_valid_meta(), "different prompt", None) is False


def test_360_cache_stale_on_missing_best_direction() -> None:
    meta = _valid_meta()
    meta["best_direction"] = ""
    assert _is_360_cache_current(meta, "default prompt", None) is False


def test_360_cache_stale_on_empty_captions() -> None:
    meta = _valid_meta()
    meta["viewport_captions"] = ""
    assert _is_360_cache_current(meta, "default prompt", None) is False


def test_360_cache_stale_on_projection_mismatch() -> None:
    meta = _valid_meta()
    meta["projection"] = "fisheye"
    assert _is_360_cache_current(meta, "default prompt", "equirect") is False


def test_360_cache_current_explicit_equirect_projection() -> None:
    assert _is_360_cache_current(_valid_meta(), "default prompt", "equirect") is True


if __name__ == "__main__":
    import sys
    failures = 0
    for name, fn in list(globals().items()):
        if not name.startswith("test_"):
            continue
        try:
            fn()
            print(f"  ok  {name}")
        except Exception as exc:
            print(f"FAIL  {name}: {exc}")
            failures += 1
    print(f"\n{'All tests passed.' if not failures else f'{failures} test(s) failed.'}")
    sys.exit(failures)
