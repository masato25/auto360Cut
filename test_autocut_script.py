
from autocut_script import (
    OUTPUT_LAYOUT_CHOICES,
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

