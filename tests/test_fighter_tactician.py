"""
Unit tests for FighterTactician (space_flight.ai.fighter.fighter_tactician).

FighterTactician can be instantiated directly since its __init__ only
delegates to GenericTactician which stores plain references.
"""

import copy
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from space_flight.ai import AttackMode, Intent, Personality
from space_flight.ai.fighter.fighter_tactician import FighterTactician
from space_flight.ai.formation import Formation


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
    :param health: pawn health
    :param shield: pawn shield level
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
# _plan_attack — attack geometry
# ---------------------------------------------------------------------------


def _wire_target_mobility(mock_game, mobility: float):
    """Point the tactician's interactions at a single target of given mobility."""
    target = MagicMock()
    target.mobility = mobility
    mock_game.interactions.get_actor_index_from_id.return_value = 0
    mock_game.interactions.actors = [target]


def test_plan_attack_slow_target_strafes(mock_game):
    """
    A target below the strafe mobility threshold is attacked with a STRAFE run.
    """
    tactician = make_fighter_tactician(mock_game)
    threshold = Personality.FIGHTER_DEFAULT["tactician"]["strafe_mobility_threshold"]
    _wire_target_mobility(mock_game, mobility=threshold * 0.5)

    assert tactician._plan_attack(target_id="t")["attack_mode"] == AttackMode.STRAFE


def test_plan_attack_agile_target_pursues(mock_game):
    """
    A mobile target above the threshold is chased with PURSUIT.
    """
    tactician = make_fighter_tactician(mock_game)
    threshold = Personality.FIGHTER_DEFAULT["tactician"]["strafe_mobility_threshold"]
    _wire_target_mobility(mock_game, mobility=min(1.0, threshold * 2.0 + 0.5))

    assert tactician._plan_attack(target_id="t")["attack_mode"] == AttackMode.PURSUIT


def test_plan_attack_missing_target_defaults_to_a_gun_chase(mock_game):
    """
    If the target can no longer be resolved, default to a PURSUIT with guns.
    """
    tactician = make_fighter_tactician(mock_game)
    mock_game.interactions.get_actor_index_from_id.side_effect = ValueError

    assert tactician._plan_attack(target_id="t") == {
        "attack_mode": AttackMode.PURSUIT,
        "weapon": "guns",
        "launcher": None,
    }


# ---------------------------------------------------------------------------
# _plan_attack / _choose_weapon — weapon choice
# ---------------------------------------------------------------------------


def _launcher(category, stock=4, target_mobility="agile"):
    """A stand-in secondary weapon launcher, meant for targets of that mobility."""
    return SimpleNamespace(
        category=category,
        stock=stock,
        conf={"target_mobility": target_mobility},
    )


def _arm(tactician, *launchers):
    """Give the tactician's pawn these secondary weapons, in loadout order."""
    tactician.pawn.secondary_cycle.return_value = list(launchers)


def _wire_numeric_target(
    mock_game, tactician, mobility, health, shield_level, target_id="t", primary=False
):
    """Point the interactions at one fully-numeric target for the bomb scoring."""
    target = MagicMock()
    target.mobility = mobility
    target.health = health
    target.shield_level = shield_level
    target.id = target_id
    mock_game.interactions.get_actor_index_from_id.return_value = 0
    mock_game.interactions.actors = [target]
    tactician.primary_target_ids = [target_id] if primary else []
    return target


def _wire_hard_stationary_primary(mock_game, tactician):
    """The ideal bomb target: tough, valuable (primary) and stationary."""
    return _wire_numeric_target(
        mock_game,
        tactician,
        mobility=0.05,
        health=8000.0,  # clearly past the hardness_step (5000) "hard" threshold
        shield_level=0.0,
        primary=True,
    )


def test_select_bomb_for_hard_stationary_primary_target(mock_game):
    """
    A tough, valuable (primary), stationary target is bombed, with any bomb in
    the loadout (selected or not), even with missiles on board.
    """
    tactician = make_fighter_tactician(mock_game)
    bomb = _launcher("bomb", stock=6)
    _arm(tactician, _launcher("missile"), bomb)
    _wire_hard_stationary_primary(mock_game, tactician)

    plan = tactician._plan_attack(target_id="t")

    assert plan == {"attack_mode": AttackMode.BOMB, "weapon": "bomb", "launcher": bomb}


def test_select_strafe_not_bomb_for_soft_target(mock_game):
    """
    A soft target is not worth a bomb even if stationary: guns, and (being slow)
    a STRAFE run.
    """
    tactician = make_fighter_tactician(mock_game)
    _arm(tactician, _launcher("bomb", stock=6))
    _wire_numeric_target(
        mock_game,
        tactician,
        mobility=0.05,
        health=100.0,
        shield_level=0.0,
    )

    plan = tactician._plan_attack(target_id="t")

    assert plan == {
        "attack_mode": AttackMode.STRAFE,
        "weapon": "guns",
        "launcher": None,
    }


@pytest.mark.parametrize(
    "launchers",
    [[], [_launcher("bomb", stock=0)]],
    ids=["no_bomb", "bombs_spent"],
)
def test_select_no_bomb_without_supply(mock_game, launchers):
    """
    With no bombs (left), even the ideal bomb target falls to guns (STRAFE).
    """
    tactician = make_fighter_tactician(mock_game)
    _arm(tactician, *launchers)
    _wire_hard_stationary_primary(mock_game, tactician)

    plan = tactician._plan_attack(target_id="t")

    assert plan == {
        "attack_mode": AttackMode.STRAFE,
        "weapon": "guns",
        "launcher": None,
    }


def test_choose_weapon_falls_back_to_guns_on_non_numeric(mock_game):
    """
    A mocked/non-numeric target must not crash the scoring; it falls back to guns.
    """
    tactician = make_fighter_tactician(mock_game)
    _arm(tactician, _launcher("bomb"))
    target = MagicMock()  # mobility/health/shield_level are MagicMocks

    assert tactician._choose_weapon(target) == ("guns", None)


def _prey(mobility: float, health: float = 0.0) -> SimpleNamespace:
    """A prey of that mobility and health (unshielded), its id "t"."""
    return SimpleNamespace(id="t", mobility=mobility, health=health, shield_level=0.0)


# Tough enough for heavy ordnance (well past the hardness_step), or soft
TOUGH_HEALTH = 20000.0
SOFT_HEALTH = 100.0


def test_concussion_missiles_only_for_primary_agile_targets(mock_game):
    """
    Concussion missiles are kept for primary targets: another fighter gets the
    guns.
    """
    tactician = make_fighter_tactician(mock_game)
    missile = _launcher("missile", target_mobility="agile")
    _arm(tactician, missile)
    target = _prey(mobility=1.0)

    assert tactician._choose_weapon(target) == ("guns", None)
    tactician.primary_target_ids = ["t"]
    assert tactician._choose_weapon(target) == ("missile", missile)


@pytest.mark.parametrize(
    "primary, health, expected",
    [
        (True, TOUGH_HEALTH, "torpedo"),
        # Not worth a torpedo: soft, or not a primary target
        (True, SOFT_HEALTH, "rocket"),
        (False, TOUGH_HEALTH, "rocket"),
    ],
)
def test_torpedoes_only_for_tough_primary_targets(mock_game, primary, health, expected):
    """
    Torpedoes are heavy ordnance kept for tough primary targets; rockets go at
    any slow target.
    """
    tactician = make_fighter_tactician(mock_game)
    launchers = {
        "torpedo": _launcher("missile", target_mobility="slow"),
        "rocket": _launcher("rocket", target_mobility="slow"),
    }
    _arm(tactician, *launchers.values())
    tactician.primary_target_ids = ["t"] if primary else []
    target = _prey(mobility=0.0, health=health)

    category = "missile" if expected == "torpedo" else "rocket"
    assert tactician._choose_weapon(target) == (category, launchers[expected])


@pytest.mark.parametrize(
    "prefer_torpedoes, expected", [(True, "torpedo"), (False, "bomb")]
)
def test_torpedo_or_bomb_first_by_personality(mock_game, prefer_torpedoes, expected):
    """
    Against a tough slow primary target, the personality picks which heavy
    ordnance comes first; once it is spent, the other one is used.
    """
    personality = copy.deepcopy(Personality.FIGHTER_DEFAULT)
    personality["tactician"]["prefer_torpedoes_to_bombs"] = prefer_torpedoes
    tactician = make_fighter_tactician(mock_game)
    tactician.personality = personality
    launchers = {
        "bomb": _launcher("bomb", stock=6),
        "torpedo": _launcher("missile", stock=4, target_mobility="slow"),
    }
    _arm(tactician, *launchers.values())
    tactician.primary_target_ids = ["t"]
    target = _prey(mobility=0.0, health=TOUGH_HEALTH)
    categories = {"bomb": "bomb", "torpedo": "missile"}
    other = "bomb" if expected == "torpedo" else "torpedo"

    assert tactician._choose_weapon(target) == (
        categories[expected],
        launchers[expected],
    )
    launchers[expected].stock = 0
    assert tactician._choose_weapon(target) == (categories[other], launchers[other])


def test_soft_slow_target_without_rockets_gets_the_guns(mock_game):
    """
    A soft primary target is not worth a torpedo: without rockets, the guns.
    """
    tactician = make_fighter_tactician(mock_game)
    _arm(tactician, _launcher("missile", target_mobility="slow"))
    tactician.primary_target_ids = ["t"]

    assert tactician._choose_weapon(_prey(0.0, SOFT_HEALTH)) == ("guns", None)


@pytest.mark.parametrize(
    "launcher_mobility, target_mobility",
    [("slow", 1.0), ("agile", 0.0)],
    ids=["torpedo_at_a_fighter", "concussion_at_a_frigate"],
)
def test_no_ordnance_meant_for_another_mobility(
    mock_game, launcher_mobility, target_mobility
):
    """
    Torpedoes and rockets are never fired at an agile target, nor concussion
    missiles at a slow one: the guns are used instead.
    """
    tactician = make_fighter_tactician(mock_game)
    _arm(
        tactician,
        _launcher("missile", target_mobility=launcher_mobility),
        _launcher("rocket", target_mobility=launcher_mobility),
    )
    tactician.primary_target_ids = ["t"]
    target = _prey(mobility=target_mobility, health=TOUGH_HEALTH)

    assert tactician._choose_weapon(target) == ("guns", None)


def test_rockets_once_the_torpedoes_are_spent(mock_game):
    """
    Against a tough slow primary target, torpedoes come first; spent, rockets
    take over, then the guns.
    """
    tactician = make_fighter_tactician(mock_game)
    missile = _launcher("missile", stock=1, target_mobility="slow")
    rocket = _launcher("rocket", stock=1, target_mobility="slow")
    _arm(tactician, missile, rocket)
    tactician.primary_target_ids = ["t"]
    target = _prey(mobility=0.0, health=TOUGH_HEALTH)

    assert tactician._choose_weapon(target) == ("missile", missile)
    missile.stock = 0
    assert tactician._choose_weapon(target) == ("rocket", rocket)
    rocket.stock = 0
    assert tactician._choose_weapon(target) == ("guns", None)


def test_plan_attack_with_a_missile_keeps_the_geometry(mock_game):
    """
    The weapon does not change the attack geometry: an agile primary target is
    chased with missiles.
    """
    tactician = make_fighter_tactician(mock_game)
    missile = _launcher("missile")
    _arm(tactician, missile)
    _wire_numeric_target(
        mock_game, tactician, mobility=1.0, health=100.0, shield_level=0.0, primary=True
    )

    plan = tactician._plan_attack(target_id="t")

    assert plan == {
        "attack_mode": AttackMode.PURSUIT,
        "weapon": "missile",
        "launcher": missile,
    }


# ---------------------------------------------------------------------------
# update_intent — formation vs. patrol
# ---------------------------------------------------------------------------


def test_update_intent_wingman_with_waypoints_holds_formation(mock_game):
    """
    With no threat nor prey, a wingman carrying the wave's route holds
    formation; once the leader is gone, it takes the lead and patrols.
    """
    # Healthy enough not to disengage
    tactician = make_fighter_tactician(mock_game, health=100.0, shield=100.0)
    tactician.evaluate_threats = MagicMock(return_value={"score": 0})
    tactician.evaluate_preys = MagicMock(return_value={"score": 0})
    tactician.pawn.id = uuid.uuid4()
    tactician.pawn.parent.navigator.waypoints = [np.array([0.0, 1000.0, 0.0])]
    leader = MagicMock()
    leader.id = uuid.uuid4()
    formation = Formation()
    formation.add_ship(leader)
    formation.add_ship(tactician.pawn)

    intent, target_dict = tactician.update_intent()

    assert intent == Intent.FORMATION
    assert target_dict["target_id"] == leader.id

    formation.remove_ship(leader.id)
    intent, _ = tactician.update_intent()

    assert intent == Intent.PATROL
