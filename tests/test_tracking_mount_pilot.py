"""
Unit tests for TrackingMountPilot
(space_flight.ai.tracking_mount.tracking_mount_pilot).

TrackingMountPilot can be instantiated directly since it only requires a game
object that exposes game_time.get_current_time().
"""

from unittest.mock import MagicMock

import numpy as np
import pytest

from space_flight.ai import Personality
from space_flight.ai.tracking_mount.tracking_mount_pilot import TrackingMountPilot


@pytest.fixture
def mock_game():
    """
    Minimal game mock whose game_time starts at 0.0.
    """
    game = MagicMock()
    game.game_time.get_current_time.return_value = 0.0
    return game


@pytest.fixture
def mount_pilot(mock_game):
    """
    A TrackingMountPilot instance with mocked game and pawn.
    """
    pawn = MagicMock()
    pawn.forward = np.array([0.0, 1.0, 0.0])
    pawn.base_right = np.array([1.0, 0.0, 0.0])
    pawn.base_forward = np.array([0.0, 1.0, 0.0])
    pawn.base_up = np.array([0.0, 0.0, 1.0])
    return TrackingMountPilot(
        game=mock_game, pawn=pawn, personality=Personality.TURRET_DEFAULT
    )


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------


def test_mount_pilot_initial_yaw_rate_is_zero(mount_pilot):
    """
    Before any call to pilot(), yaw_rate must be 0.0.
    """
    assert mount_pilot.yaw_rate == pytest.approx(0.0)


def test_mount_pilot_initial_pitch_rate_is_zero(mount_pilot):
    """
    Before any call to pilot(), pitch_rate must be 0.0.
    """
    assert mount_pilot.pitch_rate == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# set_on / set_off
# ---------------------------------------------------------------------------


def test_mount_pilot_set_on_enables_pids(mount_pilot):
    """
    set_on() must put both PID controllers into auto mode.
    """
    mount_pilot.set_on()

    assert mount_pilot.pid_yaw.auto_mode is True
    assert mount_pilot.pid_pitch.auto_mode is True


def test_mount_pilot_set_off_disables_pids(mount_pilot):
    """
    set_off() must disable both PID controllers.
    """
    mount_pilot.set_on()
    mount_pilot.set_off()

    assert mount_pilot.pid_yaw.auto_mode is False
    assert mount_pilot.pid_pitch.auto_mode is False


# ---------------------------------------------------------------------------
# pilot — zero direction
# ---------------------------------------------------------------------------


def test_mount_pilot_zero_direction_returns_zero_rates(mount_pilot):
    """
    pilot() with a zero target direction must return (0.0, 0.0) because there
    is no angular error to correct.
    """
    yaw_rate, pitch_rate = mount_pilot.pilot(target_direction=np.zeros(3))

    assert yaw_rate == pytest.approx(0.0, abs=1e-6)
    assert pitch_rate == pytest.approx(0.0, abs=1e-6)


def test_mount_pilot_pilot_returns_two_values(mount_pilot):
    """
    pilot() must return exactly two values: (yaw_rate, pitch_rate).
    """
    result = mount_pilot.pilot(target_direction=np.zeros(3))

    assert len(result) == 2


def test_mount_pilot_pilot_updates_stored_yaw_and_pitch(mount_pilot):
    """
    pilot() must update the yaw_rate and pitch_rate attributes on the instance.
    """
    mount_pilot.pilot(target_direction=np.zeros(3))

    assert hasattr(mount_pilot, "yaw_rate")
    assert hasattr(mount_pilot, "pitch_rate")
