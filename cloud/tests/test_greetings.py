from dcs_copilot_cloud.greetings import (
    GENERIC_GREETINGS,
    HORNET_GREETINGS,
    CockpitGreetingSelector,
)


def test_greetings_vary_without_immediate_repeats() -> None:
    selector = CockpitGreetingSelector()
    greetings = [selector.choose("F-16C_50") for _ in range(20)]
    assert set(greetings) <= set(GENERIC_GREETINGS)
    assert all(left != right for left, right in zip(greetings, greetings[1:]))


def test_hornet_can_receive_aircraft_specific_greeting() -> None:
    selector = CockpitGreetingSelector(lambda choices: choices[-1])
    assert selector.choose("FA-18C_hornet") in HORNET_GREETINGS
