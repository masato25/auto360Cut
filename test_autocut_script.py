
from autocut_script import (
    OUTPUT_LAYOUT_CHOICES,
    DEFAULT_OPENING_CAPTION_DURATION,
    _build_script_system_prompt,
    _choose_output_layout,
    _coerce_script_response,
    _escape_drawtext_text,
    _opening_caption_drawtext_filter,
    _opening_caption_fontfile,
    _normalize_opening_caption_duration,
    _opening_caption_dimensions,
    _normalize_openai_base_url,
    _parse_json_or_recover_clips,
    _parse_time,
    _render_layout_filter,
    _repair_json,
    _source_key,
    format_catalog,
    validate_script,
)


def test_render_layout_filter_portrait_uses_vertical_canvas() -> None:
    vf, width, height = _render_layout_filter("portrait")

    assert width == 1080
    assert height == 1920
    assert "pad=1080:1920" in vf


def test_output_layout_choices_are_manual_only() -> None:
    assert OUTPUT_LAYOUT_CHOICES == ("landscape", "portrait")
    assert _choose_output_layout("landscape") == "landscape"
    assert _choose_output_layout("portrait") == "portrait"


def test_choose_output_layout_rejects_auto() -> None:
    try:
        _choose_output_layout("auto")
    except ValueError as exc:
        assert "landscape" in str(exc)
        assert "portrait" in str(exc)
    else:
        raise AssertionError("auto layout should not be accepted")


def test_opening_caption_dimensions_follow_layout() -> None:
    assert _opening_caption_dimensions("landscape") == (1280, 720)
    assert _opening_caption_dimensions("portrait") == (1080, 1920)


def test_opening_caption_duration_default_and_positive() -> None:
    assert _normalize_opening_caption_duration(None) == DEFAULT_OPENING_CAPTION_DURATION
    assert _normalize_opening_caption_duration(2.5) == 2.5


def test_opening_caption_duration_rejects_non_positive() -> None:
    try:
        _normalize_opening_caption_duration(0)
    except ValueError as exc:
        assert "positive" in str(exc)
    else:
        raise AssertionError("zero duration should be rejected")


def test_escape_drawtext_text_escapes_special_chars() -> None:
    escaped = _escape_drawtext_text("A:B's 100%\\nok")
    assert r"A\:B\'s 100\%" in escaped
    assert r"\n" in escaped


def test_opening_caption_drawtext_filter_uses_boxed_white_text(monkeypatch) -> None:
    monkeypatch.setenv("AUTOCUT_OPENING_CAPTION_FONT", "/tmp/Noto Sans CJK.ttc")

    vf = _opening_caption_drawtext_filter("旅程開始", layout="landscape")

    assert "fontfile='/tmp/Noto Sans CJK.ttc'" in vf
    assert "text='旅程開始'" in vf
    assert "fontcolor=white" in vf
    assert "box=1" in vf
    assert "boxcolor=black@1.0" in vf


def test_opening_caption_fontfile_honors_env(monkeypatch) -> None:
    monkeypatch.setenv("AUTOCUT_OPENING_CAPTION_FONT", "/custom/cjk-font.ttc")

    assert _opening_caption_fontfile() == "/custom/cjk-font.ttc"


# ── _build_script_system_prompt ──────────────────────────────────────────────

def test_system_prompt_auto_mode_contains_key_phrases() -> None:
    prompt = _build_script_system_prompt(auto_prompt=True, prompt="", target_duration_minutes=None)
    assert "infer the best theme" in prompt
    assert "JSON array" in prompt
    assert "source_file" in prompt


def test_system_prompt_manual_mode_includes_user_request() -> None:
    prompt = _build_script_system_prompt(auto_prompt=False, prompt="surfing clips only", target_duration_minutes=None)
    assert "surfing clips only" in prompt
    assert "JSON array" in prompt


def test_system_prompt_manual_mode_no_request_has_no_extra_label() -> None:
    prompt = _build_script_system_prompt(auto_prompt=False, prompt="", target_duration_minutes=None)
    assert "Additional user request" not in prompt


def test_system_prompt_duration_instruction_included() -> None:
    prompt = _build_script_system_prompt(auto_prompt=True, prompt="", target_duration_minutes=3.0)
    assert "3 minutes" in prompt


def test_system_prompt_zero_duration_omits_instruction() -> None:
    prompt = _build_script_system_prompt(auto_prompt=True, prompt="", target_duration_minutes=0)
    assert "Target final duration" not in prompt


def test_system_prompt_none_duration_omits_instruction() -> None:
    prompt = _build_script_system_prompt(auto_prompt=False, prompt="", target_duration_minutes=None)
    assert "Target final duration" not in prompt


# ── _parse_time ──────────────────────────────────────────────────────────────

def test_parse_time_integer() -> None:
    assert _parse_time(30) == 30.0


def test_parse_time_float() -> None:
    assert _parse_time(1.5) == 1.5


def test_parse_time_plain_string() -> None:
    assert _parse_time("45.5") == 45.5


def test_parse_time_mm_ss() -> None:
    assert _parse_time("1:30") == 90.0


def test_parse_time_hh_mm_ss() -> None:
    assert _parse_time("1:02:03") == 3723.0


def test_parse_time_mm_ss_with_decimal() -> None:
    assert _parse_time("0:30.5") == 30.5


# ── _source_key ──────────────────────────────────────────────────────────────

def test_source_key_strips_vid_prefix_and_extension() -> None:
    assert _source_key("VID_20240101_120000_001.mp4") == "20240101_120000_001"


def test_source_key_strips_lrv_prefix_and_extension() -> None:
    assert _source_key("LRV_20240101_120000_001.lrv") == "20240101_120000_001"


def test_source_key_no_prefix() -> None:
    assert _source_key("clip.mp4") == "clip"


def test_source_key_uses_basename() -> None:
    assert _source_key("/some/path/VID_20240101_120000.mp4") == "20240101_120000"


# ── validate_script ──────────────────────────────────────────────────────────

_CATALOG = [
    {"source_file": "VID_20240101_120000_001.mp4", "start_time": 0.0,  "end_time": 30.0, "caption": "opening"},
    {"source_file": "VID_20240101_120000_001.mp4", "start_time": 30.0, "end_time": 60.0, "caption": "middle"},
    {"source_file": "LRV_20240101_120000_001.lrv", "start_time": 60.0, "end_time": 90.0, "caption": "lrv clip"},
]


def test_validate_script_exact_match() -> None:
    script = [{"source_file": "VID_20240101_120000_001.mp4", "start_time": 0, "end_time": 30, "narration": "n"}]
    result = validate_script(script, _CATALOG)
    assert len(result) == 1
    assert result[0]["start_time"] == 0.0


def test_validate_script_fuzzy_time_within_tolerance() -> None:
    script = [{"source_file": "VID_20240101_120000_001.mp4", "start_time": 0.5, "end_time": 29.8, "narration": ""}]
    result = validate_script(script, _CATALOG)
    assert len(result) == 1


def test_validate_script_time_outside_tolerance_skipped() -> None:
    script = [{"source_file": "VID_20240101_120000_001.mp4", "start_time": 5.0, "end_time": 30.0, "narration": ""}]
    result = validate_script(script, _CATALOG)
    assert len(result) == 0


def test_validate_script_lrv_vid_cross_match() -> None:
    # LRV_ and VID_ share the same _source_key — should match
    script = [{"source_file": "VID_20240101_120000_001.mp4", "start_time": 60, "end_time": 90, "narration": ""}]
    result = validate_script(script, _CATALOG)
    assert len(result) == 1


def test_validate_script_narration_overrides_caption() -> None:
    script = [{"source_file": "VID_20240101_120000_001.mp4", "start_time": 0, "end_time": 30, "narration": "custom"}]
    result = validate_script(script, _CATALOG)
    assert result[0]["narration"] == "custom"


def test_validate_script_empty_narration_falls_back_to_caption() -> None:
    script = [{"source_file": "VID_20240101_120000_001.mp4", "start_time": 0, "end_time": 30, "narration": ""}]
    result = validate_script(script, _CATALOG)
    assert result[0]["narration"] == "opening"


# ── _repair_json ─────────────────────────────────────────────────────────────

def test_repair_json_converts_mm_ss_time_value() -> None:
    raw = '{"start_time": 1:30, "end_time": 2:00}'
    repaired = _repair_json(raw)
    assert '"1:30"' in repaired
    assert '"2:00"' in repaired


def test_repair_json_leaves_numeric_values_alone() -> None:
    raw = '{"start_time": 90, "end_time": 120}'
    assert _repair_json(raw) == raw


# ── _coerce_script_response ──────────────────────────────────────────────────

def test_coerce_list_passthrough() -> None:
    data = [{"source_file": "a.mp4"}]
    assert _coerce_script_response(data) == data


def test_coerce_dict_with_clips_key() -> None:
    clips = [{"source_file": "a.mp4"}]
    assert _coerce_script_response({"clips": clips}) == clips


def test_coerce_dict_with_script_key() -> None:
    clips = [{"source_file": "a.mp4"}]
    assert _coerce_script_response({"script": clips}) == clips


def test_coerce_non_list_raises() -> None:
    try:
        _coerce_script_response("not a list")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")


# ── _parse_json_or_recover_clips ─────────────────────────────────────────────

def test_parse_json_clean_array() -> None:
    content = '[{"source_file": "a.mp4", "start_time": 0, "end_time": 10, "narration": "x"}]'
    result = _parse_json_or_recover_clips(content)
    assert len(result) == 1
    assert result[0]["source_file"] == "a.mp4"


def test_parse_json_recovers_from_truncated_response() -> None:
    # Simulates an LLM response that was cut off mid-array
    content = (
        '[{"source_file": "a.mp4", "start_time": 0, "end_time": 10, "narration": "x"}, '
        '{"source_file": "b.mp4", "start_time": 20, "end_time": 30, "narration": "y"}, '
        '{"source_file": "c.mp4", "start_ti'
    )
    result = _parse_json_or_recover_clips(content)
    assert len(result) == 2
    assert result[0]["source_file"] == "a.mp4"


# ── format_catalog ───────────────────────────────────────────────────────────

def test_format_catalog_basic_structure() -> None:
    rows = [
        {"source_file": "clip.mp4", "start_time": 0.0, "end_time": 30.0, "caption": "intro"},
        {"source_file": "clip.mp4", "start_time": 30.0, "end_time": 60.0, "caption": "middle"},
    ]
    text = format_catalog(rows)
    assert "[clip.mp4]" in text
    assert "00:00-00:30" in text
    assert "intro" in text


def test_format_catalog_truncates_at_max_chars() -> None:
    rows = [{"source_file": "clip.mp4", "start_time": i * 30.0, "end_time": (i + 1) * 30.0, "caption": f"cap {i}"}
            for i in range(20)]
    full = format_catalog(rows)
    truncated = format_catalog(rows, max_chars=50)
    assert len(truncated) <= len(full)
    assert "truncated" in truncated


# ── _normalize_openai_base_url ───────────────────────────────────────────────

def test_normalize_url_appends_v1() -> None:
    assert _normalize_openai_base_url("http://localhost:8080") == "http://localhost:8080/v1"


def test_normalize_url_already_has_v1() -> None:
    assert _normalize_openai_base_url("http://localhost:8080/v1") == "http://localhost:8080/v1"


def test_normalize_url_strips_trailing_slash() -> None:
    assert _normalize_openai_base_url("http://localhost:8080/v1/") == "http://localhost:8080/v1"


def test_normalize_url_empty_raises() -> None:
    try:
        _normalize_openai_base_url("")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for empty URL")


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

