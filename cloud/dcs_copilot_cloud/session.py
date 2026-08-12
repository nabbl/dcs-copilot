"""Pure state machine for an authenticated realtime client session."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from dcs_copilot_protocol import (
    PROTOCOL_VERSION,
    AudioFormat,
    ControlMessage,
    MediaKind,
    MediaPacket,
    ProtocolError,
)

from .auth import AuthenticatedPrincipal, AuthenticationError

AccessTokenVerifier = Callable[[str, str | None], AuthenticatedPrincipal]


@dataclass(frozen=True, slots=True)
class UtteranceReceipt:
    connection_id: str
    session_id: str
    audio_bytes: int
    audio_chunks: int
    duration_ms: int


@dataclass(frozen=True, slots=True)
class CompletedUtterance:
    session_id: str
    audio: bytes
    input_format: AudioFormat
    output_format: AudioFormat
    correlation_id: str


@dataclass(frozen=True, slots=True)
class SessionResult:
    responses: tuple[ControlMessage, ...] = ()
    receipt: UtteranceReceipt | None = None
    utterance: CompletedUtterance | None = None
    lifecycle: SessionLifecycle | None = None
    close_code: int | None = None


@dataclass(frozen=True, slots=True)
class SessionLifecycle:
    action: str
    session_id: str


@dataclass(slots=True)
class RealtimeSession:
    verify_access_token: AccessTokenVerifier
    max_utterance_seconds: float = 60.0
    connection_id: str = field(default_factory=lambda: str(uuid4()))
    authenticated: bool = False
    user_id: str | None = None
    device_id: str | None = None
    session_id: str | None = None
    input_audio_format: AudioFormat | None = None
    output_audio_format: AudioFormat | None = None
    ptt_active: bool = False
    audio_bytes: int = 0
    audio_chunks: int = 0
    audio_buffer: bytearray = field(default_factory=bytearray)
    utterance_overflowed: bool = False

    def hello(self) -> ControlMessage:
        return ControlMessage(
            "hello",
            {
                "connection_id": self.connection_id,
                "supported_protocol_versions": [PROTOCOL_VERSION],
                "ai_pipeline": "pipecat",
                "output_audio": AudioFormat(sample_rate=24_000).to_dict(),
            },
        )

    def handle_control(self, message: ControlMessage) -> SessionResult:
        if message.type == "authenticate":
            return self._authenticate(message)
        if not self.authenticated:
            return SessionResult((self._error(message, "authentication_required"),))
        if message.type == "session.start":
            return self._start_session(message)
        if message.type == "session.end":
            return self._end_session(message)
        if message.type == "assistant.interrupt":
            return SessionResult()
        if message.type == "ptt.start":
            return self._start_ptt(message)
        if message.type == "ptt.end":
            return self._end_ptt(message)
        return SessionResult((self._error(message, "unsupported_message"),))

    def handle_media(self, packet: MediaPacket) -> SessionResult:
        if not self.authenticated:
            return SessionResult((self._error(None, "authentication_required"),))
        if self.session_id is None or not self.ptt_active:
            return SessionResult((self._error(None, "ptt_not_active"),))
        if packet.kind is not MediaKind.AUDIO_INPUT:
            return SessionResult((self._error(None, "unexpected_media_kind"),))
        if self.input_audio_format is None:
            return SessionResult((self._error(None, "session_not_active"),))
        max_bytes = round(
            self.input_audio_format.sample_rate
            * self.input_audio_format.channels
            * 2
            * self.max_utterance_seconds
        )
        if len(self.audio_buffer) + len(packet.payload) > max_bytes:
            if self.utterance_overflowed:
                return SessionResult()
            self.utterance_overflowed = True
            return SessionResult((self._error(None, "utterance_too_large"),))
        self.audio_buffer.extend(packet.payload)
        self.audio_bytes += len(packet.payload)
        self.audio_chunks += 1
        return SessionResult()

    def _authenticate(self, message: ControlMessage) -> SessionResult:
        if self.authenticated:
            return SessionResult((self._error(message, "already_authenticated"),))
        token = message.payload.get("access_token")
        device_id = message.payload.get("device_id")
        if not isinstance(token, str) or not isinstance(device_id, str):
            return SessionResult(
                (self._error(message, "authentication_failed"),),
                close_code=4401,
            )
        try:
            principal = self.verify_access_token(token, device_id)
        except AuthenticationError:
            return SessionResult(
                (self._error(message, "authentication_failed"),),
                close_code=4401,
            )
        self.authenticated = True
        self.user_id = principal.user_id
        self.device_id = principal.device_id
        return SessionResult((self._status(message),))

    def _start_session(self, message: ControlMessage) -> SessionResult:
        if self.session_id is not None:
            return SessionResult((self._error(message, "session_already_active"),))
        if set(message.payload) != {
            "session_id",
            "input_audio",
            "output_audio",
        }:
            return SessionResult((self._error(message, "invalid_session_start"),))
        session_id = message.payload.get("session_id")
        if not isinstance(session_id, str) or not session_id or len(session_id) > 128:
            return SessionResult((self._error(message, "invalid_session_id"),))
        try:
            input_audio_format = AudioFormat.from_dict(
                message.payload.get("input_audio")
            )
            output_audio_format = AudioFormat.from_dict(
                message.payload.get("output_audio")
            )
        except ProtocolError as exc:
            return SessionResult(
                (self._error(message, "invalid_audio_format", str(exc)),)
            )
        self.session_id = session_id
        self.input_audio_format = input_audio_format
        self.output_audio_format = output_audio_format
        self.ptt_active = False
        self._reset_utterance()
        return SessionResult(
            (self._status(message),),
            lifecycle=SessionLifecycle("started", session_id),
        )

    def _end_session(self, message: ControlMessage) -> SessionResult:
        requested_session_id = message.payload.get("session_id")
        if (
            self.session_id is None
            or requested_session_id != self.session_id
            or set(message.payload) != {"session_id"}
        ):
            return SessionResult((self._error(message, "invalid_session_id"),))
        session_id = self.session_id
        self.session_id = None
        self.input_audio_format = None
        self.output_audio_format = None
        self.ptt_active = False
        self._reset_utterance()
        return SessionResult(
            (self._status(message),),
            lifecycle=SessionLifecycle("ended", session_id)
            if session_id is not None
            else None,
        )

    def _start_ptt(self, message: ControlMessage) -> SessionResult:
        if self.session_id is None:
            return SessionResult((self._error(message, "session_not_active"),))
        if self.ptt_active:
            return SessionResult((self._error(message, "ptt_already_active"),))
        self.ptt_active = True
        self._reset_utterance()
        return SessionResult()

    def _end_ptt(self, message: ControlMessage) -> SessionResult:
        if (
            self.session_id is None
            or self.input_audio_format is None
            or self.output_audio_format is None
        ):
            return SessionResult((self._error(message, "session_not_active"),))
        if not self.ptt_active:
            return SessionResult((self._error(message, "ptt_not_active"),))
        self.ptt_active = False
        bytes_per_second = (
            self.input_audio_format.sample_rate * self.input_audio_format.channels * 2
        )
        duration_ms = round(self.audio_bytes / bytes_per_second * 1000)
        receipt = UtteranceReceipt(
            self.connection_id,
            self.session_id,
            self.audio_bytes,
            self.audio_chunks,
            duration_ms,
        )
        event = ControlMessage(
            "event",
            {
                "event_type": "utterance.received",
                "session_id": self.session_id,
                "audio_bytes": self.audio_bytes,
                "audio_chunks": self.audio_chunks,
                "duration_ms": duration_ms,
            },
            correlation_id=message.message_id,
        )
        utterance = None
        if not self.utterance_overflowed:
            utterance = CompletedUtterance(
                self.session_id,
                bytes(self.audio_buffer),
                self.input_audio_format,
                self.output_audio_format,
                message.message_id,
            )
        self._reset_utterance()
        return SessionResult((event,), receipt=receipt, utterance=utterance)

    def _status(self, request: ControlMessage) -> ControlMessage:
        return ControlMessage(
            "connection.status",
            {
                "connected": True,
                "authenticated": self.authenticated,
                "session_active": self.session_id is not None,
                "connection_id": self.connection_id,
            },
            correlation_id=request.message_id,
        )

    @staticmethod
    def _error(
        request: ControlMessage | None,
        code: str,
        detail: str | None = None,
    ) -> ControlMessage:
        payload: dict[str, Any] = {"code": code, "fatal": False}
        if detail:
            payload["detail"] = detail
        return ControlMessage(
            "error",
            payload,
            correlation_id=request.message_id if request is not None else None,
        )

    def _reset_utterance(self) -> None:
        self.audio_bytes = 0
        self.audio_chunks = 0
        self.audio_buffer.clear()
        self.utterance_overflowed = False
