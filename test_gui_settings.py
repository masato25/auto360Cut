from pathlib import Path

from gui import settings


def test_gui_env_fields_include_gemini_and_self_hosted_llm_defaults() -> None:
    defaults = {key: default for key, _label, default in settings.ENV_FIELDS}

    assert defaults["AUTOCUT_BACKEND"] == "local-api"
    assert defaults["GEMINI_API_KEY"] == ""
    assert defaults["AUTOCUT_SCRIPT_API_BASE"] == "http://0.0.0.0:8080/v1"
    assert defaults["AUTOCUT_SCRIPT_API_KEY"] == "not-needed"
    assert defaults["AUTOCUT_SCRIPT_API_MODEL"] == "your-openai-compatible-llm"


def test_write_env_values_preserves_unrelated_lines_and_adds_gemini_deepseek(tmp_path: Path, monkeypatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "# existing config\n"
        "AUTOCUT_BACKEND=local-api\n"
        "UNRELATED=value\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "ENV_PATH", env_path)

    settings.write_env_values(
        {
            "AUTOCUT_BACKEND": "gemini",
            "GEMINI_API_KEY": "gemini key with spaces",
            "AUTOCUT_SCRIPT_API_BASE": "https://api.deepseek.com/v1",
            "AUTOCUT_SCRIPT_API_KEY": "deepseek-key",
            "AUTOCUT_SCRIPT_API_MODEL": "deepseek-chat",
        },
        path=env_path,
    )

    written = env_path.read_text(encoding="utf-8")
    assert "# existing config" in written
    assert "AUTOCUT_BACKEND=gemini" in written
    assert "UNRELATED=value" in written
    assert 'GEMINI_API_KEY="gemini key with spaces"' in written
    assert "AUTOCUT_SCRIPT_API_BASE=https://api.deepseek.com/v1" in written
    assert "AUTOCUT_SCRIPT_API_KEY=deepseek-key" in written
    assert "AUTOCUT_SCRIPT_API_MODEL=deepseek-chat" in written


def test_load_env_values_reads_gemini_key(tmp_path: Path, monkeypatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("GEMINI_API_KEY=abc123\n", encoding="utf-8")
    monkeypatch.setattr(settings, "ENV_PATH", env_path)

    values = settings.load_env_values(["GEMINI_API_KEY"])

    assert values["GEMINI_API_KEY"] == "abc123"
