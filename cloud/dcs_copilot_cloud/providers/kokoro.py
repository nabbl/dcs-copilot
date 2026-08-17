"""Local Kokoro TTS provider, imported lazily for hosted compatibility."""

from __future__ import annotations

from dataclasses import dataclass

from pipecat.processors.frame_processor import FrameProcessor

from ..models import provision_kokoro
from ..runtime_paths import RuntimePaths


@dataclass(frozen=True, slots=True)
class KokoroTTSProvider:
    voice: str

    def create_processor(self) -> FrameProcessor:
        from pipecat.services.kokoro.tts import KokoroTTSService

        model, voices = provision_kokoro(
            RuntimePaths.discover().ensure().models / "kokoro"
        )

        return KokoroTTSService(
            model_path=str(model),
            voices_path=str(voices),
            settings=KokoroTTSService.Settings(voice=self.voice),
        )
