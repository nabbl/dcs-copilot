"""Curated cockpit greetings for MARA's cloud TTS voice."""

from __future__ import annotations

import secrets
from collections.abc import Callable, Sequence

GENERIC_GREETINGS = (
    "Mara online. Ready when you are.",
    "Welcome aboard. Systems monitoring active.",
    "Good to see you, pilot. Let's get airborne.",
    "Cockpit link established. Mara is with you.",
)

HORNET_GREETINGS = (
    "Hornet detected. I'm online and watching the systems.",
)


class CockpitGreetingSelector:
    def __init__(
        self,
        chooser: Callable[[Sequence[str]], str] = secrets.choice,
    ) -> None:
        self._chooser = chooser
        self._previous: str | None = None

    def choose(self, aircraft: str) -> str:
        greetings = list(GENERIC_GREETINGS)
        normalized = aircraft.casefold().replace("/", "").replace("-", "")
        if "fa18" in normalized or "hornet" in normalized:
            greetings.extend(HORNET_GREETINGS)
        choices = [greeting for greeting in greetings if greeting != self._previous]
        selected = self._chooser(choices or greetings)
        self._previous = selected
        return selected
