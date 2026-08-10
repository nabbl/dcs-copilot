"""Pipecat-backed, PTT-driven cloud voice orchestration."""

from __future__ import annotations

import asyncio
import io
import wave
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from dcs_copilot_protocol import ALLOWED_AIRCRAFT_STATE_FIELDS, AudioFormat
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.frames.frames import (
    ErrorFrame,
    Frame,
    InputAudioRawFrame,
    InterruptionFrame,
    LLMFullResponseEndFrame,
    LLMTextFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.llm_service import FunctionCallParams
from pipecat.turns.user_start import ExternalUserTurnStartStrategy
from pipecat.turns.user_stop import ExternalUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.workers.runner import WorkerRunner

from .providers import ProviderBundle

AudioCallback = Callable[[bytes], Awaitable[None]]
ToolCallback = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


class VoicePipelineError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class VoiceTurn:
    audio: bytes
    input_format: AudioFormat
    output_format: AudioFormat


@dataclass(frozen=True, slots=True)
class VoiceTurnResult:
    transcript: str
    response_text: str


class VoicePipeline(Protocol):
    async def respond(
        self,
        turn: VoiceTurn,
        on_audio: AudioCallback,
        request_tool: ToolCallback | None = None,
    ) -> VoiceTurnResult: ...

    async def interrupt(self) -> None: ...

    async def close(self) -> None: ...


class _TranscriptObserver(FrameProcessor):
    def __init__(self, owner: PipecatVoicePipeline) -> None:
        super().__init__(name="dcs-transcript-observer")
        self._owner = owner

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, TranscriptionFrame):
            self._owner._transcript_parts.append(frame.text)
        await self.push_frame(frame, direction)


class _ResponseTextObserver(FrameProcessor):
    def __init__(self, owner: PipecatVoicePipeline) -> None:
        super().__init__(name="dcs-response-text-observer")
        self._owner = owner

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMTextFrame):
            self._owner._response_parts.append(frame.text)
        await self.push_frame(frame, direction)


class _OutputObserver(FrameProcessor):
    def __init__(self, owner: PipecatVoicePipeline) -> None:
        super().__init__(name="dcs-output-observer")
        self._owner = owner

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, TTSAudioRawFrame):
            callback = self._owner._audio_callback
            if callback is not None and self._owner._turn_active:
                await callback(frame.audio)
        elif isinstance(frame, ErrorFrame):
            self._owner._turn_error = frame.error
        await self.push_frame(frame, direction)
        if isinstance(frame, (LLMFullResponseEndFrame, ErrorFrame)):
            # Pipecat schedules function handlers immediately before ending the
            # first LLM pass. Give that task a chance to start; the tool result
            # will then trigger the final LLM pass.
            await asyncio.sleep(0)
            if not self._owner._tool_requests_in_flight:
                self._owner._turn_done.set()


class PipecatVoicePipeline:
    """One persistent Pipecat conversation pipeline per authenticated session."""

    def __init__(self, providers: ProviderBundle) -> None:
        self._providers = providers
        self._worker: PipelineWorker | None = None
        self._runner: WorkerRunner | None = None
        self._runner_task: asyncio.Task[None] | None = None
        self._started = asyncio.Event()
        self._turn_done = asyncio.Event()
        self._turn_lock = asyncio.Lock()
        self._turn_active = False
        self._turn_error: str | None = None
        self._transcript_parts: list[str] = []
        self._response_parts: list[str] = []
        self._audio_callback: AudioCallback | None = None
        self._tool_callback: ToolCallback | None = None
        self._tool_requests_in_flight = 0

    async def respond(
        self,
        turn: VoiceTurn,
        on_audio: AudioCallback,
        request_tool: ToolCallback | None = None,
    ) -> VoiceTurnResult:
        if not turn.audio:
            raise VoicePipelineError("utterance contained no audio")
        if turn.output_format.sample_rate != 24_000:
            raise VoicePipelineError("cloud TTS output requires 24000 Hz PCM")
        async with self._turn_lock:
            await self._ensure_started(turn)
            worker = self._worker
            if worker is None:
                raise VoicePipelineError("Pipecat worker did not start")
            self._turn_done.clear()
            self._turn_error = None
            self._transcript_parts.clear()
            self._response_parts.clear()
            self._audio_callback = on_audio
            self._tool_callback = request_tool
            self._turn_active = True
            wav_audio = pcm_to_wav(turn.audio, turn.input_format)
            try:
                await worker.queue_frames(
                    (
                        UserStartedSpeakingFrame(),
                        InputAudioRawFrame(
                            audio=wav_audio,
                            sample_rate=turn.input_format.sample_rate,
                            num_channels=turn.input_format.channels,
                        ),
                        UserStoppedSpeakingFrame(),
                    )
                )
                await self._turn_done.wait()
            finally:
                self._turn_active = False
                self._audio_callback = None
                self._tool_callback = None
            if self._turn_error:
                raise VoicePipelineError(self._turn_error)
            transcript = " ".join(self._transcript_parts).strip()
            response = "".join(self._response_parts).strip()
            if not transcript:
                raise VoicePipelineError("speech was not recognized")
            if not response:
                raise VoicePipelineError("language model returned no spoken response")
            return VoiceTurnResult(transcript, response)

    async def interrupt(self) -> None:
        self._turn_active = False
        self._audio_callback = None
        self._turn_done.set()
        if self._worker is not None and not self._worker.has_finished():
            await self._worker.queue_frame(InterruptionFrame())

    async def close(self) -> None:
        await self.interrupt()
        worker = self._worker
        task = self._runner_task
        if worker is not None and not worker.has_finished():
            await worker.cancel(reason="client disconnected")
        if task is not None:
            try:
                await asyncio.wait_for(task, timeout=5)
            except TimeoutError:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        self._worker = None
        self._runner = None
        self._runner_task = None

    async def _ensure_started(self, turn: VoiceTurn) -> None:
        if self._worker is not None:
            return
        context = LLMContext(
            tools=ToolsSchema(aircraft_tool_schemas(self._handle_tool_call))
        )
        strategies = UserTurnStrategies(
            start=[ExternalUserTurnStartStrategy()],
            stop=[ExternalUserTurnStopStrategy(timeout=0.01)],
        )
        aggregators = LLMContextAggregatorPair(
            context,
            user_params=LLMUserAggregatorParams(user_turn_strategies=strategies),
            realtime_service_mode=False,
        )
        pipeline = Pipeline(
            (
                self._providers.stt.create_processor(),
                _TranscriptObserver(self),
                aggregators.user(),
                self._providers.llm.create_processor(),
                _ResponseTextObserver(self),
                self._providers.tts.create_processor(),
                _OutputObserver(self),
                aggregators.assistant(),
            )
        )
        worker = PipelineWorker(
            pipeline,
            enable_rtvi=False,
            enable_turn_tracking=False,
            idle_timeout_secs=None,
            params=PipelineParams(
                audio_in_sample_rate=turn.input_format.sample_rate,
                audio_out_sample_rate=turn.output_format.sample_rate,
                enable_metrics=True,
                enable_usage_metrics=True,
            ),
        )

        @worker.event_handler("on_pipeline_started")
        async def pipeline_started(_worker: PipelineWorker, _frame: Frame) -> None:
            self._started.set()

        self._worker = worker
        self._runner = WorkerRunner(handle_sigint=False, handle_sigterm=False)
        await self._runner.add_workers(worker)
        self._runner_task = asyncio.create_task(
            self._runner.run(), name="pipecat-session-runner"
        )
        try:
            await asyncio.wait_for(self._started.wait(), timeout=10)
        except TimeoutError as exc:
            await self.close()
            raise VoicePipelineError("Pipecat pipeline startup timed out") from exc

    async def _handle_tool_call(self, params: FunctionCallParams) -> None:
        callback = self._tool_callback
        self._tool_requests_in_flight += 1
        try:
            if callback is None:
                result: dict[str, Any] = {
                    "available": False,
                    "error": {
                        "code": "aircraft_client_unavailable",
                        "detail": "aircraft tools are unavailable for this turn",
                    },
                }
            else:
                try:
                    result = await callback(
                        params.function_name,
                        dict(params.arguments),
                    )
                except Exception as exc:  # noqa: BLE001 - errors become tool data
                    from .tools import aircraft_tool_error_result

                    result = aircraft_tool_error_result(exc)
        finally:
            self._tool_requests_in_flight -= 1
        await params.result_callback(result)


def aircraft_tool_schemas(handler: Any) -> list[FunctionSchema]:
    """Provider-neutral Pipecat schemas for the four local read-only tools."""

    no_arguments: dict[str, Any] = {}
    state_fields = sorted(ALLOWED_AIRCRAFT_STATE_FIELDS)
    return [
        FunctionSchema(
            name="get_aircraft_state",
            description=(
                "Read only explicitly requested normalized own-aircraft fields. "
                "Unavailable telemetry is returned as unavailable."
            ),
            properties={
                "fields": {
                    "type": "array",
                    "items": {"type": "string", "enum": state_fields},
                    "minItems": 1,
                    "maxItems": 16,
                    "uniqueItems": True,
                }
            },
            required=["fields"],
            handler=handler,
        ),
        FunctionSchema(
            name="get_active_issues",
            description=(
                "Read current issues produced by deterministic local rules. Use "
                "this for questions like what did I forget or anything wrong."
            ),
            properties=no_arguments,
            required=[],
            handler=handler,
        ),
        FunctionSchema(
            name="get_recent_events",
            description=(
                "Read a bounded recent history of safe normalized own-aircraft "
                "state transitions."
            ),
            properties={
                "seconds": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                    "maximum": 300,
                    "default": 30,
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "default": 10,
                },
            },
            required=[],
            handler=handler,
        ),
        FunctionSchema(
            name="get_flight_phase",
            description="Read the deterministic local flight phase, if available.",
            properties=no_arguments,
            required=[],
            handler=handler,
        ),
    ]


def pcm_to_wav(audio: bytes, audio_format: AudioFormat) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(audio_format.channels)
        wav.setsampwidth(2)
        wav.setframerate(audio_format.sample_rate)
        wav.writeframes(audio)
    return output.getvalue()
