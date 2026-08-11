"""Small procedural PCM cues for local client actions."""

from __future__ import annotations

import math
import sys
from array import array

from dcs_copilot_protocol import AudioFormat

_MUTE_FREQUENCIES = (660.0, 440.0)
_UNMUTE_FREQUENCIES = (440.0, 660.0)


def mute_tone(audio_format: AudioFormat) -> bytes:
    return _tone_sequence(audio_format, _MUTE_FREQUENCIES)


def unmute_tone(audio_format: AudioFormat) -> bytes:
    return _tone_sequence(audio_format, _UNMUTE_FREQUENCIES)


def _tone_sequence(
    audio_format: AudioFormat,
    frequencies: tuple[float, ...],
    *,
    tone_seconds: float = 0.07,
    gap_seconds: float = 0.025,
    amplitude: float = 0.14,
) -> bytes:
    samples = array("h")
    tone_count = max(1, round(audio_format.sample_rate * tone_seconds))
    gap_count = max(0, round(audio_format.sample_rate * gap_seconds))
    fade_count = max(1, round(audio_format.sample_rate * 0.008))
    for frequency_index, frequency in enumerate(frequencies):
        for index in range(tone_count):
            envelope = min(
                1.0,
                index / fade_count,
                (tone_count - index - 1) / fade_count,
            )
            sample = round(
                math.sin(2.0 * math.pi * frequency * index / audio_format.sample_rate)
                * amplitude
                * envelope
                * 32767
            )
            samples.extend((sample,) * audio_format.channels)
        if frequency_index != len(frequencies) - 1:
            samples.extend((0,) * gap_count * audio_format.channels)
    if sys.byteorder != "little":
        samples.byteswap()
    return samples.tobytes()
