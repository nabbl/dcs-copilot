"""Local Kokoro TTS provider, imported lazily for hosted compatibility."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pipecat.processors.frame_processor import FrameProcessor

from ..models import provision_kokoro
from ..runtime_paths import RuntimePaths


def _create_service(model: Path, voices: Path, voice: str) -> FrameProcessor:
    from pipecat.services.kokoro.tts import KokoroTTSService

    return KokoroTTSService(
        model_path=str(model),
        voices_path=str(voices),
        settings=KokoroTTSService.Settings(voice=voice),
    )


def validate_kokoro_runtime(model: Path, voices: Path, voice: str) -> None:
    """Load the packaged ONNX runtime now instead of failing on the first turn."""

    service = _create_service(model, voices, voice)
    del service


@dataclass(frozen=True, slots=True)
class KokoroTTSProvider:
    voice: str

    def create_processor(self) -> FrameProcessor:
        model, voices = provision_kokoro(
            RuntimePaths.discover().ensure().models / "kokoro"
        )
        return _create_service(model, voices, self.voice)
