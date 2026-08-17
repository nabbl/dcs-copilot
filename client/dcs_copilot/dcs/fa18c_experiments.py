"""Controlled F/A-18C indication experiments required before semantic parsing."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IndicationExperiment:
    scenario: str
    group: str
    action: str


EXPERIMENTS = tuple(
    IndicationExperiment(scenario, group, action)
    for group, rows in {
        "RADAR": (
            ("radar-off", "Set radar OFF and hold a stable display"),
            ("radar-stby", "Set radar STBY"),
            ("radar-opr", "Set radar OPR"),
            ("radar-aa-mode", "Select A/A master mode"),
            ("radar-rws", "Display RWS"),
            ("radar-tws", "Display TWS"),
            ("radar-one-contact", "Show exactly one radar contact"),
            ("radar-several-contacts", "Show several radar contacts"),
            ("radar-designated", "Designate one contact"),
            ("radar-stt", "Establish STT"),
            ("radar-lock-acquired", "Acquire a radar lock"),
            ("radar-lock-lost", "Lose an established radar lock"),
            ("radar-range-change", "Change radar range once"),
            ("radar-elevation-change", "Change radar elevation once"),
            ("radar-shoot-cue-on", "Make the shoot cue appear"),
            ("radar-shoot-cue-off", "Make the shoot cue disappear"),
        ),
        "SA": (
            ("sa-no-tracks", "Display SA with no tracks"),
            ("sa-friendly", "Add one known friendly track"),
            ("sa-hostile", "Add one known hostile track"),
            ("sa-unknown", "Add one unknown track"),
            ("sa-donor", "Add one donor track"),
            ("sa-several-tracks", "Display several tracks"),
            ("sa-selected-track-change", "Change the selected track once"),
            ("sa-range-scale-change", "Change SA range scale once"),
            ("sa-waypoint-change", "Change the selected waypoint once"),
            ("sa-contact-leaves-range", "Let one contact leave displayed range"),
            ("sa-contact-disappears", "Make one displayed contact disappear"),
        ),
        "RWR": (
            ("rwr-off", "Power the RWR off"),
            ("rwr-on", "Power the RWR on"),
            ("rwr-search-appears", "Introduce one search emitter"),
            ("rwr-emitter-disappears", "Remove one established emitter"),
            ("rwr-tracking", "Make one emitter begin tracking"),
            ("rwr-lock", "Create one unambiguous radar lock warning"),
            ("rwr-missile-launch", "Create one launch-specific warning"),
            ("rwr-multiple-emitters", "Display several emitters"),
            ("rwr-priority-change", "Change the priority threat once"),
        ),
    }.items()
    for scenario, action in rows
)

EXPERIMENT_BY_SCENARIO = {experiment.scenario: experiment for experiment in EXPERIMENTS}
