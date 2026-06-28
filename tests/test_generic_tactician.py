"""
Unit tests for GenericTactician (space_flight.ai.generic.generic_tactician).

GenericTactician can be instantiated directly since its __init__ only stores
plain references.  Tests cover compute_alignment_score, evaluate_team_center,
evaluate_formation, and clean.
"""

import uuid
from unittest.mock import MagicMock

import numpy as np
import pytest

from space_flight.ai import Personality
from space_flight.ai.generic.generic_tactician import GenericTactician


@pytest.fixture
def mock_game():
    """
    A minimal game mock with a configurable live_actors list.
    """
    game = MagicMock()
    game.game_time.get_time_step.return_value = 0.1
    game.interactions.live_actors = []
    return game


@pytest.fixture
def tactician(mock_game):
    """
    A GenericTactician with mocked game and pawn using the fighter personality.
    """
    pawn = MagicMock()
    pawn.team = 1
    pawn.formation = None
    return GenericTactician(
        game=mock_game, pawn=pawn, personality=Personality.FIGHTER_DEFAULT
    )


# ---------------------------------------------------------------------------
# compute_alignment_score
# ---------------------------------------------------------------------------


def test_compute_alignment_score_forward_target_scores_at_maximum(tactician):
    """
    A target at full alignment (cos = 1.0) must return the maximum score of
    1.0 because the base is 1.0 and (base - 1) * focus = 0.
    """
    alignments = np.array([1.0])

    scores = tactician.compute_alignment_score(alignments, is_hunter=True)

    assert scores[0] == pytest.approx(1.0)


def test_compute_alignment_score_backward_target_scores_below_one(tactician):
    """
    A target directly behind (cos = -1.0) must score below 1.0.
    """
    alignments = np.array([-1.0])

    scores = tactician.compute_alignment_score(alignments, is_hunter=True)

    assert scores[0] < 1.0


def test_compute_alignment_score_perpendicular_target_scores_near_one(tactician):
    """
    A target at 90° (cos = 0.0) maps to a base score of 0.5 and should yield
    a score between 0 and 1 when focus is positive.
    """
    alignments = np.array([0.0])

    scores = tactician.compute_alignment_score(alignments, is_hunter=True)

    assert 0.0 < scores[0] < 1.0


def test_compute_alignment_score_hunter_and_prey_use_different_focus(tactician):
    """
    hunter_angular_focus and prey_angular_focus differ in the fighter default
    personality, so the hunter and prey scores for the same alignment must
    differ.
    """
    alignments = np.array([0.5])

    hunter_score = tactician.compute_alignment_score(alignments, is_hunter=True)
    prey_score = tactician.compute_alignment_score(alignments, is_hunter=False)

    assert not np.allclose(hunter_score, prey_score)


# ---------------------------------------------------------------------------
# evaluate_team_center
# ---------------------------------------------------------------------------


def test_evaluate_team_center_friends_averages_positions(mock_game, tactician):
    """
    evaluate_team_center('friends') must return the average position of all
    same-team actors excluding self.
    """
    friend_a = MagicMock()
    friend_a.team = 1
    friend_a.position = np.array([100.0, 0.0, 0.0])

    friend_b = MagicMock()
    friend_b.team = 1
    friend_b.position = np.array([200.0, 0.0, 0.0])

    mock_game.interactions.live_actors = [friend_a, friend_b, tactician.pawn]
    tactician.pawn.team = 1

    result = tactician.evaluate_team_center(team="friends")

    np.testing.assert_allclose(result["position"], np.array([150.0, 0.0, 0.0]))


def test_evaluate_team_center_foes_averages_positions(mock_game, tactician):
    """
    evaluate_team_center('foes') must return the average position of all
    actors on a different non-neutral team.
    """
    foe_a = MagicMock()
    foe_a.team = 2
    foe_a.position = np.array([0.0, 300.0, 0.0])

    foe_b = MagicMock()
    foe_b.team = 2
    foe_b.position = np.array([0.0, 100.0, 0.0])

    mock_game.interactions.live_actors = [foe_a, foe_b, tactician.pawn]
    tactician.pawn.team = 1

    result = tactician.evaluate_team_center(team="foes")

    np.testing.assert_allclose(result["position"], np.array([0.0, 200.0, 0.0]))


def test_evaluate_team_center_no_friends_returns_zero_vector(mock_game, tactician):
    """
    evaluate_team_center('friends') must return the zero vector when no
    same-team actors are alive.
    """
    mock_game.interactions.live_actors = [tactician.pawn]

    result = tactician.evaluate_team_center(team="friends")

    np.testing.assert_array_equal(result["position"], np.zeros(3))


def test_evaluate_team_center_invalid_team_raises(tactician):
    """
    evaluate_team_center must raise ValueError for an unrecognised team name.
    """
    with pytest.raises(ValueError):
        tactician.evaluate_team_center(team="enemies")


# ---------------------------------------------------------------------------
# evaluate_formation
# ---------------------------------------------------------------------------


def test_evaluate_formation_no_formation_returns_inactive(tactician):
    """
    When pawn.formation is None, evaluate_formation must return
    {'active': False}.
    """
    tactician.pawn.formation = None

    result = tactician.evaluate_formation()

    assert result == {"active": False}


def test_evaluate_formation_leader_index_zero_returns_inactive(tactician):
    """
    When the pawn is at index 0 (the leader), evaluate_formation must return
    {'active': False}.
    """
    formation = MagicMock()
    formation.get_ship_index.return_value = 0
    tactician.pawn.formation = formation

    result = tactician.evaluate_formation()

    assert result == {"active": False}


def test_evaluate_formation_wingman_returns_active_with_leader_id(tactician):
    """
    For a non-leader wingman, evaluate_formation must return a dict with
    'active': True and the leader's id as 'target_id'.
    """
    leader_id = uuid.uuid4()
    relative_position = np.array([30.0, -60.0, 0.0])
    formation = MagicMock()
    formation.get_ship_index.return_value = 1
    formation.ship_ids = [leader_id, tactician.pawn.id]
    formation.relative_positions = [np.zeros(3), relative_position]
    tactician.pawn.formation = formation

    result = tactician.evaluate_formation()

    assert result["active"] is True
    assert result["target_id"] == leader_id
    assert result["formation_index"] == 1
    np.testing.assert_array_equal(result["target_relative_position"], relative_position)


# ---------------------------------------------------------------------------
# clean
# ---------------------------------------------------------------------------


def test_generic_tactician_clean_sets_pawn_to_none(tactician):
    """
    clean() must release the reference to the pawn.
    """
    tactician.clean()

    assert tactician.pawn is None


def test_generic_tactician_clean_sets_game_to_none(tactician):
    """
    clean() must release the reference to the game.
    """
    tactician.clean()

    assert tactician.game is None
