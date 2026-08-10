"""Interfaces that keep the voice pipeline independent of AI vendors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pipecat.processors.frame_processor import FrameProcessor


class STTProvider(Protocol):
    def create_processor(self) -> FrameProcessor: ...


class LLMProvider(Protocol):
    def create_processor(self) -> FrameProcessor: ...


class TTSProvider(Protocol):
    def create_processor(self) -> FrameProcessor: ...


@dataclass(frozen=True, slots=True)
class ProviderBundle:
    stt: STTProvider
    llm: LLMProvider
    tts: TTSProvider
