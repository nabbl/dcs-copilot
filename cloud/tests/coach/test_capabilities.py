from __future__ import annotations

from dcs_copilot_cloud.coach.capabilities import (
    CapabilityManager,
    DcsCapabilities,
)


def test_spatial_coaching_is_closed_until_dcs_capabilities_are_available() -> None:
    manager = CapabilityManager()

    assert manager.status() == {
        "dcs": {
            "ownship_export": False,
            "world_object_export": False,
            "sensor_export": False,
            "cockpit_state": False,
        },
        "coach": {
            "ownship_coaching": False,
            "formation_coaching": False,
            "carrier_pattern_coaching": False,
            "carrier_approach_geometry": False,
            "procedure_coaching": False,
        },
    }


def test_spatial_capabilities_require_ownship_and_world_object_export() -> None:
    manager = CapabilityManager(
        DcsCapabilities(
            ownship_export=True,
            world_object_export=True,
            cockpit_state=True,
        )
    )

    assert manager.coach.ownship_coaching is True
    assert manager.coach.formation_coaching is True
    assert manager.coach.carrier_pattern_coaching is True
    assert manager.coach.carrier_approach_geometry is True
    assert manager.coach.procedure_coaching is True

    ownship_only = CapabilityManager(DcsCapabilities(ownship_export=True))
    assert ownship_only.coach.ownship_coaching is True
    assert ownship_only.coach.formation_coaching is False
    assert ownship_only.coach.carrier_pattern_coaching is False
    assert ownship_only.coach.carrier_approach_geometry is False

    sensors_are_not_a_world_object_fallback = CapabilityManager(
        DcsCapabilities(ownship_export=True, sensor_export=True)
    )
    assert sensors_are_not_a_world_object_fallback.coach.formation_coaching is False
    assert (
        sensors_are_not_a_world_object_fallback.coach.carrier_pattern_coaching is False
    )


def test_permission_loss_is_published_before_update_returns() -> None:
    manager = CapabilityManager(
        DcsCapabilities(ownship_export=True, world_object_export=True)
    )
    observed = []
    manager.add_change_callback(observed.append)

    transition = manager.update(
        DcsCapabilities(ownship_export=True, world_object_export=False)
    )

    assert observed == [transition]
    assert transition.world_object_export_lost is True
    assert transition.previous_coach.formation_coaching is True
    assert transition.current_coach.formation_coaching is False
    assert manager.coach.formation_coaching is False
