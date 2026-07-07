"""
Unit tests for TrackingMountNavigator
(space_flight.ai.tracking_mount.tracking_mount_navigator).

The navigator is a pure aimer: it computes a lead direction and publishes it onto
the pawn (aim_direction / target_distance_m) for the pawn to act upon; it never
fires or grabs itself.
"""

import uuid
from unittest.mock import MagicMock

import numpy as np
import pytest

from space_flight.ai import Intent, Personality
from space_flight.ai.tracking_mount.tracking_mount_navigator import (
    NO_DIRECTION,
    TrackingMountNavigator,
)


@pytest.fixture
def mock_game():
    """
    Minimal game mock whose game_time starts at 0.0.
    """
    game = MagicMock()
    game.game_time.get_current_time.return_value = 0.0
    return game


@pytest.fixture
def navigator(mock_game):
    """
    A TrackingMountNavigator with mocked game and pawn.
    """
    pawn = MagicMock()
    pawn.position = np.zeros(3)
    pawn.speed = np.zeros(3)
    pawn.forward = np.array([0.0, 1.0, 0.0])
    pawn.parent = MagicMock()
    return TrackingMountNavigator(
        game=mock_game, pawn=pawn, personality=Personality.TURRET_DEFAULT
    )


# ---------------------------------------------------------------------------
# navigate — IDLE intent
# ---------------------------------------------------------------------------


def test_navigator_idle_returns_zero_direction(navigator):
    """
    navigate() with IDLE intent must return the zero vector.
    """
    result = navigator.navigate(intent=Intent.IDLE, target_dict={})

    np.testing.assert_array_equal(result, NO_DIRECTION)


def test_navigator_idle_publishes_no_engagement(navigator):
    """
    IDLE clears the pawn's published aim so it will not act: zero direction and
    an unreachable distance.
    """
    navigator.navigate(intent=Intent.IDLE, target_dict={})

    np.testing.assert_array_equal(navigator.pawn.aim_direction, np.zeros(3))
    assert navigator.pawn.target_distance_m == np.inf


# ---------------------------------------------------------------------------
# navigate — ENGAGE intent (delegating to engage_target)
# ---------------------------------------------------------------------------


def test_navigator_engage_with_empty_target_dict_returns_zero_direction(navigator):
    """
    engage_target() with an empty target dict must return the zero direction.
    """
    result = navigator.navigate(intent=Intent.ENGAGE, target_dict={})

    np.testing.assert_array_equal(result, NO_DIRECTION)


def test_navigator_engage_missing_target_returns_zero_direction(mock_game, navigator):
    """
    When engage_target() cannot find the target in interactions (ValueError),
    it must return the zero direction and publish no engagement.
    """
    target_id = uuid.uuid4()
    mock_game.interactions.get_actor_index_from_id.side_effect = [0, ValueError("gone")]

    result = navigator.navigate(
        intent=Intent.ENGAGE, target_dict={"target_id": target_id}
    )

    np.testing.assert_array_equal(result, NO_DIRECTION)
    assert navigator.pawn.target_distance_m == np.inf


def test_navigator_engage_publishes_aim_solution_to_pawn(mock_game, navigator):
    """
    A successful engage publishes the lead direction and target distance onto
    the pawn (so the pawn's own action can fire/grab on the same solution) and
    returns the aim direction.
    """
    target_id = uuid.uuid4()
    mock_game.interactions.get_actor_index_from_id.side_effect = [0, 1]
    mock_game.interactions.distances = np.array([[0.0, 300.0], [300.0, 0.0]])
    directions = np.zeros((2, 2, 3))
    directions[0, 1, :] = np.array([0.0, 1.0, 0.0])  # target straight ahead
    mock_game.interactions.directions = directions
    mock_game.interactions.rel_velocities = np.zeros((2, 2, 3))

    result = navigator.navigate(
        intent=Intent.ENGAGE, target_dict={"target_id": target_id}
    )

    # Target dead ahead => aim direction is +Y and distance is published.
    np.testing.assert_allclose(result, np.array([0.0, 1.0, 0.0]), atol=1e-6)
    np.testing.assert_allclose(
        navigator.pawn.aim_direction, np.array([0.0, 1.0, 0.0]), atol=1e-6
    )
    assert navigator.pawn.target_distance_m == pytest.approx(300.0)
