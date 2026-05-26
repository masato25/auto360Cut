import os
import tempfile

from utils import fmt_time, resolve_hq_source


# ── fmt_time ─────────────────────────────────────────────────────────────────

def test_fmt_time_zero() -> None:
    assert fmt_time(0) == "00:00"


def test_fmt_time_under_a_minute() -> None:
    assert fmt_time(45) == "00:45"


def test_fmt_time_exactly_one_minute() -> None:
    assert fmt_time(60) == "01:00"


def test_fmt_time_ninety_seconds() -> None:
    assert fmt_time(90) == "01:30"


def test_fmt_time_truncates_sub_second() -> None:
    assert fmt_time(90.9) == "01:30"


def test_fmt_time_large_value() -> None:
    assert fmt_time(3661) == "61:01"


# ── resolve_hq_source ────────────────────────────────────────────────────────

def test_resolve_hq_source_explicit_path(tmp_path) -> None:
    f = tmp_path / "explicit.mp4"
    f.write_bytes(b"")
    result = resolve_hq_source("any.lrv", hq_source=str(f))
    assert result == str(f)


def test_resolve_hq_source_hq_dir_exact_match(tmp_path) -> None:
    hq = tmp_path / "VID_20240101_120000_00_001.mp4"
    hq.write_bytes(b"")
    result = resolve_hq_source(
        f"LRV_20240101_120000_001.lrv",
        hq_dir=str(tmp_path),
    )
    assert result == str(hq)


def test_resolve_hq_source_hq_dir_no_match_returns_none(tmp_path) -> None:
    result = resolve_hq_source("LRV_20240101_120000_001.lrv", hq_dir=str(tmp_path))
    assert result is None


def test_resolve_hq_source_lrv_sibling_lookup(tmp_path) -> None:
    lrv = tmp_path / "LRV_20240101_120000_001.lrv"
    vid = tmp_path / "VID_20240101_120000_001.mp4"
    lrv.write_bytes(b"")
    vid.write_bytes(b"")
    result = resolve_hq_source(str(lrv))
    assert result == str(vid)


def test_resolve_hq_source_no_match_returns_none(tmp_path) -> None:
    result = resolve_hq_source(str(tmp_path / "VID_20240101_120000.mp4"))
    assert result is None


# ── tmp_path shim (no pytest) ─────────────────────────────────────────────────

class _TmpPath:
    def __init__(self, path: str):
        self._path = path

    def __truediv__(self, name: str) -> "_TmpPath":
        return _TmpPath(os.path.join(self._path, name))

    def write_bytes(self, data: bytes) -> None:
        with open(self._path, "wb") as f:
            f.write(data)

    def __str__(self) -> str:
        return self._path


def _run_with_tmp(fn) -> None:
    with tempfile.TemporaryDirectory() as d:
        fn(_TmpPath(d))


if __name__ == "__main__":
    import inspect, sys

    failures = 0
    for name, fn in list(globals().items()):
        if not name.startswith("test_"):
            continue
        sig = inspect.signature(fn)
        try:
            if sig.parameters:
                _run_with_tmp(fn)
            else:
                fn()
            print(f"  ok  {name}")
        except Exception as exc:
            print(f"FAIL  {name}: {exc}")
            failures += 1

    print(f"\n{'All tests passed.' if not failures else f'{failures} test(s) failed.'}")
    sys.exit(failures)
