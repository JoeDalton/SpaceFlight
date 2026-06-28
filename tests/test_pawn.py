import uuid
from unittest.mock import MagicMock

import numpy as np
import pytest

from space_flight.actors.pawn import Pawn


@pytest.fixture
def mock_game():
    """
    Minimal game mock sufficient for Pawn instantiation.
    """
    return MagicMock()


@pytest.fixture
def mock_parent():
    """
    Minimal parent mock sufficient for Pawn instantiation.
    """
    return MagicMock()


def test_pawn_init_sets_team(mock_game, mock_parent):
    """
    Pawn stores the given team value on construction.
    """
    pawn = Pawn(game=mock_game, parent=mock_parent, team=2)

    assert pawn.team == 2


def test_pawn_init_default_team_is_zero(mock_game, mock_parent):
    """
    Pawn defaults to team 0 when no team is supplied.
    """
    pawn = Pawn(game=mock_game, parent=mock_parent)

    assert pawn.team == 0


def test_pawn_init_assigns_unique_id(mock_game, mock_parent):
    """
    Each Pawn receives a distinct UUID on construction.
    """
    pawn_a = Pawn(game=mock_game, parent=mock_parent)
    pawn_b = Pawn(game=mock_game, parent=mock_parent)

    assert isinstance(pawn_a.id, uuid.UUID)
    assert pawn_a.id != pawn_b.id


def test_pawn_init_target_fields_are_none(mock_game, mock_parent):
    """
    Pawn starts with all target fields cleared.
    """
    pawn = Pawn(game=mock_game, parent=mock_parent)

    assert pawn.target is None
    assert pawn.target_id is None
    assert pawn.target_idx is None


def test_pawn_init_position_is_zero_vector(mock_game, mock_parent):
    """
    Pawn starts at the origin.
    """
    pawn = Pawn(game=mock_game, parent=mock_parent)

    np.testing.assert_array_equal(pawn.position, np.zeros(3))


def test_pawn_init_speed_is_zero_vector(mock_game, mock_parent):
    """
    Pawn starts with zero speed.
    """
    pawn = Pawn(game=mock_game, parent=mock_parent)

    np.testing.assert_array_equal(pawn.speed, np.zeros(3))


def test_pawn_init_is_not_dead(mock_game, mock_parent):
    """
    Pawn is alive on construction.
    """
    pawn = Pawn(game=mock_game, parent=mock_parent)

    assert pawn.is_dead is False


def test_pawn_init_is_not_clean(mock_game, mock_parent):
    """
    Pawn is not yet cleaned on construction.
    """
    pawn = Pawn(game=mock_game, parent=mock_parent)

    assert pawn.is_clean is False


def test_pawn_clean_clears_target_fields(mock_game, mock_parent):
    """
    clean() sets all target tracking fields back to None.
    """
    pawn = Pawn(game=mock_game, parent=mock_parent)
    pawn.target = MagicMock()
    pawn.target_id = uuid.uuid4()
    pawn.target_idx = 3

    pawn.clean()

    assert pawn.target is None
    assert pawn.target_id is None
    assert pawn.target_idx is None


def test_pawn_clean_is_idempotent(mock_game, mock_parent):
    """
    Calling clean() twice does not raise and leaves targets as None.
    """
    pawn = Pawn(game=mock_game, parent=mock_parent)
    pawn.target = MagicMock()

    pawn.clean()
    pawn.clean()

    assert pawn.target is None


def test_pawn_stores_game_and_parent_references(mock_game, mock_parent):
    """
    Pawn holds references to both the game and its parent.
    """
    pawn = Pawn(game=mock_game, parent=mock_parent)

    assert pawn.game is mock_game
    assert pawn.parent is mock_parent


def test_pawn_formation_starts_as_none(mock_game, mock_parent):
    """
    Pawn has no formation assignment on construction.
    """
    pawn = Pawn(game=mock_game, parent=mock_parent)

    assert pawn.formation is None
