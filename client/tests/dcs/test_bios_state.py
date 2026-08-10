from __future__ import annotations

import pytest
from dcs_copilot.dcs.bios_state import DcsBiosState


def test_write_is_available_and_tracks_changes() -> None:
    state = DcsBiosState()
    assert state.read(10, 2) is None

    first = state.apply_write(10, b"\x34\x12", received_at=1.0)
    second = state.apply_write(10, b"\x34\x12", received_at=2.0)

    assert state.read(10, 2) == b"\x34\x12"
    assert first.changed is True
    assert second.changed is False
    assert state.latest_write_at == 2.0
    assert state.updated_at(10, 2) == 2.0


def test_clear_availability_does_not_reuse_stale_values() -> None:
    state = DcsBiosState()
    state.apply_write(0, b"data")
    state.clear_availability()
    assert state.read(0, 4) is None
    assert state.updated_at(0, 4) is None


@pytest.mark.parametrize("address,length", [(-1, 1), (65535, 2), (0, -1)])
def test_invalid_read_is_rejected(address: int, length: int) -> None:
    with pytest.raises(ValueError):
        DcsBiosState().read(address, length)
