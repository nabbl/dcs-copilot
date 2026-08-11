"""PTT-scoped PCM capture and streamed PCM playback using PortAudio."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from typing import Any

from dcs_copilot_protocol import AudioFormat


class AudioUnavailableError(RuntimeError):
    pass


class PortAudioCapture:
    """Opens the microphone only between explicit start and stop calls."""

    def __init__(
        self,
        audio_format: AudioFormat,
        *,
        device_index: int | None = None,
    ) -> None:
        self.audio_format = audio_format
        self.device_index = device_index
        self._audio: Any = None
        self._stream: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._on_audio: Callable[[bytes], None] | None = None

    @property
    def active(self) -> bool:
        return self._stream is not None

    async def start(self, on_audio: Callable[[bytes], None]) -> None:
        if self.active:
            return
        self._loop = asyncio.get_running_loop()
        self._on_audio = on_audio
        try:
            await asyncio.to_thread(self._start_sync)
        except Exception as exc:
            await self.stop()
            raise AudioUnavailableError(
                f"microphone could not be opened: {exc}"
            ) from exc

    async def stop(self) -> None:
        await asyncio.to_thread(self._stop_sync)
        # PortAudio callbacks use call_soon_threadsafe. Yield once so the final
        # captured chunk is queued before the controller sends ptt.end.
        await asyncio.sleep(0)
        self._loop = None
        self._on_audio = None

    def _start_sync(self) -> None:
        import pyaudio  # type: ignore[import-untyped]

        audio = pyaudio.PyAudio()
        frames_per_buffer = (
            self.audio_format.sample_rate * self.audio_format.chunk_ms // 1000
        )

        def callback(
            input_data: bytes | None,
            _frame_count: int,
            _time_info: object,
            _status_flags: int,
        ) -> tuple[None, int]:
            loop = self._loop
            on_audio = self._on_audio
            if input_data and loop is not None and on_audio is not None:
                loop.call_soon_threadsafe(on_audio, bytes(input_data))
            return None, pyaudio.paContinue

        try:
            stream = audio.open(
                format=pyaudio.paInt16,
                channels=self.audio_format.channels,
                rate=self.audio_format.sample_rate,
                input=True,
                input_device_index=self.device_index,
                frames_per_buffer=frames_per_buffer,
                stream_callback=callback,
                start=False,
            )
            stream.start_stream()
        except Exception:
            audio.terminate()
            raise
        self._audio = audio
        self._stream = stream

    def _stop_sync(self) -> None:
        stream = self._stream
        audio = self._audio
        self._stream = None
        self._audio = None
        if stream is not None:
            if stream.is_active():
                stream.stop_stream()
            stream.close()
        if audio is not None:
            audio.terminate()


class PortAudioPlayback:
    """Writes cloud PCM to the configured output and supports hard interruption."""

    def __init__(
        self,
        audio_format: AudioFormat,
        *,
        device_index: int | None = None,
    ) -> None:
        self.audio_format = audio_format
        self.device_index = device_index
        self._audio: Any = None
        self._stream: Any = None
        self._lock = threading.Lock()
        self._muted = False

    @property
    def muted(self) -> bool:
        with self._lock:
            return self._muted

    async def play(self, audio: bytes) -> None:
        if not audio:
            return
        try:
            await asyncio.to_thread(self._play_sync, audio)
        except Exception as exc:
            await self.interrupt()
            raise AudioUnavailableError(f"audio output failed: {exc}") from exc

    async def interrupt(self) -> None:
        await asyncio.to_thread(self._close_sync)

    async def toggle_muted(
        self,
        *,
        muted_feedback: bytes = b"",
        unmuted_feedback: bytes = b"",
    ) -> bool:
        return await asyncio.to_thread(
            self._toggle_muted_sync,
            muted_feedback,
            unmuted_feedback,
        )

    async def close(self) -> None:
        await self.interrupt()

    def _play_sync(self, payload: bytes) -> None:
        with self._lock:
            if self._muted:
                return
            self._write_locked(payload)

    def _close_sync(self) -> None:
        with self._lock:
            self._close_locked()

    def _toggle_muted_sync(
        self,
        muted_feedback: bytes,
        unmuted_feedback: bytes,
    ) -> bool:
        with self._lock:
            self._muted = not self._muted
            if self._muted:
                self._close_locked()
            feedback = muted_feedback if self._muted else unmuted_feedback
            if feedback:
                self._write_locked(feedback)
            if self._muted:
                self._close_locked()
            return self._muted

    def _write_locked(self, payload: bytes) -> None:
        import pyaudio

        if self._stream is None:
            audio = pyaudio.PyAudio()
            try:
                stream = audio.open(
                    format=pyaudio.paInt16,
                    channels=self.audio_format.channels,
                    rate=self.audio_format.sample_rate,
                    output=True,
                    output_device_index=self.device_index,
                )
            except Exception:
                audio.terminate()
                raise
            self._audio = audio
            self._stream = stream
        self._stream.write(payload, exception_on_underflow=False)

    def _close_locked(self) -> None:
        stream = self._stream
        audio = self._audio
        self._stream = None
        self._audio = None
        if stream is not None:
            if stream.is_active():
                stream.stop_stream()
            stream.close()
        if audio is not None:
            audio.terminate()
