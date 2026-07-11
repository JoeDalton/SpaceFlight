"""
Unit tests for FighterTactician (space_flight.ai.fighter.fighter_tactician).

FighterTactician can be instantiated directly since its __init__ only
delegates to GenericTactician which stores plain references.
"""

from unittest.mock import MagicMock

import pytest

from space_flight.ai import AttackMode, Personality
from space_flight.ai.fighter.fighter_tactician import FighterTactician


@pytest.fixture
def mock_game():
    """
    Minimal game mock.
    """
    return MagicMock()


def make_fighter_tactician(
    mock_game, health: float = 1.0, shield: float = 1.0
) -> FighterTactician:
    """
    Build a FighterTactician with the given pawn health and shield.

    :param mock_game: the mocked game object
    :param health: normalised pawn health in [0, 1]
    :param shield: normalised pawn shield level in [0, 1]
    :return: a FighterTactician ready for testing
    """
    pawn = MagicMock()
    pawn.health = health
    pawn.shield_level = shield
    pawn.team = 1
    pawn.formation = None
    return FighterTactician(
        game=mock_game, pawn=pawn, personality=Personality.FIGHTER_DEFAULT
    )


# ---------------------------------------------------------------------------
# evaluate_fighting_shape
# ---------------------------------------------------------------------------


def test_evaluate_fighting_shape_full_health_and_shield(mock_game):
    """
    With health = 1.0 and shield = 1.0 the fighting shape must equal
    0.5 * 1.0 + 1.0 = 1.5.
    """
    tactician = make_fighter_tactician(mock_game, health=1.0, shield=1.0)

    result = tactician.evaluate_fighting_shape()

    assert result == pytest.approx(1.5)


def test_evaluate_fighting_shape_no_shield(mock_game):
    """
    With shield = 0.0 the fighting shape must equal 0.5 * health.
    """
    health = 0.8
    tactician = make_fighter_tactician(mock_game, health=health, shield=0.0)

    result = tactician.evaluate_fighting_shape()

    assert result == pytest.approx(0.5 * health)


def test_evaluate_fighting_shape_no_health(mock_game):
    """
    With health = 0.0 the fighting shape must equal the shield level.
    """
    shield = 0.6
    tactician = make_fighter_tactician(mock_game, health=0.0, shield=shield)

    result = tactician.evaluate_fighting_shape()

    assert result == pytest.approx(shield)


def test_evaluate_fighting_shape_completely_destroyed(mock_game):
    """
    With health = 0.0 and shield = 0.0 the fighting shape must be zero.
    """
    tactician = make_fighter_tactician(mock_game, health=0.0, shield=0.0)

    result = tactician.evaluate_fighting_shape()

    assert result == pytest.approx(0.0)


@pytest.mark.parametrize(
    "health, shield, expected",
    [
        (1.0, 1.0, 1.5),
        (0.5, 0.5, 0.75),
        (0.0, 0.5, 0.5),
        (0.4, 0.0, 0.2),
    ],
)
def test_evaluate_fighting_shape_parametrized(mock_game, health, shield, expected):
    """
    Parametrised table: evaluate_fighting_shape must return 0.5 * health + shield
    for a variety of input combinations.
    """
    tactician = make_fighter_tactician(mock_game, health=health, shield=shield)

    result = tactician.evaluate_fighting_shape()

    assert result == pytest.approx(expected)


# ---------------------------------------------------------------------------
# _select_attack_mode
# ---------------------------------------------------------------------------


def _wire_target_mobility(mock_game, mobility: float):
    """Point the tactician's interactions at a single target of given mobility."""
    target = MagicMock()
    target.mobility = mobility
    mock_game.interactions.get_actor_index_from_id.return_value = 0
    mock_game.interactions.actors = [target]


def test_select_attack_mode_slow_target_strafes(mock_game):
    """
    A target below the strafe mobility threshold is attacked with a STRAFE run.
    """
    tactician = make_fighter_tactician(mock_game)
    threshold = Personality.FIGHTER_DEFAULT["tactician"]["strafe_mobility_threshold"]
    _wire_target_mobility(mock_game, mobility=threshold * 0.5)

    assert tactician._select_attack_mode(target_id="t") == AttackMode.STRAFE


def test_select_attack_mode_agile_target_pursues(mock_game):
    """
    A mobile target above the threshold is chased with PURSUIT.
    """
    tactician = make_fighter_tactician(mock_game)
    threshold = Personality.FIGHTER_DEFAULT["tactician"]["strafe_mobility_threshold"]
    _wire_target_mobility(mock_game, mobility=min(1.0, threshold * 2.0 + 0.5))

    assert tactician._select_attack_mode(target_id="t") == AttackMode.PURSUIT


def test_select_attack_mode_missing_target_defaults_to_pursuit(mock_game):
    """
    If the target can no longer be resolved, default to PURSUIT.
    """
    tactician = make_fighter_tactician(mock_game)
    mock_game.interactions.get_actor_index_from_id.side_effect = ValueError

    assert tactician._select_attack_mode(target_id="t") == AttackMode.PURSUIT
