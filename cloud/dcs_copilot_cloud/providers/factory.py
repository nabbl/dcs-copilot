"""Configuration-driven voice provider selection."""

from __future__ import annotations

from ..config import CloudSettings
from .base import ProviderBundle
from .openai import OpenAILLMProvider, OpenAISTTProvider, OpenAITTSProvider


class ProviderConfigurationError(ValueError):
    pass


def build_provider_bundle(settings: CloudSettings) -> ProviderBundle:
    providers = {
        "STT_PROVIDER": settings.stt_provider,
        "LLM_PROVIDER": settings.llm_provider,
        "TTS_PROVIDER": settings.tts_provider,
    }
    unsupported = [
        f"{name}={value}" for name, value in providers.items() if value != "openai"
    ]
    if unsupported:
        raise ProviderConfigurationError(
            "unsupported voice provider configuration: " + ", ".join(unsupported)
        )
    if not settings.voice_configured:
        raise ProviderConfigurationError(
            "OPENAI_API_KEY is required by the configured cloud voice providers"
        )
    if settings.llm_max_output_tokens <= 0:
        raise ProviderConfigurationError("LLM_MAX_OUTPUT_TOKENS must be positive")
    return ProviderBundle(
        stt=OpenAISTTProvider(
            settings.openai_api_key,
            settings.stt_model,
            settings.stt_language,
        ),
        llm=OpenAILLMProvider(
            settings.openai_api_key,
            settings.llm_model,
            settings.llm_max_output_tokens,
        ),
        tts=OpenAITTSProvider(
            settings.openai_api_key,
            settings.tts_model,
            settings.tts_voice,
        ),
    )
