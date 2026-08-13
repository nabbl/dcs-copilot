"""Versioned, curated F/A-18C procedural knowledge.

Cards are original MARA summaries, not embedded excerpts or a vector dump of the
source manual. Every shipped card is deliberately small and traceable to a
specific revision of Eagle Dynamics' official guide.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

HORNET_KNOWLEDGE_VERSION = "fa18c-ed-2026.08.1"


class HornetKnowledgeTopic(StrEnum):
    DEPARTURE_CLEANUP = "departure_cleanup"
    TACAN_NAVIGATION = "tacan_navigation"
    COUPLED_AUTOPILOT = "coupled_autopilot"


@dataclass(frozen=True, slots=True)
class KnowledgeSource:
    publisher: str
    title: str
    section: str
    pages: str
    url: str
    document_sha256: str
    document_created_at: str
    reviewed_on: str


@dataclass(frozen=True, slots=True)
class HornetKnowledgeCard:
    id: str
    topic: HornetKnowledgeTopic
    title: str
    aircraft: str
    applicability: str
    summary: str
    steps: tuple[str, ...]
    cautions: tuple[str, ...]
    source: KnowledgeSource


_MANUAL_URL = (
    "https://www.digitalcombatsimulator.com/upload/iblock/ea9/"
    "lxf69u2uk1fhqq7ndb55z9egzabe8hdg/"
    "DCS%20FA-18C%20Early%20Access%20Guide%20EN.pdf"
)
_MANUAL_SHA256 = "063873fac43245154bd772241fce89fe4985128cd962cb3e43fc9cefbc35d74c"


def _source(section: str, pages: str) -> KnowledgeSource:
    return KnowledgeSource(
        publisher="Eagle Dynamics",
        title="DCS: F/A-18C Early Access Guide",
        section=section,
        pages=pages,
        url=_MANUAL_URL,
        document_sha256=_MANUAL_SHA256,
        document_created_at="2024-03-24",
        reviewed_on="2026-08-13",
    )


_CARDS = {
    HornetKnowledgeTopic.DEPARTURE_CLEANUP: HornetKnowledgeCard(
        id="fa18c.departure_cleanup.v1",
        topic=HornetKnowledgeTopic.DEPARTURE_CLEANUP,
        title="Departure cleanup",
        aircraft="FA-18C_hornet",
        applicability="Airfield or carrier departure after a positive climb",
        summary=(
            "Retract the landing gear and select flaps AUTO after a positive climb; "
            "then verify the indications and address any remaining configuration warning."
        ),
        steps=(
            "Establish a positive climb before changing the takeoff configuration.",
            "Command landing gear UP and verify that the gear retracts.",
            "Set the flap switch to AUTO and verify the selected position.",
            "After a carrier launch, verify the launch bar is no longer commanded down.",
        ),
        cautions=(
            "MARA can verify exported cockpit state, not terrain, traffic, or obstacle clearance.",
        ),
        source=_source(
            "Airfield Takeoff; Aircraft Carrier Launch",
            "100, 107",
        ),
    ),
    HornetKnowledgeTopic.TACAN_NAVIGATION: HornetKnowledgeCard(
        id="fa18c.tacan_navigation.v1",
        topic=HornetKnowledgeTopic.TACAN_NAVIGATION,
        title="TACAN navigation",
        aircraft="FA-18C_hornet",
        applicability="Navigation to a known land, ship, or airborne TACAN station",
        summary=(
            "Tune the briefed channel and band on the UFC, switch TACAN on, then box "
            "TCN on the HSI to display steering to a valid station."
        ),
        steps=(
            "Select TCN on the UFC and choose the briefed X or Y band.",
            "Switch TACAN on, clear the scratchpad, enter the channel, and press ENT.",
            "Box TCN on the HSI and verify valid station identity and steering before use.",
        ),
        cautions=(
            "TACAN distance is slant range and reception depends on line of sight.",
            "T/R supplies bearing and range; receive-only mode supplies bearing only.",
        ),
        source=_source("TACAN Navigation", "136-138"),
    ),
    HornetKnowledgeTopic.COUPLED_AUTOPILOT: HornetKnowledgeCard(
        id="fa18c.coupled_autopilot.v1",
        topic=HornetKnowledgeTopic.COUPLED_AUTOPILOT,
        title="Coupled autopilot navigation",
        aircraft="FA-18C_hornet",
        applicability="Coupled steering to a selected waypoint or TACAN station",
        summary=(
            "CPL controls roll toward the active waypoint or TACAN source; pitch remains "
            "manual unless a compatible altitude-hold mode is also engaged."
        ),
        steps=(
            "Select a waypoint or tune and verify the TACAN station.",
            "Box WYPT or TCN on the HSI for the intended navigation source.",
            "Open the UFC A/P options and select CPL; verify the coupled indication.",
        ),
        cautions=(
            "Monitor pitch and flight path; coupled mode by itself commands roll only.",
            "A flashing coupled indication can mean an uncommanded disconnect such as lost TACAN signal.",
        ),
        source=_source(
            "Autopilot Relief Modes; Using Coupled Autopilot Mode",
            "146-148",
        ),
    ),
}


def get_hornet_knowledge_card(topic: HornetKnowledgeTopic) -> HornetKnowledgeCard:
    return _CARDS[topic]


__all__ = [
    "HORNET_KNOWLEDGE_VERSION",
    "HornetKnowledgeCard",
    "HornetKnowledgeTopic",
    "KnowledgeSource",
    "get_hornet_knowledge_card",
]
