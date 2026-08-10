"""OpenAI implementations of the provider-neutral voice interfaces."""

from __future__ import annotations

from dataclasses import dataclass

from pipecat.processors.frame_processor import FrameProcessor
from pipecat.services.openai.responses.llm import OpenAIResponsesLLMService
from pipecat.services.openai.stt import OpenAISTTService
from pipecat.services.openai.tts import OpenAITTSService

COPILOT_INSTRUCTION = """You are a combat copilot speaking to a pilot in flight.
Reply with one concise spoken sentence, normally under twelve words.
Use the narrow aircraft tools whenever a question depends on live cockpit state.
For "what did I forget" or "anything wrong", call get_active_issues.
Treat unavailable or stale telemetry as unknown and never infer or guess it.
Only claim aircraft facts returned by a tool in the current conversation.
If a tool is unavailable or times out, say you cannot read that state right now.
Use calm, direct aviation phrasing and no markdown."""

AVIATION_VOCABULARY = (
    "Hornet, AMRAAM, Sidewinder, TACAN, Bingo, Joker, BRAA, SA-10, "
    "Fox Three, Master Arm, Master Caution"
)


@dataclass(frozen=True, slots=True)
class OpenAISTTProvider:
    api_key: str
    model: str
    language: str

    def create_processor(self) -> FrameProcessor:
        return OpenAISTTService(
            api_key=self.api_key,
            settings=OpenAISTTService.Settings(
                model=self.model,
                language=self.language,
                prompt=AVIATION_VOCABULARY,
            ),
        )


@dataclass(frozen=True, slots=True)
class OpenAILLMProvider:
    api_key: str
    model: str
    max_output_tokens: int

    def create_processor(self) -> FrameProcessor:
        return OpenAIResponsesLLMService(
            api_key=self.api_key,
            settings=OpenAIResponsesLLMService.Settings(
                model=self.model,
                system_instruction=COPILOT_INSTRUCTION,
                max_completion_tokens=self.max_output_tokens,
            ),
        )


@dataclass(frozen=True, slots=True)
class OpenAITTSProvider:
    api_key: str
    model: str
    voice: str

    def create_processor(self) -> FrameProcessor:
        return OpenAITTSService(
            api_key=self.api_key,
            sample_rate=24_000,
            settings=OpenAITTSService.Settings(
                model=self.model,
                voice=self.voice,
                instructions="Speak calmly, clearly, and briefly like an aircraft intercom.",
            ),
        )
