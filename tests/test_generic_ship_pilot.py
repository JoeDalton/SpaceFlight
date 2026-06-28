"""
Unit tests for GenericShipPilot (space_flight.ai.generic.generic_ship_pilot).

GenericShipPilot is abstract (compute_angular_error raises NotImplementedError)
so tests instantiate FighterPilot, which provides a concrete implementation
while exercising all GenericShipPilot logic.
"""

from unittest.mock import MagicMock

import numpy as np
import pytest

from space_flight.ai import Personality
from space_flight.ai.fighter.fighter_pilot import FighterPilot


@pytest.fixture
def mock_game():
    """
    Minimal game mock whose game_time.get_current_time returns 0.0 so that
    PID controllers are initialised without error.
    """
    game = MagicMock()
    game.game_time.get_current_time.return_value = 0.0
    return game


@pytest.fixture
def pilot(mock_game):
    """
    A FighterPilot (concrete GenericShipPilot subclass) with mocked game and
    pawn.  The pawn's speed is set to zero so that the throttle PID error is
    zero and outputs remain at their starting values.
    """
    pawn = MagicMock()
    pawn.speed = np.zeros(3)
    return FighterPilot(
        game=mock_game, pawn=pawn, personality=Personality.FIGHTER_DEFAULT
    )


# ---------------------------------------------------------------------------
# __init__ — PID and state initialisation
# ---------------------------------------------------------------------------


def test_generic_ship_pilot_initial_throttle_is_zero(pilot):
    """
    Before any call to pilot(), throttle must be at its initial value of 0.0.
    """
    assert pilot.throttle == pytest.approx(0.0)


def test_generic_ship_pilot_initial_yaw_rate_is_zero(pilot):
    """
    Before any call to pilot(), yaw_rate must be at its initial value of 0.0.
    """
    assert pilot.yaw_rate == pytest.approx(0.0)


def test_generic_ship_pilot_initial_pitch_rate_is_zero(pilot):
    """
    Before any call to pilot(), pitch_rate must be at its initial value of 0.0.
    """
    assert pilot.pitch_rate == pytest.approx(0.0)


def test_generic_ship_pilot_initial_roll_rate_is_zero(pilot):
    """
    Before any call to pilot(), roll_rate must be at its initial value of 0.0.
    """
    assert pilot.roll_rate == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# set_on / set_off
# ---------------------------------------------------------------------------


def test_generic_ship_pilot_set_on_enables_all_pids(pilot):
    """
    set_on() must enable the auto mode on all four PID controllers without
    raising an exception.
    """
    pilot.set_on(
        current_normalized_yaw_rate_command=0.0,
        current_normalized_pitch_rate_command=0.0,
        current_normalized_roll_rate_command=0.0,
        current_throttle_command=0.0,
    )

    assert pilot.pid_yaw.auto_mode is True
    assert pilot.pid_pitch.auto_mode is True
    assert pilot.pid_roll.auto_mode is True
    assert pilot.pid_throttle.auto_mode is True


def test_generic_ship_pilot_set_off_disables_all_pids(pilot):
    """
    set_off() must disable the auto mode on all four PID controllers.
    """
    pilot.set_on()
    pilot.set_off()

    assert pilot.pid_yaw.auto_mode is False
    assert pilot.pid_pitch.auto_mode is False
    assert pilot.pid_roll.auto_mode is False
    assert pilot.pid_throttle.auto_mode is False


# ---------------------------------------------------------------------------
# pilot — return type and clamping
# ---------------------------------------------------------------------------


def test_generic_ship_pilot_pilot_returns_four_tuple(pilot, mock_game):
    """
    pilot() must return exactly four values: (throttle, yaw, pitch, roll).
    """
    pilot.pawn.right = np.array([1.0, 0.0, 0.0])
    pilot.pawn.forward = np.array([0.0, 1.0, 0.0])
    pilot.pawn.up = np.array([0.0, 0.0, 1.0])
    mock_game.scene.up_direction = np.array([0.0, 0.0, 1.0])

    result = pilot.pilot(target_direction=np.zeros(3), desired_speed_mps=0.0)

    assert len(result) == 4


def test_generic_ship_pilot_throttle_clipped_to_minimum(pilot, mock_game):
    """
    The throttle output from pilot() must never be below the minimum_throttle
    value defined in the personality.
    """
    pilot.pawn.right = np.array([1.0, 0.0, 0.0])
    pilot.pawn.forward = np.array([0.0, 1.0, 0.0])
    pilot.pawn.up = np.array([0.0, 0.0, 1.0])
    mock_game.scene.up_direction = np.array([0.0, 0.0, 1.0])

    throttle, _, _, _ = pilot.pilot(target_direction=np.zeros(3), desired_speed_mps=0.0)

    minimum_throttle = Personality.FIGHTER_DEFAULT["pilot"]["minimum_throttle"]
    assert throttle >= minimum_throttle
