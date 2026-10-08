"""
Unit tests for Bot (space_flight.actors.bot).

Bot.__init__ instantiates Panda3D-backed pawns and AI components, so every
test that exercises post-construction logic uses object.__new__() with
manually-set MagicMock attributes.  This keeps the suite fully headless.
"""

import math
from unittest.mock import MagicMock

import numpy as np
import pytest

from space_flight.actors.bot import Bot
from space_flight.ai.think_scheduler import ThinkScheduler
from space_flight.utils.state_machine import DyingPhase


def make_bot_without_init(bot_type: str = "fighter") -> Bot:
    """
    Build a Bot that bypasses __init__, with MagicMock pawn/AI/game and a real
    dying phase and think slot.

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
    bot.game.game_time.get_current_time.return_value = 0.0
    bot.game.game_time.get_time_step.return_value = 1.0 / 60.0
    bot.tasks = []
    # A live bot is not mid-death: move_bot_task checks is_dying (a property over
    # the composed DyingPhase) to switch from AI control to the death tumble.
    bot._dying = DyingPhase(clock=lambda: 0.0)
    # Scheduled like a freshly spawned bot: it thinks on its first frame
    bot._think_slot = ThinkScheduler().register(period_s=0.1)
    bot._next_think_s = -math.inf
    bot._commands = None
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
# set_team
# ---------------------------


def test_set_team_reassigns_bot_and_pawn():
    """
    A lone fighter's team is read live every frame, so reassigning bot.team
    and bot.pawn.team is enough for it.
    """
    bot = make_bot_without_init()
    bot.pawn.sub_systems = []
    bot.pawn.shield = None
    bot.pawn.mounted_bots = []

    bot.set_team(9)

    assert bot.team == 9
    assert bot.pawn.team == 9


def test_set_team_cascades_to_capital_ship_dependents():
    """
    A capital ship's dependents cache team at construction time and never
    re-read it: each sub_system (including shield generators), the shared
    shield, and each mounted bot (turret / tractor beam -- itself a Bot with
    its own pawn.team) must all be walked.
    """
    turret = make_bot_without_init(bot_type="turret")
    turret.pawn.sub_systems = []
    turret.pawn.shield = None
    turret.pawn.mounted_bots = []

    sub_system = MagicMock(team=2)
    shield = MagicMock(team=2)
    frigate = make_bot_without_init(bot_type="capital_ship")
    frigate.pawn.sub_systems = [sub_system]
    frigate.pawn.shield = shield
    frigate.pawn.mounted_bots = [turret]

    frigate.set_team(5)

    assert frigate.team == 5
    assert frigate.pawn.team == 5
    assert sub_system.team == 5
    assert shield.team == 5
    assert turret.team == 5
    assert turret.pawn.team == 5


# ---------------------------
# begin_death
# ---------------------------


def test_begin_death_removes_pawn_as_players_target():
    """
    begin_death() asks the player to drop this bot's pawn as its current
    target, so a dying wreck can't stay locked on.
    """
    bot = make_bot_without_init()

    bot.begin_death()

    bot.game.player.remove_target.assert_called_once_with(target_to_remove=bot.pawn)


def test_begin_death_tolerates_missing_player():
    """
    begin_death() must not raise if game.player is None (or otherwise has no
    remove_target), e.g. during level cleanup.
    """
    bot = make_bot_without_init()
    bot.game.player = None

    bot.begin_death()  # must not raise


# ---------------------------
# play_death
# ---------------------------


def test_play_death_calls_fire_smoke_pool_burst():
    """
    play_death() calls game.fire_smoke_pool.burst exactly once.
    """
    bot = make_bot_without_init()
    bot.pawn.position = np.array([10.0, 20.0, 30.0])
    bot.pawn.speed = np.array([1.0, 0.0, 0.0])
    bot.pawn.explosion_scale = 2.0

    bot.play_death()

    bot.game.fire_smoke_pool.burst.assert_called_once()


def test_play_death_passes_pawn_position_to_explosion():
    """
    play_death() forwards the pawn's current position to the burst.
    """
    bot = make_bot_without_init()
    position = np.array([5.0, 10.0, -3.0])
    bot.pawn.position = position
    bot.pawn.speed = np.zeros(3)
    bot.pawn.explosion_scale = 1.0

    bot.play_death()

    burst_kwargs = bot.game.fire_smoke_pool.burst.call_args.kwargs
    np.testing.assert_array_equal(burst_kwargs["position"], position)


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

    burst_kwargs = bot.game.fire_smoke_pool.burst.call_args.kwargs
    np.testing.assert_array_equal(burst_kwargs["base_velocity"], speed)


def test_play_death_passes_pawn_explosion_scale():
    """
    play_death() forwards the pawn's explosion_scale.
    """
    bot = make_bot_without_init()
    bot.pawn.position = np.zeros(3)
    bot.pawn.speed = np.zeros(3)
    bot.pawn.explosion_scale = 3.5

    bot.play_death()

    burst_kwargs = bot.game.fire_smoke_pool.burst.call_args.kwargs
    assert burst_kwargs["scale"] == pytest.approx(3.5)


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


def test_move_bot_task_passes_the_navigator_speed_floor_to_the_pilot():
    """
    The navigator's speed floor of the think reaches the pilot, for its energy
    protection.
    """
    bot = make_bot_without_init(bot_type="fighter")
    bot.tactician.think.return_value = ("attack", {})
    bot.navigator.navigate.return_value = (np.array([1.0, 0.0, 0.0]), 100.0)
    bot.navigator.minimum_speed_mps = 112.5
    bot.pilot.pilot.return_value = (0.8, 0.1, -0.1, 0.0)

    bot.move_bot_task()

    assert bot.pilot.pilot.call_args.kwargs["minimum_speed_mps"] == 112.5


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


def test_clean_removes_pawn_as_players_target():
    """
    clean() asks the player to drop this bot's pawn as its current target.
    """
    bot = make_bot_without_init()
    pawn = bot.pawn
    player = bot.game.player

    bot.clean()

    player.remove_target.assert_called_once_with(target_to_remove=pawn)


def test_clean_tolerates_missing_player():
    """
    clean() must not raise if game.player is None, e.g. during level cleanup.
    """
    bot = make_bot_without_init()
    bot.game.player = None

    bot.clean()  # must not raise


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


# ---------------------------
# move_bot_task – think scheduling
# ---------------------------


def _run_frames(bot, n_frames):
    """Step move_bot_task over n_frames of a 60 Hz game clock."""
    clock = {"now_s": 0.0}
    bot.game.game_time.get_current_time.side_effect = lambda: clock["now_s"]
    for _ in range(n_frames):
        bot.move_bot_task()
        clock["now_s"] += 1.0 / 60.0


def test_fighter_thinks_once_per_pilot_period_and_moves_every_frame():
    """
    With a 0.1 s pilot period, the fighter navigates and pilots every 6th
    frame, keeps flying the last commands in between, and lets the navigator
    take its weapon decisions on the other frames.
    """
    bot = make_bot_without_init(bot_type="fighter")
    bot.tactician.think.return_value = ("engage", {})
    bot.navigator.navigate.return_value = (np.array([1.0, 0.0, 0.0]), 100.0)
    bot.pilot.pilot.return_value = (0.8, 0.1, -0.1, 0.0)

    _run_frames(bot, 12)

    assert bot.tactician.think.call_count == 12
    assert bot.navigator.navigate.call_count == 2
    assert bot.pilot.pilot.call_count == 2
    assert bot.navigator.update_triggers.call_count == 10
    assert bot.pawn.move.call_count == 12
    bot.pawn.move.assert_called_with(
        throttle=0.8, yaw_rate=0.1, pitch_rate=-0.1, roll_rate=0.0
    )


def test_turret_navigates_every_frame_but_pilots_once_per_period():
    """
    A mount's navigator publishes the firing solution checked every frame, so
    it keeps running every frame; only the pilot follows the schedule.
    """
    bot = make_bot_without_init(bot_type="turret")
    bot.tactician.think.return_value = ("track", {})
    bot.navigator.navigate.return_value = np.array([0.0, 1.0, 0.0])
    bot.pilot.pilot.return_value = (0.3, -0.2)

    _run_frames(bot, 12)

    assert bot.navigator.navigate.call_count == 12
    assert bot.pilot.pilot.call_count == 2
    assert bot.pawn.move.call_count == 12


@pytest.mark.parametrize("end_of_life", ["begin_death", "clean"])
def test_dying_or_cleaned_bot_gives_its_think_slot_back(end_of_life):
    bot = make_bot_without_init()
    scheduler = bot._think_slot.scheduler
    assert scheduler.load.sum() == 1

    getattr(bot, end_of_life)()
    # Releasing again (e.g. cleanup after death) must not free it twice
    bot._release_think_slot()

    assert scheduler.load.sum() == 0


class _FakeSensor:
    """Records the collision sensor's on/off state, like CollisionSensor.set_active."""

    def __init__(self):
        self.active = True

    def set_active(self, active):
        self.active = active


def test_sensor_is_on_only_for_the_traversal_of_each_think_frame():
    """
    The traversal runs before the bots update: the sensor is switched on at the
    end of the frame before each think, and off again after the think.
    """
    bot = make_bot_without_init(bot_type="fighter")
    bot.tactician.think.return_value = ("engage", {})
    bot.navigator.navigate.return_value = (np.array([1.0, 0.0, 0.0]), 100.0)
    bot.pilot.pilot.return_value = (0.8, 0.1, -0.1, 0.0)
    sensor = bot.navigator.collision_sensor = _FakeSensor()
    clock = {"now_s": 0.0}
    bot.game.game_time.get_current_time.side_effect = lambda: clock["now_s"]

    traversed_with_sensor, think_frames = [], []
    for frame in range(13):
        traversed_with_sensor.append(sensor.active)  # state during this traversal
        calls = bot.navigator.navigate.call_count
        bot.move_bot_task()
        if bot.navigator.navigate.call_count > calls:
            think_frames.append(frame)
        clock["now_s"] += 1.0 / 60.0

    assert think_frames == [0, 6, 12]
    assert [f for f, on in enumerate(traversed_with_sensor) if on] == think_frames


def test_think_waits_a_frame_when_the_sensor_missed_the_traversal():
    """
    If a frame comes later than expected, the bot can be due to think while its
    sensor sat out that frame's traversal: it turns the sensor on and thinks on
    the next frame, so it never thinks without this frame's contacts.
    """
    bot = make_bot_without_init(bot_type="fighter")
    bot.tactician.think.return_value = ("engage", {})
    bot.navigator.navigate.return_value = (np.array([1.0, 0.0, 0.0]), 100.0)
    bot.pilot.pilot.return_value = (0.8, 0.1, -0.1, 0.0)
    bot._commands = (0.0, 0.0, 0.0, 0.0)  # it already thought before
    bot._next_think_s = 0.0
    sensor = bot.navigator.collision_sensor = _FakeSensor()
    sensor.active = False

    bot.move_bot_task()  # due, but no contacts this frame
    bot.navigator.navigate.assert_not_called()
    assert sensor.active

    bot.game.game_time.get_current_time.return_value = 1.0 / 60.0
    bot.move_bot_task()
    bot.navigator.navigate.assert_called_once()
