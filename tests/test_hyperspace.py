"""
Tests for hyperspace transits (:mod:`space_flight.actors.hyperspace`): the
motion profile, the transit controller, the ship's pinned step, and how
transiting actors are kept out of interactions, targeting and collisions.
"""

import math
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest
from mission_fakes import FakeGame, depart_all, patch_engine
from panda3d.core import BitMask32, CollisionNode, CollisionSphere, NodePath

from space_flight.actors.bot import Bot
from space_flight.actors.destructibles import Destructible, Destructibles
from space_flight.actors.hyperspace import (
    ARRIVAL_STAGGER_S,
    JUMP_SPOOL_S,
    TRANSIT_DISTANCE_M,
    TRANSIT_DURATION_S,
    HyperspaceTransit,
    transit_offset_fraction,
)
from space_flight.actors.player import Player
from space_flight.actors.ship import Ship
from space_flight.ai.interactions import Interactions
from space_flight.game.collisions import CollisionLayers
from space_flight.game.scenario import Mission, WaveSpec
from space_flight.utils.state_machine import DyingPhase

# ---------------------------------------------------------------------------
# Motion profile
# ---------------------------------------------------------------------------


def test_arrival_starts_far_and_ends_exactly_on_the_pose():
    assert transit_offset_fraction(0.0, arriving=True) == pytest.approx(1.0)
    assert transit_offset_fraction(1.0, arriving=True) == pytest.approx(0.0)


def test_arrival_covers_most_of_the_distance_early():
    """Very fast at first, then a sudden stop."""
    fractions = [
        transit_offset_fraction(u, arriving=True) for u in np.linspace(0, 1, 21)
    ]
    assert all(a > b for a, b in zip(fractions, fractions[1:]))
    assert transit_offset_fraction(0.25, arriving=True) < 0.25


def test_departure_is_the_arrival_played_backwards():
    for u in np.linspace(0, 1, 11):
        assert transit_offset_fraction(u, arriving=False) == pytest.approx(
            transit_offset_fraction(1.0 - u, arriving=True)
        )
    # Eases out, then streaks away
    assert transit_offset_fraction(0.75, arriving=False) < 0.25
    assert transit_offset_fraction(0.0, arriving=False) == pytest.approx(0.0)
    assert transit_offset_fraction(1.0, arriving=False) == pytest.approx(1.0)


@pytest.mark.parametrize("speed_fraction", [0.0, 0.01, 0.2])
def test_arrival_lands_at_the_ship_speed(speed_fraction):
    """The final slope is the ship's own speed (in transit distance per
    transit duration), whatever the sharpness."""
    h = 1e-6
    for sharpness in (6.0, 10.0):
        end = transit_offset_fraction(1.0, True, speed_fraction, sharpness)
        before = transit_offset_fraction(1.0 - h, True, speed_fraction, sharpness)
        assert end == pytest.approx(0.0, abs=1e-12)
        assert (end - before) / h == pytest.approx(-speed_fraction, abs=1e-4)
        assert transit_offset_fraction(
            0.0, True, speed_fraction, sharpness
        ) == pytest.approx(1.0)


def test_arrival_with_speed_still_decreases_monotonically():
    fractions = [
        transit_offset_fraction(u, arriving=True, speed_fraction=0.05)
        for u in np.linspace(0, 1, 101)
    ]
    assert all(a > b for a, b in zip(fractions, fractions[1:]))


def test_progress_is_clamped():
    assert transit_offset_fraction(-1.0, arriving=True) == pytest.approx(1.0)
    assert transit_offset_fraction(2.0, arriving=True) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Transit controller
# ---------------------------------------------------------------------------


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _collider(parent: NodePath, from_mask: BitMask32, into_mask: BitMask32):
    node = CollisionNode("collider")
    node.addSolid(CollisionSphere(0, 0, 0, 1))
    node.setFromCollideMask(from_mask)
    node.setIntoCollideMask(into_mask)
    return parent.attachNewNode(node)


def make_transiting_ship():
    """A ship stand-in with a real node carrying a hull and a subsystem collider."""
    root = NodePath("root")
    ship = SimpleNamespace(
        node=root.attachNewNode("ship_node"),
        position=np.array([10.0, 20.0, 30.0]),
        orientation=np.array([1.0, 0.0, 0.0, 0.0]),
        speed=np.array([0.0, 50.0, 0.0]),
        in_hyperspace=False,
        held=[],
    )
    ship.hold_step = lambda **kwargs: ship.held.append(kwargs)
    hull = _collider(
        ship.node, CollisionLayers.DESTRUCTIBLE_FROM, CollisionLayers.DESTRUCTIBLE_INTO
    )
    subsystem = _collider(
        ship.node.attachNewNode("subsystem_node"),
        CollisionLayers.SUBSYSTEM_FROM,
        CollisionLayers.SUBSYSTEM_INTO,
    )
    return ship, hull, subsystem


def make_transit(ship, clock, delay_s=0.0, arriving=True):
    return HyperspaceTransit(
        ship=ship,
        arriving=arriving,
        distance_m=1000.0,
        duration_s=0.5,
        clock=clock,
        delay_s=delay_s,
    )


def test_transit_mutes_every_collider_and_restores_them():
    ship, hull, subsystem = make_transiting_ship()
    transit = make_transit(ship, FakeClock())

    transit.begin()
    assert ship.in_hyperspace
    for collider in (hull, subsystem):
        assert collider.node().getFromCollideMask() == BitMask32.allOff()
        assert collider.node().getIntoCollideMask() == BitMask32.allOff()

    transit.end()
    assert not ship.in_hyperspace
    assert hull.node().getFromCollideMask() == CollisionLayers.DESTRUCTIBLE_FROM
    assert hull.node().getIntoCollideMask() == CollisionLayers.DESTRUCTIBLE_INTO
    assert subsystem.node().getIntoCollideMask() == CollisionLayers.SUBSYSTEM_INTO


def test_arrival_rushes_in_from_behind_and_stops_on_the_pose():
    ship, _, _ = make_transiting_ship()
    clock = FakeClock()
    transit = make_transit(ship, clock)
    transit.begin()

    offsets = []
    finished = False
    while not finished:
        finished = transit.step()
        offsets.append(ship.held[-1]["offset_m"])
        clock.t += 1 / 60

    assert offsets[0] == pytest.approx(-1000.0)
    assert offsets[-1] == pytest.approx(0.0)
    assert all(a <= b for a, b in zip(offsets, offsets[1:]))
    # The ship lands at its spawn speed (50 m/s here)...
    dt = 1e-4
    clock.t = 0.5 - dt
    transit.step()
    before = ship.held[-1]["offset_m"]
    clock.t = 0.5
    transit.step()
    assert (ship.held[-1]["offset_m"] - before) / dt == pytest.approx(50.0, rel=0.01)
    # ...held at its spawn pose and velocity throughout
    for held in ship.held:
        np.testing.assert_array_equal(held["position"], [10.0, 20.0, 30.0])
        np.testing.assert_array_equal(held["orientation"], [1.0, 0.0, 0.0, 0.0])
        np.testing.assert_array_equal(held["speed"], [0.0, 50.0, 0.0])


def test_departure_streaks_away_ahead():
    ship, _, _ = make_transiting_ship()
    clock = FakeClock()
    transit = make_transit(ship, clock, arriving=False)
    transit.begin()

    transit.step()
    assert ship.held[-1]["offset_m"] == pytest.approx(0.0)
    clock.t = 0.5
    assert transit.step()
    assert ship.held[-1]["offset_m"] == pytest.approx(1000.0)


def test_a_delayed_arrival_waits_hidden_and_held_far_behind():
    ship, _, _ = make_transiting_ship()
    clock = FakeClock()
    transit = make_transit(ship, clock, delay_s=0.2)
    transit.begin()

    assert ship.node.isHidden()
    assert not transit.step()
    assert ship.held[-1]["offset_m"] == pytest.approx(-1000.0)
    assert ship.node.isHidden()

    clock.t = 0.2
    transit.step()
    assert not ship.node.isHidden()
    clock.t = 0.75
    assert transit.step()


# ---------------------------------------------------------------------------
# Ship.hold_step
# ---------------------------------------------------------------------------


class ConcreteShip(Ship):
    def apply_damage(self, damage, damage_type):
        pass

    def ship_handle_health(self):
        pass


def make_ship_for_hold_step():
    ship = object.__new__(ConcreteShip)
    ship.node = NodePath("ship_node")
    ship.state = np.zeros(10)
    ship.state_dot = np.ones(10)
    ship.state_dot_previous = np.ones(10)
    ship.speed = np.array([50.0, 0.0, 0.0])
    ship.pqr = np.ones(3)
    ship.scalar_thrust_n = 1000.0
    ship.mass_kg = 2.0
    # e.g. gravity: the held ship must not drift under it
    ship.additional_force_n = np.array([0.0, 0.0, -20.0])
    ship.impact_force_n = np.zeros(3)
    ship.external_force_n = np.zeros(3)
    ship.position_correction = np.ones(3)
    ship.velocity_correction = np.ones(3)
    ship.drag_factor = 0.0
    ship.lift_factor = 0.0
    ship.lateral_lift_factor = 0.0
    ship.lift_inefficiency = 0.0
    ship.max_thrust_n = 1000.0
    ship.game = SimpleNamespace(integrator=MagicMock())
    ship.game.integrator.set_state_variables.return_value = 7
    return ship


def test_hold_step_pins_the_state_still_and_offsets_the_node():
    ship = make_ship_for_hold_step()
    position = np.array([1.0, 2.0, 3.0])
    speed = np.array([0.0, 50.0, 0.0])

    ship.hold_step(
        position=position,
        orientation=np.array([1.0, 0.0, 0.0, 0.0]),
        speed=speed,
        offset_m=-100.0,
    )

    kwargs = ship.game.integrator.set_state_variables.call_args.kwargs
    np.testing.assert_array_equal(kwargs["partial_x"][:3], position)
    # It keeps its velocity, without moving: zero derivatives
    np.testing.assert_array_equal(kwargs["partial_x"][7:10], speed)
    np.testing.assert_array_equal(kwargs["partial_x_dot"], np.zeros(10))
    np.testing.assert_array_equal(kwargs["partial_x_dot_previous"], np.zeros(10))
    assert ship.integrator_idx == 7
    np.testing.assert_array_equal(ship.speed, speed)
    np.testing.assert_array_equal(ship.position_correction, np.zeros(3))
    # Forward is +Y for the identity orientation: drawn 100 m behind
    np.testing.assert_allclose(list(ship.node.getPos()), [1.0, -98.0, 3.0], atol=1e-4)


# ---------------------------------------------------------------------------
# Interactions and targeting
# ---------------------------------------------------------------------------


class Actor:
    def __init__(self, team, position, in_hyperspace=False):
        self.id = uuid.uuid4()
        self.team = team
        self.position = np.array(position, dtype=float)
        self.speed = np.zeros(3)
        self.forward = np.array([0.0, 1.0, 0.0])
        self.in_hyperspace = in_hyperspace


def test_an_actor_in_hyperspace_interacts_with_nobody():
    interactions = Interactions()
    friend = Actor(team=1, position=[0, 0, 0])
    foe = Actor(team=2, position=[0, 500, 0])
    dropping = Actor(team=2, position=[0, -500, 0], in_hyperspace=True)
    for actor in (friend, foe, dropping):
        interactions.add_actor(actor)

    interactions.update_interactions()

    idx = {
        a: interactions.get_actor_index_from_id(a.id) for a in (friend, foe, dropping)
    }
    assert interactions.interact[idx[friend], idx[foe]]
    assert not interactions.interact[idx[friend], idx[dropping]]
    assert not interactions.interact[idx[dropping], idx[friend]]


@pytest.mark.parametrize("target_filter", ["All", "Fighters", "Enemies"])
def test_the_player_cannot_target_an_actor_in_hyperspace(target_filter):
    player = object.__new__(Player)
    player.target_filter = target_filter
    game = MagicMock()
    game.interactions.alive = np.ones(3, dtype=bool)
    game.interactions.live_actors = [
        SimpleNamespace(category="fighter", in_hyperspace=False),  # the player
        SimpleNamespace(category="fighter", in_hyperspace=False),
        SimpleNamespace(category="fighter", in_hyperspace=True),
    ]
    game.interactions.interact = np.ones((3, 3), dtype=bool)
    player.game = game

    player.update_target_mask(player_actor_index=0)

    np.testing.assert_array_equal(player.target_mask, [0, 1, 0])


# ---------------------------------------------------------------------------
# Bot
# ---------------------------------------------------------------------------


def make_bot(bot_type="fighter"):
    bot = object.__new__(Bot)
    bot.name = "test_bot"
    bot.bot_type = bot_type
    bot.pawn = MagicMock()
    bot.tactician = MagicMock()
    bot.game = MagicMock()
    bot.game.game_time.get_current_time.return_value = 0.0
    bot._dying = DyingPhase(clock=lambda: 0.0)
    bot._next_think_s = 5.0
    bot.hyperspace_transit = None
    bot._jump_at_s = None
    bot.has_departed = False
    return bot


@pytest.mark.parametrize("bot_type", ["fighter", "major_ship"])
def test_begin_hyperspace_arrival_uses_the_bot_type_transit(bot_type, monkeypatch):
    created = []

    def fake_transit(**kwargs):
        transit = MagicMock()
        created.append((kwargs, transit))
        return transit

    monkeypatch.setattr("space_flight.actors.bot.HyperspaceTransit", fake_transit)
    bot = make_bot(bot_type)

    bot.begin_hyperspace_arrival(delay_s=0.1)

    kwargs, transit = created[0]
    assert kwargs["ship"] is bot.pawn
    assert kwargs["arriving"] is True
    assert kwargs["distance_m"] == TRANSIT_DISTANCE_M[bot_type]
    assert kwargs["duration_s"] == TRANSIT_DURATION_S[bot_type]
    assert kwargs["delay_s"] == 0.1
    transit.begin.assert_called_once()
    assert bot.hyperspace_transit is transit


def test_the_ai_waits_out_the_transit_then_thinks_at_once():
    bot = make_bot()
    bot.hyperspace_transit = transit = MagicMock()
    transit.step.return_value = False

    bot.move_bot_task()
    bot.tactician.think.assert_not_called()
    bot.pawn.move.assert_not_called()

    transit.step.return_value = True
    bot.move_bot_task()
    transit.end.assert_called_once()
    assert bot.hyperspace_transit is None
    assert bot._next_think_s == -math.inf


# ---------------------------------------------------------------------------
# Waves
# ---------------------------------------------------------------------------

WAVE = WaveSpec(name="wave", ship_model="tie-fighter", size=3, spawn_point=[0, 0, 0])


@pytest.fixture
def mission():
    return Mission(FakeGame())


@pytest.fixture
def spawned(monkeypatch):
    return patch_engine(monkeypatch)


def run_jobs(mission, n=100):
    for _ in range(n):
        if not mission.jobs:
            return
        mission.update()


def test_wave_ships_drop_in_by_default_with_a_stagger(mission, spawned):
    mission.spawn(WAVE)
    run_jobs(mission)

    for bot in spawned:
        assert len(bot.hyperspace_arrivals) == 1
        assert 0.0 <= bot.hyperspace_arrivals[0] <= ARRIVAL_STAGGER_S


def test_wave_ships_spawn_at_the_spawn_speed_along_their_heading(mission, monkeypatch):
    calls = []

    def fake_spawn_bot(game, **kwargs):
        calls.append(kwargs)
        bot = MagicMock()
        bot.pawn.id = uuid.uuid4()
        return bot

    monkeypatch.setattr("space_flight.game.scenario.wave.spawn_bot", fake_spawn_bot)
    # The default orientation: a 180 degree turn about z, facing -Y
    mission.spawn(WAVE)
    mission.spawn(WaveSpec(**{**WAVE.__dict__, "spawn_speed_mps": 120.0}))
    run_jobs(mission)

    # Both waves spawn concurrently: the first one's ships alternate with the
    # second one's
    for kwargs in calls[0::2]:
        np.testing.assert_allclose(kwargs["ini_speed"], [0.0, -50.0, 0.0], atol=1e-9)
    for kwargs in calls[1::2]:
        np.testing.assert_allclose(kwargs["ini_speed"], [0.0, -120.0, 0.0], atol=1e-9)


def test_a_wave_can_opt_out_of_the_drop(mission, spawned):
    mission.spawn(WaveSpec(**{**WAVE.__dict__, "hyperspace": False}))
    mission.spawn(WAVE, hyperspace=False)
    run_jobs(mission)

    assert len(spawned) == 6
    assert all(bot.hyperspace_arrivals == [] for bot in spawned)


def test_a_dropping_wave_is_alive(mission, spawned):
    wave = mission.spawn(WAVE)
    run_jobs(mission)

    assert wave.alive()
    assert not wave.all_destroyed()


# ---------------------------------------------------------------------------
# Jumping out
# ---------------------------------------------------------------------------


class Part(Destructible):
    """A destructible standing for a ship, a subsystem or a mounted bot."""

    def __init__(self, game, mounted_on=None):
        super().__init__(game)
        self.mounted_on = mounted_on
        self.is_clean = False
        self.played_death = False

    def clean(self):
        self.is_clean = True

    def get_health(self):
        return 100.0

    def play_death(self):
        self.played_death = True


@pytest.fixture
def parts_game():
    game = MagicMock()
    game.destructibles = Destructibles(on_death=MagicMock())
    game.method_lists = {}
    return game


def test_a_departed_object_is_torn_down_next_frame_without_a_death(parts_game):
    part = Part(parts_game)
    part.add_task(lambda: None)

    parts_game.destructibles.depart(part)
    assert part not in parts_game.destructibles.alive_objects
    assert not part.is_clean  # its tasks may still be due this frame

    parts_game.destructibles.handle_deaths()
    assert part.is_clean
    assert part.id not in parts_game.method_lists
    assert not part.played_death
    parts_game.destructibles.on_death.assert_not_called()
    assert parts_game.destructibles.departing_objects == []


def test_an_already_clean_departed_object_only_drops_its_tasks(parts_game):
    """A turret pawn, cleaned by its Bot before the teardown reaches it."""
    part = Part(parts_game)
    part.add_task(lambda: None)
    part.is_clean = True
    part.clean = MagicMock()

    parts_game.destructibles.depart(part)
    parts_game.destructibles.handle_deaths()

    part.clean.assert_not_called()
    assert part.id not in parts_game.method_lists


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def make_jumping_bot(bot_type="fighter"):
    bot = make_bot(bot_type)
    bot.clock = Clock()
    bot.game.game_time.get_current_time.side_effect = bot.clock
    bot._think_slot = MagicMock()
    bot.navigator = MagicMock()
    bot._commands = (0.7, 0.3, -0.2, 0.1)
    bot.game.departed_ids = set()
    bot.game.destructibles.alive_objects = []
    return bot


def test_jump_out_silences_the_ai_and_flies_straight_while_spooling():
    bot = make_jumping_bot()
    slot = bot._think_slot

    bot.jump_out(spool_s=2.0)
    slot.scheduler.unregister.assert_called_once_with(slot)
    bot.navigator.collision_sensor.set_active.assert_called_with(False)

    bot.clock.t = 1.0
    bot.move_bot_task()
    bot.tactician.think.assert_not_called()
    bot.pawn.move.assert_called_once_with(
        throttle=0.7, yaw_rate=0.0, pitch_rate=0.0, roll_rate=0.0
    )
    assert bot.hyperspace_transit is None


def test_after_the_spool_the_ship_jumps_then_departs(monkeypatch):
    created = []

    def fake_transit(**kwargs):
        transit = MagicMock(arriving=kwargs["arriving"])
        transit.step.return_value = False
        created.append((kwargs, transit))
        return transit

    monkeypatch.setattr("space_flight.actors.bot.HyperspaceTransit", fake_transit)
    bot = make_jumping_bot("major_ship")
    turret_bot = SimpleNamespace(pawn=SimpleNamespace(mounted_on=bot.pawn))
    generator = SimpleNamespace(mounted_on=bot.pawn)
    stranger = SimpleNamespace(mounted_on=MagicMock())
    bot.game.destructibles.alive_objects = [turret_bot, generator, stranger]

    bot.jump_out()
    bot.clock.t = JUMP_SPOOL_S
    bot.move_bot_task()

    kwargs, transit = created[0]
    assert kwargs["arriving"] is False
    assert kwargs["distance_m"] == TRANSIT_DISTANCE_M["major_ship"]
    transit.begin.assert_called_once()
    # Nothing can stay locked onto the ship or its parts
    dropped = [
        c.kwargs["target_to_remove"]
        for c in bot.game.player.remove_target.call_args_list
    ]
    assert bot.pawn in dropped and turret_bot.pawn in dropped and generator in dropped

    transit.step.return_value = True
    bot.move_bot_task()
    assert bot.has_departed
    assert bot.hyperspace_transit is None
    bot.pawn.node.hide.assert_called_once()
    assert bot.pawn.id in bot.game.departed_ids
    bot.game.interactions.remove_actor.assert_called_with(bot.pawn)
    departed = [c.args[0] for c in bot.game.destructibles.depart.call_args_list]
    assert departed == [turret_bot, generator, bot]

    # Gone: nothing more happens until the teardown
    bot.move_bot_task()
    assert transit.step.call_count == 2


def test_a_ship_still_dropping_in_lands_before_spooling():
    bot = make_jumping_bot()
    bot.hyperspace_transit = arrival = MagicMock(arriving=True)

    bot.jump_out()

    arrival.end.assert_called_once()
    assert bot.hyperspace_transit is None
    assert bot._jump_at_s == pytest.approx(JUMP_SPOOL_S)


@pytest.mark.parametrize("case", ["dying", "turret", "twice"])
def test_jump_out_is_a_no_op(case):
    bot = make_jumping_bot("turret" if case == "turret" else "fighter")
    if case == "dying":
        bot._dying.begin()
    if case == "twice":
        bot.jump_out(spool_s=1.0)
        bot.clock.t = 0.5
    bot.jump_out(spool_s=5.0)
    expected = 1.0 if case == "twice" else None
    assert bot._jump_at_s == expected


def test_depart_is_done_once():
    bot = make_jumping_bot()
    bot.depart()
    bot.depart()
    assert bot.game.destructibles.depart.call_count == 1


# ---------------------------------------------------------------------------
# Waves and missions
# ---------------------------------------------------------------------------


def test_a_wave_jumps_out_its_live_members(mission, spawned):
    wave = mission.spawn(WAVE)
    run_jobs(mission)

    wave.jump_out()
    wave.jump_out(spool_s=0.5)

    assert all(bot.jump_outs == [None, 0.5] for bot in spawned)


def test_an_escape_is_not_a_kill(mission, spawned):
    game = mission.game
    wave = mission.spawn(WAVE)
    run_jobs(mission)
    pawns = wave.pawns()

    depart_all(game, pawns[:1])
    assert wave.any_jumped_out() and not wave.all_jumped_out()
    assert wave.jumped_out_count() == 1
    assert wave.destroyed_count() == 0 and not wave.any_destroyed()

    game.interactions.kill(pawns[1])
    assert wave.destroyed_count() == 1
    depart_all(game, pawns[2:])
    assert not wave.alive()
    assert not wave.all_destroyed()
    assert not wave.all_jumped_out()


def test_a_wave_that_all_jumped_out(mission, spawned):
    wave = mission.spawn(WAVE)
    assert not wave.all_jumped_out()  # not spawned yet
    run_jobs(mission)

    depart_all(mission.game, wave.pawns())
    assert wave.all_jumped_out()
    assert not wave.all_destroyed()


def test_mission_jump_out_skips_the_player(mission, spawned):
    wave = mission.spawn(WAVE)
    run_jobs(mission)
    mission.game.player.jump_out = MagicMock()

    mission.jump_out([wave, mission.game.player], spool_s=1.5)

    assert all(bot.jump_outs == [1.5] for bot in spawned)
    mission.game.player.jump_out.assert_not_called()
