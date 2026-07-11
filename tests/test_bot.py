"""
Unit tests for Bot (space_flight.actors.bot).

Bot.__init__ instantiates Panda3D-backed pawns and AI components, so every
test that exercises post-construction logic uses object.__new__() with
manually-set MagicMock attributes.  This keeps the suite fully headless.
"""

from unittest.mock import MagicMock

import numpy as np
import pytest

from space_flight.actors.bot import Bot


def make_bot_without_init(bot_type: str = "fighter") -> Bot:
    """
    Build a Bot that bypasses __init__ and has all lifecycle attributes
    pre-populated with MagicMocks.

    :param bot_type: the bot_type string stored on the instance
    :return: a Bot whose methods can be tested in isolation
    """
    bot = object.__new__(Bot)
    bot.name = "test_bot"
    bot.bot_type = bot_type
    bot.record = False
    bot.pawn = MagicMock()
    bot.pilot = MagicMock()
    bot.navigator = MagicMock()
    bot.tactician = MagicMock()
    bot.game = MagicMock()
    bot.tasks = []
    return bot


# ---------------------------
# get_health
# ---------------------------


def test_get_health_returns_pawn_health():
    """
    get_health() delegates directly to the pawn's health attribute.
    """
    bot = make_bot_without_init()
    bot.pawn.health = 85.0

    result = bot.get_health()

    assert result == pytest.approx(85.0)


def test_get_health_reflects_updated_pawn_health():
    """
    get_health() returns the current pawn health even after it has changed.
    """
    bot = make_bot_without_init()
    bot.pawn.health = 100.0
    bot.pawn.health = 40.0

    assert bot.get_health() == pytest.approx(40.0)


def test_get_health_returns_zero_when_pawn_health_is_zero():
    """
    get_health() returns zero for a destroyed pawn.
    """
    bot = make_bot_without_init()
    bot.pawn.health = 0.0

    assert bot.get_health() == pytest.approx(0.0)


# ---------------------------
# set_personality
# ---------------------------


def test_set_personality_propagates_to_pilot(mock_personality=None):
    """
    set_personality() assigns the given personality dict to the pilot.
    """
    bot = make_bot_without_init()
    personality = {"aggression": 0.8, "caution": 0.2}

    bot.set_personality(personality)

    assert bot.pilot.personality == personality


def test_set_personality_propagates_to_navigator():
    """
    set_personality() assigns the given personality dict to the navigator.
    """
    bot = make_bot_without_init()
    personality = {"aggression": 0.5}

    bot.set_personality(personality)

    assert bot.navigator.personality == personality


def test_set_personality_propagates_to_tactician():
    """
    set_personality() assigns the given personality dict to the tactician.
    """
    bot = make_bot_without_init()
    personality = {"caution": 1.0}

    bot.set_personality(personality)

    assert bot.tactician.personality == personality


def test_set_personality_propagates_same_object_to_all_three():
    """
    All three AI components receive the exact same personality object (not
    independent copies).
    """
    bot = make_bot_without_init()
    personality = {"aggression": 0.3}

    bot.set_personality(personality)

    assert bot.pilot.personality is personality
    assert bot.navigator.personality is personality
    assert bot.tactician.personality is personality


# ---------------------------
# play_death
# ---------------------------


def test_play_death_calls_explosion_fx_pool_spawn():
    """
    play_death() calls game.explosion_fx_pool.spawn exactly once.
    """
    bot = make_bot_without_init()
    bot.pawn.position = np.array([10.0, 20.0, 30.0])
    bot.pawn.speed = np.array([1.0, 0.0, 0.0])
    bot.pawn.explosion_scale = 2.0

    bot.play_death()

    bot.game.explosion_fx_pool.spawn.assert_called_once()


def test_play_death_passes_pawn_position_to_explosion():
    """
    play_death() forwards the pawn's current position to the explosion spawner.
    """
    bot = make_bot_without_init()
    position = np.array([5.0, 10.0, -3.0])
    bot.pawn.position = position
    bot.pawn.speed = np.zeros(3)
    bot.pawn.explosion_scale = 1.0

    bot.play_death()

    spawn_kwargs = bot.game.explosion_fx_pool.spawn.call_args.kwargs
    np.testing.assert_array_equal(spawn_kwargs["position"], position)


def test_play_death_passes_pawn_speed_as_base_velocity():
    """
    play_death() forwards the pawn's current speed as base_velocity.
    """
    bot = make_bot_without_init()
    speed = np.array([3.0, -1.0, 0.5])
    bot.pawn.position = np.zeros(3)
    bot.pawn.speed = speed
    bot.pawn.explosion_scale = 1.0

    bot.play_death()

    spawn_kwargs = bot.game.explosion_fx_pool.spawn.call_args.kwargs
    np.testing.assert_array_equal(spawn_kwargs["base_velocity"], speed)


def test_play_death_passes_pawn_explosion_scale():
    """
    play_death() forwards the pawn's explosion_scale.
    """
    bot = make_bot_without_init()
    bot.pawn.position = np.zeros(3)
    bot.pawn.speed = np.zeros(3)
    bot.pawn.explosion_scale = 3.5

    bot.play_death()

    spawn_kwargs = bot.game.explosion_fx_pool.spawn.call_args.kwargs
    assert spawn_kwargs["scale"] == pytest.approx(3.5)


# ---------------------------
# move_bot_task – routing
# ---------------------------


def test_move_bot_task_raises_for_unknown_bot_type():
    """
    move_bot_task() raises NotImplementedError for any bot_type not handled
    by the dispatch logic.
    """
    bot = make_bot_without_init(bot_type="drone")

    with pytest.raises(NotImplementedError):
        bot.move_bot_task()


def test_move_bot_task_calls_pawn_move_for_fighter():
    """
    move_bot_task() calls pawn.move() for a fighter bot after gathering
    intent and direction from the AI stack.
    """
    bot = make_bot_without_init(bot_type="fighter")
    bot.tactician.think.return_value = ("attack", {})
    bot.navigator.navigate.return_value = (np.array([1.0, 0.0, 0.0]), 100.0)
    bot.pilot.pilot.return_value = (0.8, 0.1, -0.1, 0.0)

    bot.move_bot_task()

    bot.pawn.move.assert_called_once_with(
        throttle=0.8, yaw_rate=0.1, pitch_rate=-0.1, roll_rate=0.0
    )


def test_move_bot_task_calls_pawn_move_for_turret():
    """
    move_bot_task() calls pawn.move() for a turret bot with only yaw/pitch
    arguments.
    """
    bot = make_bot_without_init(bot_type="turret")
    bot.tactician.think.return_value = ("track", {})
    bot.navigator.navigate.return_value = np.array([0.0, 1.0, 0.0])
    bot.pilot.pilot.return_value = (0.3, -0.2)

    bot.move_bot_task()

    bot.pawn.move.assert_called_once_with(yaw_rate=0.3, pitch_rate=-0.2)


def test_move_bot_task_calls_pawn_move_for_capital_ship():
    """
    move_bot_task() uses the same fighter code-path for capital_ship bots.
    """
    bot = make_bot_without_init(bot_type="capital_ship")
    bot.tactician.think.return_value = ("patrol", {})
    bot.navigator.navigate.return_value = (np.array([0.0, 1.0, 0.0]), 50.0)
    bot.pilot.pilot.return_value = (0.5, 0.0, 0.0, 0.0)

    bot.move_bot_task()

    bot.pawn.move.assert_called_once()


# ---------------------------
# clean
# ---------------------------


def test_clean_calls_pilot_clean():
    """
    clean() calls clean() on the pilot AI component.
    """
    bot = make_bot_without_init()
    pilot = bot.pilot

    bot.clean()

    pilot.clean.assert_called_once()


def test_clean_calls_navigator_clean():
    """
    clean() calls clean() on the navigator AI component.
    """
    bot = make_bot_without_init()
    navigator = bot.navigator

    bot.clean()

    navigator.clean.assert_called_once()


def test_clean_calls_tactician_clean():
    """
    clean() calls clean() on the tactician AI component.
    """
    bot = make_bot_without_init()
    tactician = bot.tactician

    bot.clean()

    tactician.clean.assert_called_once()


def test_clean_calls_pawn_clean():
    """
    clean() calls clean() on the pawn.
    """
    bot = make_bot_without_init()
    pawn = bot.pawn

    bot.clean()

    pawn.clean.assert_called_once()


def test_clean_sets_pilot_to_none():
    """
    clean() sets pilot to None to release the reference.
    """
    bot = make_bot_without_init()

    bot.clean()

    assert bot.pilot is None


def test_clean_sets_navigator_to_none():
    """
    clean() sets navigator to None to release the reference.
    """
    bot = make_bot_without_init()

    bot.clean()

    assert bot.navigator is None


def test_clean_sets_tactician_to_none():
    """
    clean() sets tactician to None to release the reference.
    """
    bot = make_bot_without_init()

    bot.clean()

    assert bot.tactician is None


def test_clean_sets_pawn_to_none():
    """
    clean() sets pawn to None to release the reference.
    """
    bot = make_bot_without_init()

    bot.clean()

    assert bot.pawn is None
