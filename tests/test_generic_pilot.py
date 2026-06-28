"""
Unit tests for GenericPilot (space_flight.ai.generic.generic_pilot).

GenericPilot can be instantiated directly with mocked game and pawn since
its __init__ only stores references.  Abstract methods are also tested to
confirm they raise NotImplementedError.
"""

from unittest.mock import MagicMock

import pytest

from space_flight.ai import Personality
from space_flight.ai.generic.generic_pilot import GenericPilot


@pytest.fixture
def generic_pilot():
    """
    A fully-constructed GenericPilot with mocked game and pawn.
    """
    game = MagicMock()
    pawn = MagicMock()
    return GenericPilot(game=game, pawn=pawn, personality=Personality.FIGHTER_DEFAULT)


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------


def test_generic_pilot_stores_game(generic_pilot):
    """
    After construction, the game attribute must hold the provided game object.
    """
    assert generic_pilot.game is not None


def test_generic_pilot_stores_pawn(generic_pilot):
    """
    After construction, the pawn attribute must hold the provided pawn object.
    """
    assert generic_pilot.pawn is not None


def test_generic_pilot_stores_personality(generic_pilot):
    """
    After construction, the personality attribute must equal the dict provided.
    """
    assert generic_pilot.personality is Personality.FIGHTER_DEFAULT


# ---------------------------------------------------------------------------
# Abstract methods raise NotImplementedError
# ---------------------------------------------------------------------------


def test_generic_pilot_set_on_raises_not_implemented(generic_pilot):
    """
    GenericPilot.set_on() must raise NotImplementedError because it is
    overridden in concrete subclasses.
    """
    with pytest.raises(NotImplementedError):
        generic_pilot.set_on()


def test_generic_pilot_set_off_raises_not_implemented(generic_pilot):
    """
    GenericPilot.set_off() must raise NotImplementedError because it is
    overridden in concrete subclasses.
    """
    with pytest.raises(NotImplementedError):
        generic_pilot.set_off()


def test_generic_pilot_pilot_raises_not_implemented(generic_pilot):
    """
    GenericPilot.pilot() must raise NotImplementedError because it is
    overridden in concrete subclasses.
    """
    with pytest.raises(NotImplementedError):
        generic_pilot.pilot()


# ---------------------------------------------------------------------------
# clean
# ---------------------------------------------------------------------------


def test_generic_pilot_clean_sets_pawn_to_none(generic_pilot):
    """
    clean() must release the reference to the pawn.
    """
    generic_pilot.clean()

    assert generic_pilot.pawn is None


def test_generic_pilot_clean_sets_game_to_none(generic_pilot):
    """
    clean() must release the reference to the game.
    """
    generic_pilot.clean()

    assert generic_pilot.game is None
