from __future__ import annotations

from dcs_copilot_cloud.coach.coordinator import CoachCoordinator
from dcs_copilot_cloud.coach.tools import COACH_TOOL_NAMES, CoachToolExecutor


def test_coach_capability_tool_explains_server_restriction() -> None:
    executor = CoachToolExecutor(CoachCoordinator())

    result = executor.execute("coach_get_capabilities", {})

    assert result["formation"] is False
    assert result["case1_pattern"] is False
    assert result["carrier_approach"] is False
    assert "world-object export is disabled" in result["restriction"]


def test_coach_tool_allowlist_is_high_level_only() -> None:
    assert set(COACH_TOOL_NAMES) == {
        "coach_get_capabilities",
        "coach_start_exercise",
        "coach_stop_exercise",
        "coach_get_status",
        "coach_get_feedback",
        "coach_get_last_debrief",
    }
    assert all(
        "world" not in name and "object" not in name for name in COACH_TOOL_NAMES
    )
