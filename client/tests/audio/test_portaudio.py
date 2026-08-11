from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

from dcs_copilot.audio.feedback import mute_tone, unmute_tone
from dcs_copilot.audio.portaudio import PortAudioPlayback
from dcs_copilot_protocol import AudioFormat


class FakeStream:
    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.stopped = False
        self.closed = False

    def write(self, payload: bytes, *, exception_on_underflow: bool) -> None:
        assert exception_on_underflow is False
        self.writes.append(payload)

    def is_active(self) -> bool:
        return not self.stopped

    def stop_stream(self) -> None:
        self.stopped = True

    def close(self) -> None:
        self.closed = True


class FakePyAudio:
    def __init__(self) -> None:
        self.stream = FakeStream()
        self.terminated = False

    def open(self, **_kwargs: object) -> FakeStream:
        return self.stream

    def terminate(self) -> None:
        self.terminated = True


def test_playback_toggle_immediately_closes_and_suppresses_audio(monkeypatch) -> None:
    audio_instances: list[FakePyAudio] = []

    def create_audio() -> FakePyAudio:
        audio = FakePyAudio()
        audio_instances.append(audio)
        return audio

    monkeypatch.setitem(
        sys.modules,
        "pyaudio",
        SimpleNamespace(paInt16=8, PyAudio=create_audio),
    )
    playback = PortAudioPlayback(AudioFormat(sample_rate=24_000))

    async def scenario() -> None:
        assert (
            await playback.toggle_muted(
                muted_feedback=b"mute-tone",
                unmuted_feedback=b"unmute-tone",
            )
            is True
        )
        await playback.play(b"muted")
        assert len(audio_instances) == 1

        assert (
            await playback.toggle_muted(
                muted_feedback=b"mute-tone",
                unmuted_feedback=b"unmute-tone",
            )
            is False
        )
        await playback.play(b"audible")
        assert audio_instances[1].stream.writes == [b"unmute-tone", b"audible"]

        assert (
            await playback.toggle_muted(
                muted_feedback=b"mute-tone",
                unmuted_feedback=b"unmute-tone",
            )
            is True
        )

    asyncio.run(scenario())
    assert [audio.stream.writes for audio in audio_instances] == [
        [b"mute-tone"],
        [b"unmute-tone", b"audible"],
        [b"mute-tone"],
    ]
    assert all(audio.stream.closed for audio in audio_instances)
    assert all(audio.terminated for audio in audio_instances)


def test_mute_feedback_tones_are_short_and_distinct() -> None:
    audio_format = AudioFormat(sample_rate=24_000)

    muted = mute_tone(audio_format)
    unmuted = unmute_tone(audio_format)

    assert muted
    assert unmuted
    assert muted != unmuted
    assert len(muted) < audio_format.sample_rate
