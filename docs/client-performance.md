# Thin-client performance methodology

Client resource consumption is a product requirement. The client must not load
AI models or contend with DCS for GPU time. Performance claims require automated
queue/parser tests and an in-game Windows measurement.

## Dependency and model audit

The client includes standard-library DCS-BIOS decoding and telemetry batching
plus the WebSocket transport, PyAudio, desktop UI, and Windows hotkey listener. Database,
authentication, cloud Pipecat, and AI providers remain excluded from the
client. Before a release, inspect the client-only resolved
environment and packaged artifact and verify that it contains no FastAPI cloud
stack, Pipecat, OpenAI, Torch, CUDA, ONNX, Whisper, Kokoro, Piper, Smart Turn,
embedding, or vector-database package or model file.

The `status` command explicitly reports:

```text
AI inference running locally: NO
```

## Repeatable tests

Run the client suite from the repository root:

```bash
uv run --package dcs-copilot-client pytest -q client/tests
```

The suite covers parser behavior, dirty-output decoding, bounded telemetry
queues, rapid-change coalescing, reconnect epochs, audio, PTT, authentication,
and the architectural ban on client product-logic packages. CI deliberately
does not impose timing thresholds on shared runners.

## Windows DCS acceptance measurement

Automated tests cannot establish the product requirement. Before claiming
Milestone 1 performance acceptance:

1. Select a repeatable demanding F/A-18C mission, graphics preset, resolution,
   and camera view.
2. Warm DCS for five minutes and record a ten-minute baseline using the same
   frametime tool and sampling interval.
3. Start the packaged thin client with telemetry streaming and record another
   ten-minute run without changing the mission or view.
4. Repeat both runs at least three times in alternating order.
5. Compare median FPS plus median, 95th, and 99th percentile CPU/GPU frametime;
   also record client CPU, working set, parser errors, and received frame rate.
6. Repeat separate connected-idle, PTT-capture and response-playback runs and
   record uplink/downlink bandwidth. Verify at the OS device level that the
   microphone stream does not exist while PTT is released.

Record hardware, Windows and DCS versions, mission, server/export restrictions,
background applications, and raw measurements. The acceptance criterion is no
meaningful repeatable DCS frametime regression; the numeric release threshold
must be set after the first controlled hardware baseline rather than invented
from a development laptop.
