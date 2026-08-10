from __future__ import annotations

from dcs_copilot.events import EventManager, SpeechMode, SpeechPolicy
from dcs_copilot.rules.base import (
    ActiveIssue,
    RuleTransition,
    RuleTransitionType,
    Severity,
)
from dcs_copilot.rules.engine import RuleEngine
from dcs_copilot.rules.fa18c import MasterCautionRule
from dcs_copilot.state.history import StateHistory
from dcs_copilot.state.models import AircraftState, FlightPhase, TelemetryValue


def _transition(
    severity: Severity,
    *,
    rule_id: str = "TEST_RULE",
    eligible: bool = True,
) -> RuleTransition:
    issue = ActiveIssue(
        rule_id=rule_id,
        severity=severity,
        aircraft="FA-18C_hornet",
        flight_phase=FlightPhase.CRUISE,
        activated_at=1.0,
        observed_at=1.0,
        message="Check configuration.",
        explanation="Test issue.",
        data={},
    )
    return RuleTransition(
        RuleTransitionType.ACTIVATED,
        issue,
        timestamp=1.0,
        notification_eligible=eligible,
    )


def test_speech_policy_modes_are_local_deterministic_and_cooldown_aware() -> None:
    minimal = SpeechPolicy(SpeechMode.MINIMAL)
    normal = SpeechPolicy(SpeechMode.NORMAL)
    coach = SpeechPolicy(SpeechMode.COACH)

    assert minimal.allows(_transition(Severity.CRITICAL))
    assert not minimal.allows(_transition(Severity.WARNING))
    assert normal.allows(_transition(Severity.WARNING))
    assert normal.allows(
        _transition(
            Severity.ADVISORY,
            rule_id="FA18_REFUELING_PROBE_LEFT_OUT",
        )
    )
    assert not normal.allows(_transition(Severity.ADVISORY))
    assert coach.allows(_transition(Severity.INFO))
    assert not coach.allows(_transition(Severity.CRITICAL, eligible=False))


def test_event_manager_correlates_raised_and_resolved_rule_events() -> None:
    engine = RuleEngine([MasterCautionRule()])
    manager = EventManager(engine, speech_policy=SpeechPolicy(SpeechMode.NORMAL))
    delivered = []
    manager.add_callback(delivered.append)
    history = StateHistory()
    caution = AircraftState(
        aircraft="FA-18C_hornet",
        connected=True,
        flight_phase=FlightPhase.CRUISE,
        master_caution=TelemetryValue(True, available=True, updated_at=0),
    )

    engine.evaluate(caution, history, now=0)
    engine.evaluate(caution, history, now=0.25)
    clear = AircraftState(
        aircraft="FA-18C_hornet",
        connected=True,
        flight_phase=FlightPhase.CRUISE,
        master_caution=TelemetryValue(False, available=True, updated_at=1),
    )
    engine.evaluate(clear, history, now=1)
    engine.evaluate(clear, history, now=1.5)

    raised, resolved = delivered
    assert raised.event.status == "RAISED"
    assert raised.event.control_type == "event.raised"
    assert raised.event.flight_phase == "CRUISE"
    assert raised.observed_at == 0.25
    assert raised.publish and raised.speak
    assert resolved.event.status == "RESOLVED"
    assert resolved.event.control_type == "event.resolved"
    assert resolved.event.event_id == raised.event.event_id
    assert resolved.publish and not resolved.speak
    assert manager.history == tuple(delivered)


def test_unpublished_advisory_is_retained_locally_without_cloud_resolution() -> None:
    engine = RuleEngine([])
    manager = EventManager(engine, speech_policy=SpeechPolicy(SpeechMode.MINIMAL))
    transition = _transition(Severity.ADVISORY)

    manager.handle_transition(transition)
    resolved = RuleTransition(
        RuleTransitionType.RESOLVED,
        transition.issue,
        timestamp=2.0,
        notification_eligible=False,
    )
    manager.handle_transition(resolved)

    assert [item.publish for item in manager.history] == [False, False]
    assert [item.speak for item in manager.history] == [False, False]
