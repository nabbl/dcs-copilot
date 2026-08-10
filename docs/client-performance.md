# Thin-client performance methodology

Client resource consumption is a product requirement. The client must not load
AI models or contend with DCS for GPU time. Performance claims require both the
repeatable microbenchmark below and an in-game Windows measurement.

## Dependency and model audit

Milestones 2 through 4 add only standard-library tool schemas/execution plus the
WebSocket transport, PyAudio and Windows hotkey listener. Cloud Pipecat and AI
providers remain excluded. Before a release, inspect the client-only resolved
environment and packaged artifact and verify that it contains no FastAPI cloud
stack, Pipecat, OpenAI, Torch, CUDA, ONNX, Whisper, Kokoro, Piper, Smart Turn,
embedding, or vector-database package or model file.

The `status` and `benchmark` commands explicitly report:

```text
AI inference running locally: NO
```

## Repeatable microbenchmark

Run from the repository root on an otherwise idle machine:

```bash
uv run dcs-copilot benchmark --updates 30000 --idle-seconds 5
```

The command measures:

- process CPU used during a blocking idle sample;
- resident/high-water memory before and after the workload;
- DCS-BIOS binary parser throughput and bytes processed;
- normalized history, phase-detector, six-rule evaluation, and bounded semantic
  event-management cost;
- the workload CPU time projected to 30 updates per second.

It does not open a microphone, initialize audio, contact a server, or load a
model. Results should be retained with the OS, CPU, Python version, client
revision, and command arguments. CI verifies that the benchmark workload is
correct but deliberately does not impose timing thresholds on shared runners.

## Windows DCS acceptance measurement

Microbenchmarks cannot establish the product requirement. Before claiming
Milestone 1 performance acceptance:

1. Select a repeatable demanding F/A-18C mission, graphics preset, resolution,
   and camera view.
2. Warm DCS for five minutes and record a ten-minute baseline using the same
   frametime tool and sampling interval.
3. Start the packaged client with normalized monitoring and record another
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
