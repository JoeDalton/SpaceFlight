"""
Unit tests for FighterPilot (space_flight.ai.fighter.fighter_pilot).

FighterPilot can be instantiated directly because its __init__ only sets up
PID controllers and needs game.game_time.get_current_time().  The
compute_angular_error method is the primary logic under test.
"""

from unittest.mock import MagicMock

import numpy as np
import pytest

from space_flight.ai import Personality
from space_flight.ai.fighter.fighter_pilot import FighterPilot


@pytest.fixture
def mock_game():
    """
    Minimal game mock with a game_time that returns 0.0 and a scene with a
    known up direction.
    """
    game = MagicMock()
    game.game_time.get_current_time.return_value = 0.0
    game.scene.up_direction = np.array([0.0, 0.0, 1.0])
    return game


def make_pilot_with_axes(
    mock_game,
    right: np.ndarray = None,
    forward: np.ndarray = None,
    up: np.ndarray = None,
) -> FighterPilot:
    """
    Build a FighterPilot whose pawn axes are set to the provided vectors.

    :param mock_game: the mocked game object
    :param right: ship right axis (X); defaults to world X
    :param forward: ship forward axis (Y); defaults to world Y
    :param up: ship up axis (Z); defaults to world Z
    :return: a FighterPilot with the given ship orientation
    """
    pawn = MagicMock()
    pawn.right = np.array([1.0, 0.0, 0.0]) if right is None else right
    pawn.forward = np.array([0.0, 1.0, 0.0]) if forward is None else forward
    pawn.up = np.array([0.0, 0.0, 1.0]) if up is None else up
    pawn.speed = np.zeros(3)
    return FighterPilot(
        game=mock_game, pawn=pawn, personality=Personality.FIGHTER_DEFAULT
    )


# ---------------------------------------------------------------------------
# compute_angular_error — zero direction
# ---------------------------------------------------------------------------


def test_compute_angular_error_zero_direction_returns_all_zeros(mock_game):
    """
    A zero target_direction vector must yield zero errors for yaw, pitch, and
    roll, and a cos_angle of 1.0 (no rotation needed).
    """
    pilot = make_pilot_with_axes(mock_game)

    yaw, pitch, roll, cos_angle = pilot.compute_angular_error(np.zeros(3))

    assert yaw == pytest.approx(0.0)
    assert pitch == pytest.approx(0.0)
    assert roll == pytest.approx(0.0)
    assert cos_angle == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# compute_angular_error — forward target
# ---------------------------------------------------------------------------


def test_compute_angular_error_target_straight_ahead_has_zero_yaw_and_pitch(mock_game):
    """
    When the target is exactly in the ship's forward direction, both yaw and
    pitch errors must be (near) zero.
    """
    pilot = make_pilot_with_axes(mock_game)

    yaw, pitch, _, _ = pilot.compute_angular_error(np.array([0.0, 1.0, 0.0]))

    assert yaw == pytest.approx(0.0, abs=1e-6)
    assert pitch == pytest.approx(0.0, abs=1e-6)


def test_compute_angular_error_forward_target_cos_angle_is_one(mock_game):
    """
    For a target straight ahead the alignment (cos) must equal 1.0.
    """
    pilot = make_pilot_with_axes(mock_game)

    _, _, _, cos_angle = pilot.compute_angular_error(np.array([0.0, 1.0, 0.0]))

    assert cos_angle == pytest.approx(1.0, abs=1e-6)


# ---------------------------------------------------------------------------
# compute_angular_error — side target
# ---------------------------------------------------------------------------


def test_compute_angular_error_target_to_the_right_has_positive_yaw(mock_game):
    """
    A target to the right of the ship (along the ship X axis) must produce a
    positive yaw error, directing the ship to rotate right.
    """
    pilot = make_pilot_with_axes(mock_game)

    yaw, _, _, _ = pilot.compute_angular_error(np.array([1.0, 0.0, 0.0]))

    assert yaw > 0.0


def test_compute_angular_error_target_above_has_nonzero_pitch(mock_game):
    """
    A target above the ship (along the ship Z axis) must produce a nonzero
    pitch error.
    """
    pilot = make_pilot_with_axes(mock_game)

    _, pitch, _, _ = pilot.compute_angular_error(np.array([0.0, 0.0, 1.0]))

    assert abs(pitch) > 0.0


def test_compute_angular_error_returns_float_values(mock_game):
    """
    All four returned values must be scalars (not arrays).
    """
    pilot = make_pilot_with_axes(mock_game)

    yaw, pitch, roll, cos_angle = pilot.compute_angular_error(np.array([1.0, 1.0, 0.0]))

    for value in (yaw, pitch, roll, cos_angle):
        assert np.isscalar(value) or (isinstance(value, np.ndarray) and value.ndim == 0)
