from __future__ import annotations

from pathlib import Path

from dcs_copilot.config import Settings
from dcs_copilot.events import SpeechMode


def test_settings_load_dotenv_without_overriding_environment(
    tmp_path: Path, monkeypatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DCS_BIOS_PORT=6000\n"
        "DCS_COPILOT_CLOUD_URL=ws://localhost:9000/v1/realtime\n"
        "COPILOT_PTT_KEY=f14\n"
        "COPILOT_PTT_DEVICE=2\n"
        "COPILOT_PTT_BUTTON=5\n"
        "COPILOT_SPEECH_MODE=coach\n"
        "LOG_LEVEL=debug\n"
    )
    monkeypatch.setenv("DCS_BIOS_PORT", "7000")
    settings = Settings.from_env(env_file)
    assert settings.port == 7000
    assert settings.cloud_url == "ws://localhost:9000/v1/realtime"
    assert settings.copilot_ptt_key == "F14"
    assert settings.copilot_ptt_device == 2
    assert settings.copilot_ptt_button == 5
    assert settings.speech_mode is SpeechMode.COACH
    assert settings.audio_sample_rate == 16_000
    assert settings.audio_output_sample_rate == 24_000
    assert settings.log_level == "DEBUG"
    assert not hasattr(settings, "openai_api_key")
