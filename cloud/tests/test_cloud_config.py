from __future__ import annotations

from pathlib import Path

import pytest
from dcs_copilot_cloud.app import create_app
from dcs_copilot_cloud.config import CloudSettings


def test_cloud_settings_load_dotenv_without_overriding_environment(
    tmp_path: Path, monkeypatch
) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "CLOUD_PORT=9000\n"
        "DCS_COPILOT_DEV_TOKEN=file-token\n"
        "OPENAI_API_KEY=server-key\n"
        "LLM_MODEL=gpt-test\n"
        "CLOUD_TELEMETRY_STALE_SECONDS=2.5\n"
    )
    monkeypatch.setenv("CLOUD_PORT", "9100")
    monkeypatch.delenv("DCS_COPILOT_DEV_TOKEN", raising=False)
    settings = CloudSettings.from_env(dotenv)
    assert settings.port == 9100
    assert settings.dev_access_token == "file-token"
    assert settings.openai_api_key == "server-key"
    assert settings.llm_model == "gpt-test"
    assert settings.telemetry_stale_seconds == 2.5
    assert settings.tts_model == "gpt-4o-mini-tts"


def test_cloud_settings_default_to_low_latency_luna_model(monkeypatch) -> None:
    monkeypatch.delenv("LLM_MODEL", raising=False)

    settings = CloudSettings.from_env(Path("/does/not/exist"))

    assert settings.llm_model == "gpt-5.6-luna"


def test_non_loopback_service_rejects_development_credentials() -> None:
    with pytest.raises(ValueError, match="DEV_TOKEN"):
        create_app(CloudSettings(host="0.0.0.0"))
    with pytest.raises(ValueError, match="AUTH_SIGNING_KEY"):
        create_app(
            CloudSettings(
                host="0.0.0.0",
                dev_access_token="",
            )
        )
