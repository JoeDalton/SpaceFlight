"""
Unit tests for CapitalShipTactician space_flight.ai.capital_ship.capital_ship_tactician

CapitalShipTactician can be instantiated directly since its __init__ only
delegates to GenericTactician and adds a scripted_prey_dict attribute.
"""

from unittest.mock import MagicMock

import pytest

from space_flight.ai import Intent, Personality
from space_flight.ai.capital_ship.capital_ship_tactician import CapitalShipTactician


def make_capital_ship_tactician(
    mock_game,
    health: float = 1.0,
    shield_generators=None,
) -> CapitalShipTactician:
    """
    Build a CapitalShipTactician with the given pawn state.

    :param mock_game: the mocked game object
    :param health: normalised pawn health value
    :param shield_generators: list of shield generator stubs, or None to
                              omit the attribute (simulating no shield
                              subsystem)
    :return: a CapitalShipTactician ready for testing
    """
    pawn = MagicMock()
    pawn.health = health
    pawn.team = 1
    pawn.formation = None
    if shield_generators is None:
        del pawn.shield_generators  # triggers AttributeError via spec removal
    else:
        pawn.shield_generators = shield_generators
    return CapitalShipTactician(
        game=mock_game, pawn=pawn, personality=Personality.CAPITAL_SHIP_DEFAULT
    )


# ---------------------------------------------------------------------------
# evaluate_fighting_shape — without shield generators
# ---------------------------------------------------------------------------


def test_evaluate_fighting_shape_without_shield_generators():
    """
    When the pawn has no shield_generators attribute, evaluate_fighting_shape
    must return 0.5 * health with no error.
    """
    mock_game = MagicMock()
    tactician = make_capital_ship_tactician(
        mock_game, health=1.0, shield_generators=None
    )

    result = tactician.evaluate_fighting_shape()

    assert result == pytest.approx(0.5 * 1.0)


# ---------------------------------------------------------------------------
# evaluate_fighting_shape — with shield generators
# ---------------------------------------------------------------------------


def make_shield_generator(shield_level: float) -> MagicMock:
    """
    Build a shield generator stub returning a fixed shield level.

    :param shield_level: the value returned by get_shield_level()
    :return: a MagicMock shield generator
    """
    gen = MagicMock()
    gen.get_shield_level.return_value = shield_level
    return gen


def test_evaluate_fighting_shape_with_single_shield_generator():
    """
    With one shield generator the fighting shape must equal
    0.5 * health + shield_level.
    """
    mock_game = MagicMock()
    health = 0.8
    shield_level = 0.6
    generators = [make_shield_generator(shield_level)]
    tactician = make_capital_ship_tactician(
        mock_game, health=health, shield_generators=generators
    )

    result = tactician.evaluate_fighting_shape()

    assert result == pytest.approx(0.5 * health + shield_level)


def test_evaluate_fighting_shape_with_multiple_shield_generators():
    """
    With multiple shield generators, the fighting shape must equal
    0.5 * health + sum of all shield levels.
    """
    mock_game = MagicMock()
    health = 0.6
    shield_levels = [0.4, 0.3, 0.5]
    generators = [make_shield_generator(level) for level in shield_levels]
    tactician = make_capital_ship_tactician(
        mock_game, health=health, shield_generators=generators
    )

    result = tactician.evaluate_fighting_shape()

    assert result == pytest.approx(0.5 * health + sum(shield_levels))


def test_evaluate_fighting_shape_fully_depleted():
    """
    With health = 0 and all shield generators at zero, the fighting shape
    must be 0.0.
    """
    mock_game = MagicMock()
    generators = [make_shield_generator(0.0), make_shield_generator(0.0)]
    tactician = make_capital_ship_tactician(
        mock_game, health=0.0, shield_generators=generators
    )

    result = tactician.evaluate_fighting_shape()

    assert result == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# __init__ — scripted_prey_dict
# ---------------------------------------------------------------------------


def test_scripted_prey_dict_is_inactive_by_default():
    """
    After construction, scripted_prey_dict must have 'active': False.
    """
    mock_game = MagicMock()
    tactician = make_capital_ship_tactician(mock_game)

    assert tactician.scripted_prey_dict == {"active": False}


# ---------------------------------------------------------------------------
# update_intent — scripted prey active
# ---------------------------------------------------------------------------


def test_update_intent_scripted_prey_returns_engage():
    """
    When scripted_prey_dict has 'active': True, update_intent must return
    ENGAGE immediately (after checking fighting shape).

    min_fighting_shape is 2.0, so health must be high enough that
    0.5 * health > 2.0 (i.e. health > 4.0) to pass the shape check.
    """
    mock_game = MagicMock()
    health = 10.0  # 0.5 * 10 = 5.0 > min_fighting_shape (2.0)
    tactician = make_capital_ship_tactician(
        mock_game, health=health, shield_generators=None
    )
    tactician.scripted_prey_dict = {"active": True, "target_id": "mock_target"}

    intent, target_dict = tactician.update_intent()

    assert intent == Intent.ENGAGE
    assert target_dict is tactician.scripted_prey_dict


# ---------------------------------------------------------------------------
# update_intent — poor fighting shape
# ---------------------------------------------------------------------------


def test_update_intent_poor_fighting_shape_returns_disengage():
    """
    When fighting shape falls below min_fighting_shape, update_intent must
    return DISENGAGE regardless of scripted prey.
    """
    mock_game = MagicMock()
    health = 0.0  # fighting shape = 0.0 < min_fighting_shape
    tactician = make_capital_ship_tactician(
        mock_game, health=health, shield_generators=None
    )
    tactician.scripted_prey_dict = {"active": True, "target_id": "mock_target"}

    mock_game.interactions.live_actors = []
    tactician.pawn.team = 1

    intent, _ = tactician.update_intent()

    assert intent == Intent.DISENGAGE
