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
    zero and outputs remain at their starting values.  The pawn carries the
    X-wing's flight constants, read by the throttle feedforward.
    """
    pawn = MagicMock()
    pawn.speed = np.zeros(3)
    pawn.drag_factor = 0.5
    pawn.lift_inefficiency = 0.0005
    pawn.max_thrust_n = 10512.5
    pawn.lift_n = np.zeros(3)
    pawn.thrust_factor.return_value = 1.0
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


# ---------------------------------------------------------------------------
# compute_feedforward_throttle — drag-balance throttle estimate
# ---------------------------------------------------------------------------


def _thrust_at(throttle: float, pawn) -> float:
    """The thrust Ship.set_inputs produces for a (positive-thrust) throttle."""
    from space_flight.actors.ship import ZERO_THRUST_POSITION

    return (
        ((throttle - ZERO_THRUST_POSITION) / (1 - ZERO_THRUST_POSITION)) ** 2
        * pawn.max_thrust_n
        * pawn.thrust_factor()
    )


def test_feedforward_throttle_balances_drag_in_level_flight(pilot):
    """
    Without lift, the feedforward throttle produces exactly the thrust that
    balances the drag at the desired speed.
    """
    desired_speed_mps = 80.0

    throttle = pilot.compute_feedforward_throttle(desired_speed_mps)

    drag_n = pilot.pawn.drag_factor * desired_speed_mps**2
    assert _thrust_at(throttle, pilot.pawn) == pytest.approx(drag_n)


def test_feedforward_throttle_compensates_induced_drag(pilot):
    """
    Lift (a turn) adds induced drag, so the feedforward throttle rises.
    """
    level_throttle = pilot.compute_feedforward_throttle(80.0)
    pilot.pawn.lift_n = np.array([3000.0, 0.0, 0.0])

    turning_throttle = pilot.compute_feedforward_throttle(80.0)

    assert turning_throttle > level_throttle


def test_feedforward_throttle_saturates_at_full_throttle(pilot):
    """
    A desired speed beyond the ship's top speed asks for full throttle, not
    more.
    """
    assert pilot.compute_feedforward_throttle(2000.0) == pytest.approx(1.0)


def test_feedforward_throttle_holds_speed_when_on_target(pilot, mock_game):
    """
    At the desired speed (zero PID error), pilot() outputs the feedforward
    throttle rather than the bare PID's zero.
    """
    mock_game.scene.up_direction = np.array([0.0, 0.0, 1.0])
    pilot.pawn.right = np.array([1.0, 0.0, 0.0])
    pilot.pawn.forward = np.array([0.0, 1.0, 0.0])
    pilot.pawn.up = np.array([0.0, 0.0, 1.0])
    pilot.pawn.speed = np.array([0.0, 80.0, 0.0])

    throttle, _, _, _ = pilot.pilot(
        target_direction=np.zeros(3), desired_speed_mps=80.0
    )

    assert throttle == pytest.approx(pilot.compute_feedforward_throttle(80.0))


def test_throttle_pid_can_pull_below_feedforward(pilot):
    """
    The throttle PID is a signed correction of the feedforward throttle.
    """
    assert pilot.pid_throttle.output_limits == (-1.0, 1.0)
