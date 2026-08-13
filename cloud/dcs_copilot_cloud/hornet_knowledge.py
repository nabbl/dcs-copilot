"""Versioned, curated F/A-18C procedural knowledge.

Cards are original MARA summaries, not embedded excerpts or a vector dump of the
source manual. Every shipped card is deliberately small and traceable to a
specific revision of Eagle Dynamics' official guide.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

HORNET_KNOWLEDGE_VERSION = "fa18c-ed-2026.08.2"


class HornetKnowledgeTopic(StrEnum):
    DEPARTURE_CLEANUP = "departure_cleanup"
    TACAN_NAVIGATION = "tacan_navigation"
    COUPLED_AUTOPILOT = "coupled_autopilot"
    CASE_I_RECOVERY = "case_i_recovery"
    AIRFIELD_VFR_LANDING = "airfield_vfr_landing"
    WAYPOINT_NAVIGATION = "waypoint_navigation"
    AUTOPILOT_RELIEF_MODES = "autopilot_relief_modes"
    CARRIER_LAUNCH = "carrier_launch"


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
    HornetKnowledgeTopic.CASE_I_RECOVERY: HornetKnowledgeCard(
        id="fa18c.case_i_recovery.v1",
        topic=HornetKnowledgeTopic.CASE_I_RECOVERY,
        title="CASE I carrier recovery overview",
        aircraft="FA-18C_hornet",
        applicability=(
            "Day visual carrier recovery in at least 5 miles visibility with a "
            "cloud base of at least 5,000 feet"
        ),
        summary=(
            "Make the visual initial, break into the 600-foot landing pattern, "
            "configure and trim on-speed on downwind, fly the descending approach "
            "turn, then use IFLOLS and LSO direction in the groove."
        ),
        steps=(
            "Before entry, select NAV, set Master Arm SAFE, lower the hook, and use radar altitude on the HUD.",
            "For the direct initial, pass starboard of the ship from astern at 800 feet and 350 KIAS while checking the deck.",
            "Break left no later than 1.5 nautical miles past the bow and roll out reciprocal at 600 feet.",
            "On downwind, establish about 1.3 to 1.4 nautical miles lateral spacing, configure gear down and flaps FULL, and trim on-speed AoA.",
            "Begin the approach turn at the round-down, holding on-speed with roughly 27 to 30 degrees of bank and controlling descent with power.",
            "Acquire the carrier and IFLOLS in the second half of the turn; in the groove, fly the ball and comply immediately with LSO or waveoff signals.",
            "At deck contact, select full power until a successful arrestment is assured; after the trap, idle, hook up, flaps AUTO, and clear the landing area.",
        ),
        cautions=(
            "This is a DCS pattern overview, not real-world flight instruction.",
            "MARA cannot verify ship position, deck status, lineup, glideslope, or LSO calls from current telemetry.",
            "Wave off immediately when directed or when a safe approach is not assured.",
        ),
        source=_source("Case 1 Carrier Recovery", "108-113"),
    ),
    HornetKnowledgeTopic.AIRFIELD_VFR_LANDING: HornetKnowledgeCard(
        id="fa18c.airfield_vfr_landing.v1",
        topic=HornetKnowledgeTopic.AIRFIELD_VFR_LANDING,
        title="Airfield VFR landing pattern",
        aircraft="FA-18C_hornet",
        applicability="Visual overhead landing pattern at a DCS airfield",
        summary=(
            "Enter the overhead, break to a 600-foot reciprocal downwind, configure "
            "below 250 KIAS, trim on-speed, and fly the base-to-final turn with power."
        ),
        steps=(
            "Select NAV, set Master Arm SAFE, and enter at 800 feet AGL and 350 KIAS along the runway heading.",
            "Break to downwind after passing the runway, rolling out reciprocal at 600 feet AGL with about 1.2 miles lateral spacing.",
            "Below 250 KIAS, lower the gear and select flaps FULL; decelerate and trim to on-speed AoA.",
            "Turn base when abeam the threshold, maintain on-speed with about 30 degrees of bank, and continue the descending turn to final.",
            "On final, maintain on-speed and use power for the flight path; after touchdown, idle and track the runway with small corrections.",
        ),
        cautions=(
            "Runway geometry, traffic, winds, and clearance are not available from cockpit telemetry alone.",
            "Use the mission briefing and ATC instructions when they differ from this training pattern.",
        ),
        source=_source("Airfield VFR Landing", "101-103"),
    ),
    HornetKnowledgeTopic.WAYPOINT_NAVIGATION: HornetKnowledgeCard(
        id="fa18c.waypoint_navigation.v1",
        topic=HornetKnowledgeTopic.WAYPOINT_NAVIGATION,
        title="Waypoint navigation",
        aircraft="FA-18C_hornet",
        applicability="Point-to-point navigation using mission waypoints",
        summary=(
            "Box WYPT on the HSI, select the desired steer-to waypoint, and use the "
            "HSI and HUD bearing, distance, time, and command-heading cues."
        ),
        steps=(
            "Open the HSI and box WYPT to select waypoint steering.",
            "Use the waypoint increment or decrement controls to select the intended steer-to point.",
            "Cross-check the selected waypoint and its bearing, distance, and time data before following the steering cues.",
            "Use AUTO sequencing only when the loaded sequence and mission plan have been verified.",
        ),
        cautions=(
            "WPDSG changes the selected waypoint into a target designation; do not select it merely to navigate.",
            "MARA does not currently read or verify the loaded waypoint coordinates or sequence.",
        ),
        source=_source("Waypoint Navigation", "121-122"),
    ),
    HornetKnowledgeTopic.AUTOPILOT_RELIEF_MODES: HornetKnowledgeCard(
        id="fa18c.autopilot_relief_modes.v1",
        topic=HornetKnowledgeTopic.AUTOPILOT_RELIEF_MODES,
        title="Autopilot relief modes",
        aircraft="FA-18C_hornet",
        applicability="Normal in-flight workload relief",
        summary=(
            "The UFC A/P menu provides attitude hold, heading select, barometric "
            "altitude hold, radar altitude hold, and coupled navigation modes."
        ),
        steps=(
            "Press A/P on the UFC and select the intended mode; a colon marks the selection.",
            "Use ATTH for current attitude, HSEL for the HSI-selected heading, BALT for barometric altitude, or RALT for radar altitude.",
            "Use CPL only with a verified active waypoint or TACAN navigation source.",
            "Confirm the A/P advisory and expected flight response after engagement; use the paddle switch to disengage.",
        ),
        cautions=(
            "Each mode has an engagement envelope; this card is a mode overview, not a substitute for checking the full limitations.",
            "MARA does not currently verify which autopilot mode is engaged.",
        ),
        source=_source("Autopilot Relief Modes", "146-147"),
    ),
    HornetKnowledgeTopic.CARRIER_LAUNCH: HornetKnowledgeCard(
        id="fa18c.carrier_launch.v1",
        topic=HornetKnowledgeTopic.CARRIER_LAUNCH,
        title="Carrier launch overview",
        aircraft="FA-18C_hornet",
        applicability="Catapult launch after taxi and aircraft hookup",
        summary=(
            "Complete the carrier takeoff checks, spread and lock the wings, hook up "
            "the launch bar, set weight-appropriate trim, wipe the controls, and launch."
        ),
        steps=(
            "Complete the carrier before-takeoff checks and use MARA's CARRIER takeoff-readiness gate for observable configuration.",
            "Taxi to the assigned catapult, spread and lock the wings, align with the shuttle, lower the launch bar, and hook up.",
            "Set takeoff stabilator trim for aircraft gross weight and verify the takeoff configuration.",
            "At the catapult, set power as required, perform the control wipe, verify indications, and follow launch direction.",
            "After launch and positive climb, raise the gear, select flaps AUTO, and fly the assigned departure.",
        ),
        cautions=(
            "Gross-weight trim and power requirements must come from the current aircraft and applicable launch procedure.",
            "MARA's knowledge card does not establish catapult assignment, deck clearance, or permission to launch.",
        ),
        source=_source(
            "Aircraft Carrier Taxi; Aircraft Carrier Launch",
            "104-107",
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
