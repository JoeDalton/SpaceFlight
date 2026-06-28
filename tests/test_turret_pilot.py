"""
Unit tests for TurretPilot (space_flight.ai.turret.turret_pilot).

TurretPilot can be instantiated directly since it only requires a game object
that exposes game_time.get_current_time().
"""

from unittest.mock import MagicMock

import numpy as np
import pytest

from space_flight.ai import Personality
from space_flight.ai.turret.turret_pilot import TurretPilot


@pytest.fixture
def mock_game():
    """
    Minimal game mock whose game_time starts at 0.0.
    """
    game = MagicMock()
    game.game_time.get_current_time.return_value = 0.0
    return game


@pytest.fixture
def turret_pilot(mock_game):
    """
    A TurretPilot instance with mocked game and pawn.
    """
    pawn = MagicMock()
    pawn.forward = np.array([0.0, 1.0, 0.0])
    pawn.base_right = np.array([1.0, 0.0, 0.0])
    pawn.base_forward = np.array([0.0, 1.0, 0.0])
    pawn.base_up = np.array([0.0, 0.0, 1.0])
    return TurretPilot(
        game=mock_game, pawn=pawn, personality=Personality.TURRET_DEFAULT
    )


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------


def test_turret_pilot_initial_yaw_rate_is_zero(turret_pilot):
    """
    Before any call to pilot(), yaw_rate must be 0.0.
    """
    assert turret_pilot.yaw_rate == pytest.approx(0.0)


def test_turret_pilot_initial_pitch_rate_is_zero(turret_pilot):
    """
    Before any call to pilot(), pitch_rate must be 0.0.
    """
    assert turret_pilot.pitch_rate == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# set_on / set_off
# ---------------------------------------------------------------------------


def test_turret_pilot_set_on_enables_pids(turret_pilot):
    """
    set_on() must put both PID controllers into auto mode.
    """
    turret_pilot.set_on()

    assert turret_pilot.pid_yaw.auto_mode is True
    assert turret_pilot.pid_pitch.auto_mode is True


def test_turret_pilot_set_off_disables_pids(turret_pilot):
    """
    set_off() must disable both PID controllers.
    """
    turret_pilot.set_on()
    turret_pilot.set_off()

    assert turret_pilot.pid_yaw.auto_mode is False
    assert turret_pilot.pid_pitch.auto_mode is False


# ---------------------------------------------------------------------------
# pilot — zero direction
# ---------------------------------------------------------------------------


def test_turret_pilot_zero_direction_returns_zero_rates(turret_pilot):
    """
    pilot() with a zero target direction must return (0.0, 0.0) because there
    is no angular error to correct.
    """
    yaw_rate, pitch_rate = turret_pilot.pilot(target_direction=np.zeros(3))

    assert yaw_rate == pytest.approx(0.0, abs=1e-6)
    assert pitch_rate == pytest.approx(0.0, abs=1e-6)


def test_turret_pilot_pilot_returns_two_values(turret_pilot):
    """
    pilot() must return exactly two values: (yaw_rate, pitch_rate).
    """
    result = turret_pilot.pilot(target_direction=np.zeros(3))

    assert len(result) == 2


def test_turret_pilot_pilot_updates_stored_yaw_and_pitch(turret_pilot):
    """
    pilot() must update the yaw_rate and pitch_rate attributes on the instance.
    """
    turret_pilot.pilot(target_direction=np.zeros(3))

    assert hasattr(turret_pilot, "yaw_rate")
    assert hasattr(turret_pilot, "pitch_rate")
