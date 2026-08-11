"""Filter runtime output into user-visible conversation activity."""

from __future__ import annotations

from dcs_copilot_protocol import ControlMessage


class ConversationActivity:
    def __init__(self) -> None:
        self._pilot_turns: set[str] = set()

    def reset(self) -> None:
        self._pilot_turns.clear()

    def accept(self, message: ControlMessage) -> tuple[str, ...]:
        text = message.payload.get("text")
        correlation_id = message.correlation_id
        if not isinstance(text, str) or correlation_id is None:
            return ()
        if message.type == "pilot.text":
            self._pilot_turns.add(correlation_id)
            return (f"Pilot: {text}",)
        if message.type == "assistant.text" and correlation_id in self._pilot_turns:
            self._pilot_turns.discard(correlation_id)
            return (f"MARA: {text}",)
        return ()


class ActivityOutputFilter:
    def __init__(self) -> None:
        self._buffer = ""

    def reset(self) -> None:
        self._buffer = ""

    def feed(self, output: str) -> tuple[str, ...]:
        self._buffer += output
        lines: list[str] = []
        while "\n" in self._buffer:
            raw_line, self._buffer = self._buffer.split("\n", 1)
            line = raw_line.rstrip("\r").strip()
            if _is_activity_line(line):
                lines.append(line)
        return tuple(lines)

    def flush(self) -> tuple[str, ...]:
        line = self._buffer.rstrip("\r").strip()
        self._buffer = ""
        return (line,) if _is_activity_line(line) else ()


def _is_activity_line(line: str) -> bool:
    return line.startswith(("Pilot: ", "MARA: "))
