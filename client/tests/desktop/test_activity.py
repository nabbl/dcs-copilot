from dcs_copilot.desktop.activity import ActivityOutputFilter, ConversationActivity
from dcs_copilot_protocol import ControlMessage


def test_conversation_activity_requires_a_correlated_pilot_turn() -> None:
    activity = ConversationActivity()

    proactive = ControlMessage(
        "assistant.text",
        {"text": "Master caution."},
        correlation_id="event-1",
    )
    pilot = ControlMessage(
        "pilot.text",
        {"text": "What did I forget?"},
        correlation_id="turn-1",
    )
    response = ControlMessage(
        "assistant.text",
        {"text": "Your probe is still out."},
        correlation_id="turn-1",
    )

    assert activity.accept(proactive) == ()
    assert activity.accept(pilot) == ("Pilot: What did I forget?",)
    assert activity.accept(response) == ("MARA: Your probe is still out.",)
    assert activity.accept(response) == ()


def test_activity_filter_keeps_conversation_and_diagnostic_lines() -> None:
    output = ActivityOutputFilter()

    first = output.feed(
        "Cloud: connecting\nPTT: active\nPilot: What did I "
    )
    second = output.feed(
        "forget?\n{\"level\":\"INFO\",\"message\":\"telemetry\"}\nMARA: "
    )
    third = output.feed("Your probe is still out.\n")

    assert first == ("Cloud: connecting", "PTT: active")
    assert second == ("Pilot: What did I forget?",)
    assert third == ("MARA: Your probe is still out.",)


def test_activity_filter_flushes_final_activity_line_only() -> None:
    output = ActivityOutputFilter()
    output.feed("DCS Copilot running\nMARA: Muted response")

    assert output.flush() == ("MARA: Muted response",)
    assert output.flush() == ()


def test_activity_filter_keeps_message_diagnostics_and_errors() -> None:
    output = ActivityOutputFilter()

    lines = output.feed(
        "Send: ptt.start id=12345678\n"
        "Receive: event event=utterance.received audio_bytes=640\n"
        "Error: voice_pipeline_failed detail=speech was not recognized\n"
        '{"level":"INFO","message":"telemetry"}\n'
    )

    assert lines == (
        "Send: ptt.start id=12345678",
        "Receive: event event=utterance.received audio_bytes=640",
        "Error: voice_pipeline_failed detail=speech was not recognized",
    )
