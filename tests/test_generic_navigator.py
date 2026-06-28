"""
Unit tests for GenericNavigator (space_flight.ai.generic.generic_navigator).

GenericNavigator can be instantiated directly since its __init__ only needs
game.game_time.get_current_time() and stores plain references.
"""

from unittest.mock import MagicMock

import numpy as np
import pytest

from space_flight.ai import Personality
from space_flight.ai.generic.generic_navigator import GenericNavigator


@pytest.fixture
def mock_game():
    """
    A minimal game mock whose game_time.get_current_time starts at 0.0.
    """
    game = MagicMock()
    game.game_time.get_current_time.return_value = 0.0
    return game


@pytest.fixture
def navigator(mock_game):
    """
    A GenericNavigator instance with mocked game and pawn.
    """
    pawn = MagicMock()
    return GenericNavigator(
        game=mock_game, pawn=pawn, personality=Personality.FIGHTER_DEFAULT
    )


# ---------------------------------------------------------------------------
# record_behaviour
# ---------------------------------------------------------------------------


def test_record_behaviour_same_behaviour_increments_duration(mock_game, navigator):
    """
    Calling record_behaviour with the same behaviour name accumulates time
    since the last update.
    """
    mock_game.game_time.get_current_time.return_value = 1.0
    navigator.record_behaviour("patrol")

    mock_game.game_time.get_current_time.return_value = 2.5
    navigator.record_behaviour("patrol")

    assert navigator.behaviour_duration_s == pytest.approx(1.5)


def test_record_behaviour_different_behaviour_resets_duration(mock_game, navigator):
    """
    Switching to a different behaviour resets behaviour_duration_s to zero.
    """
    mock_game.game_time.get_current_time.return_value = 1.0
    navigator.record_behaviour("patrol")

    mock_game.game_time.get_current_time.return_value = 3.0
    navigator.record_behaviour("engage")

    assert navigator.behaviour_duration_s == pytest.approx(0.0)


def test_record_behaviour_different_behaviour_updates_behaviour_name(
    mock_game, navigator
):
    """
    After switching, the behaviour attribute holds the new name.
    """
    navigator.record_behaviour("patrol")
    navigator.record_behaviour("engage")

    assert navigator.behaviour == "engage"


def test_record_behaviour_updates_last_update_time(mock_game, navigator):
    """
    After each call, last_update_time must equal the current time.
    """
    mock_game.game_time.get_current_time.return_value = 5.0
    navigator.record_behaviour("idle")

    assert navigator.last_update_time == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# compute_constant_angle_pursuit
# ---------------------------------------------------------------------------


def test_compute_cap_returns_unit_vector(navigator):
    """
    compute_constant_angle_pursuit must return a unit vector.
    """
    direction = np.array([0.0, 1.0, 0.0])
    distance_m = 500.0
    lateral_speed = np.array([10.0, 0.0, 0.0])

    result = navigator.compute_constant_angle_pursuit(
        direction, distance_m, lateral_speed
    )

    assert np.linalg.norm(result) == pytest.approx(1.0, abs=1e-6)


def test_compute_cap_zero_lateral_speed_returns_given_direction(navigator):
    """
    With zero lateral speed the CAP formula reduces to the raw direction,
    scaled by distance and then normalised — which is just the direction itself.
    """
    direction = np.array([0.0, 1.0, 0.0])
    distance_m = 300.0
    lateral_speed = np.zeros(3)

    result = navigator.compute_constant_angle_pursuit(
        direction, distance_m, lateral_speed
    )

    np.testing.assert_allclose(result, direction, atol=1e-6)


def test_compute_cap_nonzero_lateral_speed_shifts_direction(navigator):
    """
    With nonzero lateral speed the result must differ from the raw direction.
    """
    direction = np.array([0.0, 1.0, 0.0])
    distance_m = 100.0
    lateral_speed = np.array([50.0, 0.0, 0.0])

    result = navigator.compute_constant_angle_pursuit(
        direction, distance_m, lateral_speed
    )

    assert not np.allclose(result, direction)


# ---------------------------------------------------------------------------
# compute_lead_pursuit
# ---------------------------------------------------------------------------


def test_compute_lead_pursuit_stationary_target_returns_direction_to_target(
    mock_game, navigator
):
    """
    For a stationary target the lead-pursuit direction must equal the unit
    vector from self to the target.
    """
    self_position = np.array([0.0, 0.0, 0.0])
    target_position = np.array([0.0, 100.0, 0.0])
    navigator.pawn.position = self_position

    result = navigator.compute_lead_pursuit(
        target_current_position=target_position,
        target_current_speed=np.zeros(3),
        lead_time_s=1.0,
    )

    np.testing.assert_allclose(result, np.array([0.0, 1.0, 0.0]), atol=1e-6)


def test_compute_lead_pursuit_returns_unit_vector(navigator):
    """
    compute_lead_pursuit must always return a unit vector (or zeros if the
    target is within tolerance).
    """
    navigator.pawn.position = np.zeros(3)
    target_position = np.array([3.0, 4.0, 0.0])

    result = navigator.compute_lead_pursuit(
        target_current_position=target_position,
        target_current_speed=np.array([1.0, 0.0, 0.0]),
        lead_time_s=0.5,
    )

    norm = np.linalg.norm(result)
    assert norm == pytest.approx(1.0, abs=1e-6)


def test_compute_lead_pursuit_at_zero_distance_returns_zero_vector(navigator):
    """
    When the predicted future position coincides with self the returned
    direction is the zero vector.
    """
    navigator.pawn.position = np.zeros(3)

    result = navigator.compute_lead_pursuit(
        target_current_position=np.zeros(3),
        target_current_speed=np.zeros(3),
        lead_time_s=1.0,
    )

    np.testing.assert_array_equal(result, np.zeros(3))


# ---------------------------------------------------------------------------
# clean
# ---------------------------------------------------------------------------


def test_generic_navigator_clean_sets_pawn_to_none(navigator):
    """
    clean() must release the reference to the pawn.
    """
    navigator.clean()

    assert navigator.pawn is None


def test_generic_navigator_clean_sets_game_to_none(navigator):
    """
    clean() must release the reference to the game.
    """
    navigator.clean()

    assert navigator.game is None
