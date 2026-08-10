from __future__ import annotations

import asyncio
import io
import wave

import pytest
from dcs_copilot_cloud.config import CloudSettings
from dcs_copilot_cloud.providers.base import ProviderBundle
from dcs_copilot_cloud.providers.factory import (
    ProviderConfigurationError,
    build_provider_bundle,
)
from dcs_copilot_cloud.providers.openai import (
    OpenAILLMProvider,
    OpenAISTTProvider,
    OpenAITTSProvider,
)
from dcs_copilot_cloud.voice import (
    PipecatVoicePipeline,
    VoiceAnnouncement,
    VoiceTurn,
    account_tool_schemas,
    aircraft_tool_schemas,
    copilot_tool_schemas,
    pcm_to_wav,
)
from dcs_copilot_protocol import AudioFormat
from pipecat.frames.frames import (
    Frame,
    InputAudioRawFrame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


def test_pcm_is_wrapped_as_bounded_wav_for_file_transcription() -> None:
    pcm = b"\x01\x02" * 320
    encoded = pcm_to_wav(pcm, AudioFormat())
    with wave.open(io.BytesIO(encoded), "rb") as wav:
        assert wav.getframerate() == 16_000
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.readframes(wav.getnframes()) == pcm


def test_provider_selection_is_configuration_driven() -> None:
    providers = build_provider_bundle(CloudSettings(openai_api_key="server-only-key"))
    assert isinstance(providers.stt, OpenAISTTProvider)
    assert isinstance(providers.llm, OpenAILLMProvider)
    assert isinstance(providers.tts, OpenAITTSProvider)


def test_missing_server_key_and_unknown_provider_fail_closed() -> None:
    with pytest.raises(ProviderConfigurationError, match="OPENAI_API_KEY"):
        build_provider_bundle(CloudSettings())
    with pytest.raises(ProviderConfigurationError, match="STT_PROVIDER=local"):
        build_provider_bundle(CloudSettings(openai_api_key="key", stt_provider="local"))


def test_pipecat_context_exposes_only_milestone_four_aircraft_tools() -> None:
    async def handler(_params) -> None:
        return None

    schemas = aircraft_tool_schemas(handler)
    assert {schema.name for schema in schemas} == {
        "get_aircraft_state",
        "get_active_issues",
        "get_recent_events",
        "get_flight_phase",
    }
    assert all(schema.handler is handler for schema in schemas)


def test_pipecat_context_separates_allowlisted_account_and_aircraft_tools() -> None:
    async def handler(_params) -> None:
        return None

    account_schemas = account_tool_schemas(handler)
    assert {schema.name for schema in account_schemas} == {
        "get_pilot_memories",
        "remember_pilot_fact",
        "forget_pilot_fact",
        "get_aircraft_preferences",
        "set_chatter_level",
        "get_flight_history",
        "get_pilot_habits",
    }
    assert len(copilot_tool_schemas(handler)) == 11
    assert all(schema.handler is handler for schema in account_schemas)


class _FakeSTT(FrameProcessor):
    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, InputAudioRawFrame):
            await self.push_frame(
                TranscriptionFrame("Hello?", "pilot", "2026-01-01T00:00:00Z")
            )
        else:
            await self.push_frame(frame, direction)


class _FakeLLM(FrameProcessor):
    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMContextFrame):
            await self.push_frame(LLMFullResponseStartFrame())
            await self.push_frame(LLMTextFrame("Ready."))
            await self.push_frame(LLMFullResponseEndFrame())
        else:
            await self.push_frame(frame, direction)


class _FakeTTS(FrameProcessor):
    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMTextFrame):
            await self.push_frame(TTSAudioRawFrame(b"\x10\x20" * 240, 24_000, 1))
        await self.push_frame(frame, direction)


class _FakeProvider:
    def __init__(self, processor_type: type[FrameProcessor]) -> None:
        self._processor_type = processor_type

    def create_processor(self) -> FrameProcessor:
        return self._processor_type()


def test_pipecat_pipeline_uses_explicit_ptt_turn_and_streams_audio() -> None:
    async def scenario() -> tuple[str, str, list[bytes]]:
        pipeline = PipecatVoicePipeline(
            ProviderBundle(
                _FakeProvider(_FakeSTT),
                _FakeProvider(_FakeLLM),
                _FakeProvider(_FakeTTS),
            )
        )
        chunks: list[bytes] = []

        async def output(audio: bytes) -> None:
            chunks.append(audio)

        try:
            result = await asyncio.wait_for(
                pipeline.respond(
                    VoiceTurn(
                        b"\x01\x02" * 320,
                        AudioFormat(),
                        AudioFormat(sample_rate=24_000),
                    ),
                    output,
                ),
                timeout=2,
            )
            return result.transcript, result.response_text, chunks
        finally:
            await pipeline.close()

    transcript, response, chunks = asyncio.run(scenario())
    assert transcript == "Hello?"
    assert response == "Ready."
    assert chunks == [b"\x10\x20" * 240]


def test_pipecat_proactive_announcement_bypasses_stt_and_streams_cloud_tts() -> None:
    async def scenario() -> tuple[str, list[bytes]]:
        pipeline = PipecatVoicePipeline(
            ProviderBundle(
                _FakeProvider(_FakeSTT),
                _FakeProvider(_FakeLLM),
                _FakeProvider(_FakeTTS),
            )
        )
        chunks: list[bytes] = []

        async def output(audio: bytes) -> None:
            chunks.append(audio)

        try:
            response = await asyncio.wait_for(
                pipeline.announce(
                    VoiceAnnouncement(
                        "Master Caution.",
                        AudioFormat(),
                        AudioFormat(sample_rate=24_000),
                    ),
                    output,
                ),
                timeout=2,
            )
            return response, chunks
        finally:
            await pipeline.close()

    response, chunks = asyncio.run(scenario())
    assert response == "Master Caution."
    assert chunks == [b"\x10\x20" * 240]
