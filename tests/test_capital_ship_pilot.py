"""
Unit tests for CapitalShipPilot (space_flight.ai.capital_ship.capital_ship_pilot).

CapitalShipPilot can be instantiated directly since it only needs
game.game_time.get_current_time() during PID initialisation.
"""

from unittest.mock import MagicMock

import numpy as np
import pytest

from space_flight.ai import Personality
from space_flight.ai.capital_ship.capital_ship_pilot import CapitalShipPilot


@pytest.fixture
def mock_game():
    """
    Minimal game mock with game_time returning 0.0 and a scene up direction.
    """
    game = MagicMock()
    game.game_time.get_current_time.return_value = 0.0
    game.scene.up_direction = np.array([0.0, 0.0, 1.0])
    return game


def make_capital_ship_pilot(
    mock_game,
    right: np.ndarray = None,
    forward: np.ndarray = None,
    up: np.ndarray = None,
) -> CapitalShipPilot:
    """
    Build a CapitalShipPilot whose pawn axes are set to the provided vectors.

    :param mock_game: the mocked game object
    :param right: ship right axis; defaults to world X
    :param forward: ship forward axis; defaults to world Y
    :param up: ship up axis; defaults to world Z
    :return: a CapitalShipPilot ready for testing
    """
    pawn = MagicMock()
    pawn.right = np.array([1.0, 0.0, 0.0]) if right is None else right
    pawn.forward = np.array([0.0, 1.0, 0.0]) if forward is None else forward
    pawn.up = np.array([0.0, 0.0, 1.0]) if up is None else up
    pawn.speed = np.zeros(3)
    return CapitalShipPilot(
        game=mock_game, pawn=pawn, personality=Personality.CAPITAL_SHIP_DEFAULT
    )


# ---------------------------------------------------------------------------
# compute_angular_error — zero direction
# ---------------------------------------------------------------------------


def test_capital_ship_pilot_zero_direction_returns_zero_errors(mock_game):
    """
    A zero target_direction must yield yaw, pitch, and roll errors all equal
    to 0.0 and cos_angle equal to 1.0.
    """
    pilot = make_capital_ship_pilot(mock_game)

    yaw, pitch, roll, cos_angle = pilot.compute_angular_error(np.zeros(3))

    assert yaw == pytest.approx(0.0)
    assert pitch == pytest.approx(0.0)
    assert roll == pytest.approx(0.0)
    assert cos_angle == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# compute_angular_error — forward target
# ---------------------------------------------------------------------------


def test_capital_ship_pilot_target_straight_ahead_has_zero_yaw_and_pitch(mock_game):
    """
    When the target is in the ship's forward direction, yaw and pitch errors
    must be (near) zero.
    """
    pilot = make_capital_ship_pilot(mock_game)

    yaw, pitch, _, _ = pilot.compute_angular_error(np.array([0.0, 1.0, 0.0]))

    assert yaw == pytest.approx(0.0, abs=1e-6)
    assert pitch == pytest.approx(0.0, abs=1e-6)


def test_capital_ship_pilot_forward_target_cos_angle_is_one(mock_game):
    """
    With a forward target the alignment (cos) must equal 1.0.
    """
    pilot = make_capital_ship_pilot(mock_game)

    _, _, _, cos_angle = pilot.compute_angular_error(np.array([0.0, 1.0, 0.0]))

    assert cos_angle == pytest.approx(1.0, abs=1e-6)


# ---------------------------------------------------------------------------
# compute_angular_error — side target
# ---------------------------------------------------------------------------


def test_capital_ship_pilot_target_to_right_has_positive_yaw(mock_game):
    """
    A target to the right (along the ship X axis) must produce a positive yaw
    error.
    """
    pilot = make_capital_ship_pilot(mock_game)

    yaw, _, _, _ = pilot.compute_angular_error(np.array([1.0, 0.0, 0.0]))

    assert yaw > 0.0


def test_capital_ship_pilot_roll_error_only_uses_scene_orientation(mock_game):
    """
    Unlike FighterPilot, CapitalShipPilot does not add a target-based roll
    contribution.  The roll error must be non-zero only due to the scene
    orientation even when the target is directly ahead.
    """
    pilot = make_capital_ship_pilot(mock_game)

    _, _, roll_forward, _ = pilot.compute_angular_error(np.array([0.0, 1.0, 0.0]))
    _, _, roll_side, _ = pilot.compute_angular_error(np.array([1.0, 0.0, 0.0]))

    # For a ship aligned with the world axes, the scene roll correction is zero
    # (right is perpendicular to up_direction).  Both cases should give ~0 roll.
    assert roll_forward == pytest.approx(roll_side, abs=1e-6)
