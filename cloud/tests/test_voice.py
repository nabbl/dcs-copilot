from __future__ import annotations

import asyncio

import pytest
from dcs_copilot_cloud.config import CloudSettings
from dcs_copilot_cloud.providers.base import ProviderBundle
from dcs_copilot_cloud.providers.factory import (
    ProviderConfigurationError,
    build_provider_bundle,
)
from dcs_copilot_cloud.providers.openai import (
    COPILOT_INSTRUCTION,
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
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


def test_provider_selection_is_configuration_driven() -> None:
    providers = build_provider_bundle(CloudSettings(openai_api_key="server-only-key"))
    assert isinstance(providers.stt, OpenAISTTProvider)
    assert isinstance(providers.llm, OpenAILLMProvider)
    assert isinstance(providers.tts, OpenAITTSProvider)


def test_copilot_prompt_separates_live_state_from_general_knowledge() -> None:
    assert "Only claim current aircraft facts" in COPILOT_INSTRUCTION
    assert "general aviation knowledge" in COPILOT_INSTRUCTION
    assert "empty issue list" in COPILOT_INSTRUCTION
    assert "include every returned gap" in COPILOT_INSTRUCTION
    assert "get_takeoff_readiness" in COPILOT_INSTRUCTION
    assert "get_flight_status" in COPILOT_INSTRUCTION
    assert "get_hornet_knowledge" in COPILOT_INSTRUCTION
    assert "walked through" in COPILOT_INSTRUCTION
    assert "one subsequent step" in COPILOT_INSTRUCTION
    assert "Never claim land-runway alignment" in COPILOT_INSTRUCTION


def test_missing_server_key_and_unknown_provider_fail_closed() -> None:
    with pytest.raises(ProviderConfigurationError, match="OPENAI_API_KEY"):
        build_provider_bundle(CloudSettings())
    with pytest.raises(ProviderConfigurationError, match="STT_PROVIDER=local"):
        build_provider_bundle(CloudSettings(openai_api_key="key", stt_provider="local"))


def test_pipecat_context_exposes_allowlisted_aircraft_tools() -> None:
    async def handler(_params) -> None:
        return None

    schemas = aircraft_tool_schemas(handler)
    assert {schema.name for schema in schemas} == {
        "get_aircraft_state",
        "get_active_issues",
        "get_recent_events",
        "get_flight_phase",
        "get_ground_ops_status",
        "get_takeoff_readiness",
        "get_flight_status",
        "get_hornet_knowledge",
        "get_checklist_status",
        "get_missing_checklist_items",
        "start_guided_checklist",
        "get_next_checklist_item",
        "confirm_manual_checklist_item",
        "stop_guided_checklist",
    }
    checklist = next(
        schema for schema in schemas if schema.name == "get_missing_checklist_items"
    )
    assert checklist.required == []
    assert set(checklist.properties) == {"checklist_id", "stage"}
    knowledge = next(
        schema for schema in schemas if schema.name == "get_hornet_knowledge"
    )
    assert "case_i_recovery" in knowledge.properties["topic"]["enum"]
    assert "airfield_vfr_landing" in knowledge.properties["topic"]["enum"]
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
    assert len(copilot_tool_schemas(handler)) == 21
    assert all(schema.handler is handler for schema in account_schemas)


class _FakeSTT(FrameProcessor):
    def __init__(self) -> None:
        super().__init__()
        self.audio = bytearray()
        self.saw_speech_start = False
        self.saw_speech_stop = False

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, VADUserStartedSpeakingFrame):
            self.saw_speech_start = True
        elif isinstance(frame, InputAudioRawFrame) and self.saw_speech_start:
            self.audio.extend(frame.audio)
        elif isinstance(frame, VADUserStoppedSpeakingFrame):
            self.saw_speech_stop = True
            await self.push_frame(
                TranscriptionFrame("Hello?", "pilot", "2026-01-01T00:00:00Z")
            )
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
        self.processor: FrameProcessor | None = None

    def create_processor(self) -> FrameProcessor:
        self.processor = self._processor_type()
        return self.processor


def test_pipecat_pipeline_uses_explicit_ptt_turn_and_streams_audio() -> None:
    pcm = b"\x01\x02" * 320
    stt_provider = _FakeProvider(_FakeSTT)

    async def scenario() -> tuple[str, str, list[bytes]]:
        pipeline = PipecatVoicePipeline(
            ProviderBundle(
                stt_provider,
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
                        pcm,
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
    assert isinstance(stt_provider.processor, _FakeSTT)
    assert stt_provider.processor.saw_speech_start
    assert stt_provider.processor.saw_speech_stop
    assert bytes(stt_provider.processor.audio) == pcm


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
