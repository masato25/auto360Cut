
from autocut_script import (
    OUTPUT_LAYOUT_CHOICES,
    _build_script_system_prompt,
    _choose_output_layout,
    _render_layout_filter,
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
    assert "minutes" not in prompt


def test_system_prompt_none_duration_omits_instruction() -> None:
    prompt = _build_script_system_prompt(auto_prompt=False, prompt="", target_duration_minutes=None)
    assert "minutes" not in prompt

