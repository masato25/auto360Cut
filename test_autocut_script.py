
from pathlib import Path

from autocut_script import (
    OUTPUT_LAYOUT_CHOICES,
    DEFAULT_CAPTION_DURATION,
    _build_script_system_prompt,
    _choose_output_layout,
    _coerce_script_response,
    _escape_drawtext_text,
    _opening_caption_drawtext_filter,
    _band_caption_drawtext_filter,
    _opening_caption_fontfile,
    _normalize_opening_caption_duration,
    _music_candidates,
    _select_music_file,
    _normalize_music_volume,
    render,
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
    assert _normalize_opening_caption_duration(None) == DEFAULT_CAPTION_DURATION
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


def test_band_caption_drawtext_filter_uses_bottom_right_and_custom_box_color(monkeypatch) -> None:
    monkeypatch.setenv("AUTOCUT_OPENING_CAPTION_FONT", "/tmp/Noto Sans CJK.ttc")

    vf = _band_caption_drawtext_filter("Channel A", layout="landscape", box_color="blue@0.7")

    assert "text='Channel A'" in vf
    assert "x=w-text_w-48" in vf
    assert "y=h-text_h-48" in vf
    assert "fontsize=30" in vf
    assert "boxcolor=blue@0.7" in vf


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


# ── background music ────────────────────────────────────────────────────────


def test_music_candidates_reads_supported_audio_files(monkeypatch, tmp_path) -> None:
    (tmp_path / "a.mp3").write_text("music", encoding="utf-8")
    (tmp_path / "b.txt").write_text("not music", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "c.WAV").write_text("music", encoding="utf-8")

    monkeypatch.setenv("AUTOCUT_MUSIC_DIR", str(tmp_path))

    assert _music_candidates() == [str((tmp_path / "a.mp3").resolve()), str((nested / "c.WAV").resolve())]


def test_select_music_file_is_deterministic(tmp_path) -> None:
    (tmp_path / "a.mp3").write_text("music", encoding="utf-8")
    (tmp_path / "b.mp3").write_text("music", encoding="utf-8")
    selected = [{"source_file": "clip.mp4", "start_time": 0, "end_time": 1}]

    first = _select_music_file(selected=selected, output_path="out.mp4", music_dir=str(tmp_path))
    second = _select_music_file(selected=selected, output_path="out.mp4", music_dir=str(tmp_path))

    assert first == second
    assert first in {str((tmp_path / "a.mp3").resolve()), str((tmp_path / "b.mp3").resolve())}


def test_normalize_music_volume_default_and_rejects_negative(monkeypatch) -> None:
    monkeypatch.delenv("AUTOCUT_MUSIC_VOLUME", raising=False)
    assert _normalize_music_volume(None) == 0.18
    assert _normalize_music_volume("0.3") == 0.3
    try:
        _normalize_music_volume(-0.1)
    except ValueError as exc:
        assert "non-negative" in str(exc)
    else:
        raise AssertionError("negative volume should be rejected")


# ── render caption ordering ─────────────────────────────────────────────────


def test_render_env_band_text_applies_to_opening_and_closing(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AUTOCUT_BAND_TEXT", "Channel")
    rendered_titles = []
    normalized = []
    concat_files = []
    mixed_music = []

    def fake_get_ffmpeg() -> str:
        return "ffmpeg"

    def fake_render_caption(ffmpeg, *, text, output_path, layout, duration=None, band_text=None, band_box_color=None):
        rendered_titles.append((text, output_path, duration, band_text, band_box_color))
        Path(output_path).write_text(text, encoding="utf-8")
        return output_path

    def fake_normalize(ffmpeg, input_path, output_path, *, layout):
        normalized.append(output_path)
        Path(output_path).write_text("clip", encoding="utf-8")
        return output_path

    def fake_apply_music(ffmpeg, input_path, output_path, music_path, *, volume=None):
        mixed_music.append((input_path, output_path, music_path, volume))
        Path(output_path).write_text("music output", encoding="utf-8")
        return output_path

    def fake_run(cmd, capture_output=True, text=True):
        if "concat" in cmd:
            list_path = Path(cmd[cmd.index("-i") + 1])
            concat_files.extend(
                line.split("'", 2)[1]
                for line in list_path.read_text(encoding="utf-8").splitlines()
            )
            Path(cmd[-1]).write_text("output", encoding="utf-8")
        class Result:
            returncode = 0
            stderr = ""
        return Result()

    monkeypatch.setattr("autocut_script._get_ffmpeg", fake_get_ffmpeg)
    monkeypatch.setattr("autocut_script._render_opening_caption_clip", fake_render_caption)
    monkeypatch.setattr("autocut_script._normalize_clip_for_concat", fake_normalize)
    monkeypatch.setattr("autocut_script._apply_background_music", fake_apply_music)
    monkeypatch.setattr("autocut_script._resolve_hq_source", lambda source_file, hq_dir=None: source_file)
    monkeypatch.setattr("autocut_script.subprocess.run", fake_run)

    import sys
    import types
    trimmer = types.ModuleType("sentrysearch.trimmer")
    def fake_trim_clip(source_file, start_time, end_time, output_path, padding=1.0):
        Path(output_path).write_text("raw", encoding="utf-8")
    trimmer.trim_clip = fake_trim_clip
    sentrysearch = types.ModuleType("sentrysearch")
    sentrysearch.trimmer = trimmer
    monkeypatch.setitem(sys.modules, "sentrysearch", sentrysearch)
    monkeypatch.setitem(sys.modules, "sentrysearch.trimmer", trimmer)

    music_dir = tmp_path / "music"
    music_dir.mkdir()
    music_file = music_dir / "track.mp3"
    music_file.write_text("music", encoding="utf-8")

    output = tmp_path / "out.mp4"
    render(
        [{"source_file": "clip.mp4", "start_time": 0, "end_time": 1}],
        output_path=str(output),
        hq_dir=None,
        output_layout="landscape",
        opening_caption="Start",
        opening_caption_duration=1.5,
        closing_caption="End",
        closing_caption_duration=2.5,
        opening_band="Channel",
        closing_band="Subscribe",
        band_box_color="blue@0.7",
        auto_music=True,
        music_dir=str(music_dir),
        music_volume=0.25,
    )

    # Opening/closing captions intentionally share one duration; if both legacy
    # args are passed, opening_caption_duration wins for compatibility.
    assert rendered_titles == [
        ("Start", str(tmp_path / "out_opening_caption.mp4"), 1.5, "Channel", "blue@0.7"),
        ("End", str(tmp_path / "out_closing_caption.mp4"), 1.5, "Channel", "blue@0.7"),
    ]
    assert concat_files == [str(tmp_path / "out_opening_caption.mp4"), str(tmp_path / "out_0_norm.mp4"), str(tmp_path / "out_closing_caption.mp4")]
    assert len(mixed_music) == 1
    assert mixed_music[0][1] == str(tmp_path / "out_music.mp4")
    assert mixed_music[0][2] == str(music_file.resolve())
    assert mixed_music[0][3] == 0.25
    assert output.exists()


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

