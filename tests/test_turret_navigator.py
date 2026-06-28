"""
Unit tests for TurretNavigator (space_flight.ai.turret.turret_navigator).

TurretNavigator can be instantiated directly because it inherits from
GenericNavigator which only requires game.game_time.get_current_time().
"""

import uuid
from unittest.mock import MagicMock

import numpy as np
import pytest

from space_flight.ai import Intent, Personality
from space_flight.ai.turret.turret_navigator import NO_DIRECTION, TurretNavigator


@pytest.fixture
def mock_game():
    """
    Minimal game mock whose game_time starts at 0.0.
    """
    game = MagicMock()
    game.game_time.get_current_time.return_value = 0.0
    return game


@pytest.fixture
def turret_navigator(mock_game):
    """
    A TurretNavigator with mocked game and pawn.
    """
    pawn = MagicMock()
    pawn.position = np.zeros(3)
    pawn.speed = np.zeros(3)
    pawn.forward = np.array([0.0, 1.0, 0.0])
    pawn.parent = MagicMock()
    return TurretNavigator(
        game=mock_game, pawn=pawn, personality=Personality.TURRET_DEFAULT
    )


# ---------------------------------------------------------------------------
# navigate — IDLE intent
# ---------------------------------------------------------------------------


def test_turret_navigator_idle_returns_zero_direction(turret_navigator):
    """
    navigate() with IDLE intent must return the zero vector.
    """
    result = turret_navigator.navigate(intent=Intent.IDLE, target_dict={})

    np.testing.assert_array_equal(result, NO_DIRECTION)


def test_turret_navigator_idle_sets_engage_phase_to_empty_string(turret_navigator):
    """
    navigate() with IDLE intent must set engage_phase to an empty string.
    """
    turret_navigator.navigate(intent=Intent.IDLE, target_dict={})

    assert turret_navigator.engage_phase == ""


# ---------------------------------------------------------------------------
# navigate — ENGAGE intent (delegating to engage_target)
# ---------------------------------------------------------------------------


def test_turret_navigator_engage_with_empty_target_dict_returns_zero_direction(
    turret_navigator,
):
    """
    engage_target() with an empty target dict must return the zero direction
    and log a warning.
    """
    result = turret_navigator.navigate(intent=Intent.ENGAGE, target_dict={})

    np.testing.assert_array_equal(result, NO_DIRECTION)


def test_turret_navigator_engage_missing_target_returns_zero_direction(
    mock_game, turret_navigator
):
    """
    When engage_target() cannot find the target in interactions (ValueError),
    it must return the zero direction.
    """
    target_id = uuid.uuid4()
    mock_game.interactions.get_actor_index_from_id.side_effect = [0, ValueError("gone")]

    result = turret_navigator.navigate(
        intent=Intent.ENGAGE, target_dict={"target_id": target_id}
    )

    np.testing.assert_array_equal(result, NO_DIRECTION)
