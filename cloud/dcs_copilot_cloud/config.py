"""Environment-backed cloud configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .credentials import (
    ChainedCredentialStore,
    CredentialStore,
    EnvironmentCredentialStore,
    KeyringCredentialStore,
)
from .runtime_paths import RuntimePaths

LOCAL_DEVELOPMENT_SIGNING_KEY = "local-development-signing-key-change-me"


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


@dataclass(frozen=True, slots=True)
class CloudSettings:
    host: str = "127.0.0.1"
    port: int = 8000
    dev_access_token: str = field(default="local-dev-token", repr=False)
    database_url: str = field(default="sqlite+aiosqlite:///:memory:", repr=False)
    auth_signing_key: str = field(default=LOCAL_DEVELOPMENT_SIGNING_KEY, repr=False)
    auth_access_token_seconds: int = 900
    auth_refresh_token_days: int = 30
    handshake_timeout_seconds: float = 5.0
    log_level: str = "info"
    max_utterance_seconds: float = 60.0
    telemetry_stale_seconds: float = 30.0
    deployment: str = "local"
    provision_models: bool = False
    openai_api_key: str = field(default="", repr=False)
    stt_provider: str = "openai"
    stt_model: str = "gpt-transcribe"
    stt_language: str = "en"
    llm_provider: str = "openai"
    llm_model: str = "gpt-5.6-luna"
    llm_max_output_tokens: int = 80
    tts_provider: str = "openai"
    tts_model: str = "gpt-4o-mini-tts"
    tts_voice: str = "marin"

    @property
    def voice_configured(self) -> bool:
        return bool(self.openai_api_key.strip())

    @classmethod
    def from_env(
        cls,
        dotenv_path: Path | None = None,
        *,
        credential_store: CredentialStore | None = None,
    ) -> CloudSettings:
        _load_dotenv(dotenv_path or Path.cwd() / ".env")
        deployment = os.getenv("MARA_DEPLOYMENT", "local").strip().lower()
        if deployment not in {"local", "remote", "hosted"}:
            raise ValueError("MARA_DEPLOYMENT must be local, remote, or hosted")
        paths = RuntimePaths.discover()
        credentials = credential_store or ChainedCredentialStore(
            EnvironmentCredentialStore(), KeyringCredentialStore()
        )
        default_tts_provider = "kokoro" if deployment == "local" else "openai"
        default_tts_voice = "af_heart" if default_tts_provider == "kokoro" else "marin"
        return cls(
            host=os.getenv("CLOUD_HOST", "127.0.0.1"),
            port=int(os.getenv("CLOUD_PORT", "8000")),
            dev_access_token=os.getenv("DCS_COPILOT_DEV_TOKEN", "local-dev-token"),
            database_url=os.getenv(
                "DCS_COPILOT_DATABASE_URL",
                paths.database_url,
            ).strip(),
            auth_signing_key=os.getenv(
                "DCS_COPILOT_AUTH_SIGNING_KEY",
                LOCAL_DEVELOPMENT_SIGNING_KEY,
            ),
            auth_access_token_seconds=int(
                os.getenv("AUTH_ACCESS_TOKEN_SECONDS", "900")
            ),
            auth_refresh_token_days=int(os.getenv("AUTH_REFRESH_TOKEN_DAYS", "30")),
            handshake_timeout_seconds=float(
                os.getenv("CLOUD_HANDSHAKE_TIMEOUT_SECONDS", "5")
            ),
            log_level=os.getenv("CLOUD_LOG_LEVEL", "info").lower(),
            max_utterance_seconds=float(os.getenv("CLOUD_MAX_UTTERANCE_SECONDS", "60")),
            telemetry_stale_seconds=float(
                os.getenv("CLOUD_TELEMETRY_STALE_SECONDS", "30")
            ),
            deployment=deployment,
            provision_models=os.getenv(
                "MARA_PROVISION_MODELS", "1" if deployment == "local" else "0"
            )
            .strip()
            .lower()
            not in {"0", "false", "no"},
            openai_api_key=credentials.get_openai_key() or "",
            stt_provider=os.getenv("STT_PROVIDER", "openai").strip().lower(),
            stt_model=os.getenv("STT_MODEL", "gpt-transcribe").strip(),
            stt_language=os.getenv("STT_LANGUAGE", "en").strip().lower(),
            llm_provider=os.getenv("LLM_PROVIDER", "openai").strip().lower(),
            llm_model=os.getenv("LLM_MODEL", "gpt-5.6-luna").strip(),
            llm_max_output_tokens=int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "80")),
            tts_provider=os.getenv("TTS_PROVIDER", default_tts_provider)
            .strip()
            .lower(),
            tts_model=os.getenv("TTS_MODEL", "gpt-4o-mini-tts").strip(),
            tts_voice=os.getenv("TTS_VOICE", default_tts_voice).strip().lower(),
        )
