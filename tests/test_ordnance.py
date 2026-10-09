"""
Tests for ordnance in flight (space_flight.actors.ordnance): the Ordnance pawn
and its OrdnanceController, flown end to end through a real Integrator, the
real launcher, navigator and pilot, on a minimal fake game.

The headless app is only used to load the placeholder sphere model.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest
from panda3d.core import NodePath

from space_flight.actors.destructibles import Destructibles
from space_flight.actors.ordnance import Ordnance, OrdnanceController
from space_flight.game.integrator import Integrator
from space_flight.weapons.ordnance_launcher import (
    OrdnanceLauncher,
    load_ordnance_configuration,
)

DT_S = 1 / 60
# The smallest fighter hit box: closer than this to its centre is a hit
TARGET_HIT_BOX_RADIUS_M = 5.0


class FakeGameTime:
    """A game clock advanced by hand, one fixed step per frame."""

    def __init__(self):
        self.time_s = 0.0

    def get_time_step(self) -> float:
        return DT_S

    def get_current_time(self) -> float:
        return self.time_s


class FakeInteractions:
    """The targetable actors, looked up by id like Interactions does."""

    def __init__(self):
        self.actors = []

    def get_actor_index_from_id(self, actor_id: uuid.UUID) -> int:
        for index, actor in enumerate(self.actors):
            if actor is not None and actor.id == actor_id:
                return index
        raise ValueError(f"Actor {actor_id} is not in the actors' list")


@pytest.fixture
def game(spaceflight_app):
    """
    A minimal game: real integrator, destructibles and per-object task lists,
    fake clock and interactions, mocked collision system and effects.
    """
    game = MagicMock()
    game.app = spaceflight_app
    game.root_node = NodePath("root")
    game.game_time = FakeGameTime()
    game.integrator = Integrator(game=game, max_state_size=1000)
    game.method_lists = {}
    game.destructibles = Destructibles()
    game.interactions = FakeInteractions()
    game.scene.up_direction = np.array([0.0, 0.0, 1.0])
    return game


def step(game, n_frames: int = 1, targets=()):
    """
    Advance the fake game like FlightState.update_game_world_task does, moving
    the scripted targets along.
    """
    for _ in range(n_frames):
        game.game_time.time_s += DT_S
        for target in targets:
            target.position = target.position + target.speed * DT_S
        game.destructibles.handle_deaths()
        game.integrator.step()
        for method_list in list(game.method_lists.values()):
            for method in method_list:
                method()


def make_ship(position=(0.0, 0.0, 0.0), speed=(0.0, 100.0, 0.0), team=1):
    """
    A launching ship, level and facing +Y (right +X, up +Z).
    """
    return SimpleNamespace(
        id=uuid.uuid4(),
        team=team,
        position=np.array(position, dtype=float),
        speed=np.array(speed, dtype=float),
        orientation=np.array([1.0, 0.0, 0.0, 0.0]),
        right=np.array([1.0, 0.0, 0.0]),
        forward=np.array([0.0, 1.0, 0.0]),
        up=np.array([0.0, 0.0, 1.0]),
        node=NodePath("ship"),
        parent=SimpleNamespace(name="launcher"),
    )


def make_target(position, speed):
    """A scripted target actor, registered in the interactions."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        position=np.array(position, dtype=float),
        speed=np.array(speed, dtype=float),
        is_dead=False,
        incoming_missiles={},
    )


def launch(game, name, ship=None, target_id=None, damage_multiplier=1.0):
    """
    Launch one ordnance from a fresh launcher, and return its controller.
    """
    ship = make_ship() if ship is None else ship
    launcher = OrdnanceLauncher(
        game=game,
        parent=ship,
        name=name,
        stock=1,
        damage_multiplier=damage_multiplier,
    )
    launcher.last_fire_time = -np.inf  # no initial reload
    if target_id is not None:
        launcher.target_lock = MagicMock(is_locked=True)
    controller = launcher.launch(target_id=target_id)
    assert controller is not None
    assert controller in game.destructibles.alive_objects
    assert controller.pawn.origin_ship is ship
    return controller


# ---------------------------
# launch
# ---------------------------


@pytest.mark.parametrize(
    "name, expected_offset, expected_velocity",
    [
        # Belly drop: the ship's velocity plus the launch speed along -up
        ("proton_bomb", [0.0, 0.0, 0.0], [0.0, 100.0, -75.0]),
        # Forward, on top of the ship's velocity
        ("rocket", [0.0, 0.0, 0.0], [0.0, 500.0, 0.0]),
        ("proton_torpedo", [0.0, 0.0, 0.0], [0.0, 350.0, 0.0]),
        # Just behind the ship, drifting with its velocity
        ("flare", [0.0, -12.0, 0.0], [0.0, 100.0, 0.0]),
    ],
)
def test_launch_position_and_velocity(game, name, expected_offset, expected_velocity):
    """
    Every ordnance starts at the ship (offset along its launch direction) with
    the ship's velocity plus its launch speed along its launch direction.
    """
    ship = make_ship(position=(10.0, 20.0, 30.0))

    pawn = launch(game, name, ship=ship).pawn

    np.testing.assert_allclose(pawn.position, ship.position + expected_offset)
    np.testing.assert_allclose(pawn.speed, expected_velocity, atol=1e-9)
    assert pawn.max_speed_mps == pytest.approx(np.linalg.norm(expected_velocity))
    assert pawn.team == ship.team
    assert pawn.origin_ship_id == ship.id


def test_ordnance_power_is_scaled_by_the_launchers_damage_multiplier(game):
    """An ordnance hits with its configured damage times the launcher's multiplier."""
    base_damage = load_ordnance_configuration("rocket")["damage"]

    pawn = launch(game, "rocket", damage_multiplier=0.5).pawn

    assert pawn.power == pytest.approx(0.5 * base_damage)


def test_flare_has_a_flare_collider_and_others_an_ordnance_collider(game):
    """
    Flares register as decoys; the other ordnance as ordnance.
    """
    flare = launch(game, "flare").pawn
    rocket = launch(game, "rocket").pawn

    assert flare.collision_sphere_np.name == "flare"
    assert rocket.collision_sphere_np.name == "ordnance"
    assert rocket.collision_sphere_np.getPythonTag("owner") is rocket


# ---------------------------
# flight
# ---------------------------


@pytest.mark.parametrize("name", ["proton_bomb", "rocket", "flare", "proton_torpedo"])
def test_unguided_ordnance_flies_straight_at_constant_velocity(game, name):
    """
    Bombs, rockets, flares and a missile launched without a target keep their
    launch velocity: a straight line, integrated exactly.
    """
    controller = launch(game, name)
    pawn = controller.pawn
    start_position = pawn.position.copy()
    velocity = pawn.speed.copy()

    step(game, n_frames=120)

    assert controller.navigator is None
    np.testing.assert_allclose(pawn.speed, velocity, atol=1e-9)
    np.testing.assert_allclose(
        pawn.position, start_position + velocity * 120 * DT_S, atol=1e-6
    )


def test_guided_missile_pursues_a_crossing_target_at_constant_speed(game):
    """
    A missile launched at a locked target turns toward it (within its
    configured turn rates), keeps its speed, and reaches it.
    """
    target = make_target(position=[0.0, 1500.0, 0.0], speed=[150.0, 0.0, 0.0])
    game.interactions.actors.append(target)
    controller = launch(game, "concussion_missile", target_id=target.id)
    pawn = controller.pawn
    launch_speed_mps = np.linalg.norm(pawn.speed)
    max_rates_radps = np.deg2rad(
        [
            pawn.conf["max_pitch_rate_degps"],
            pawn.conf["max_roll_rate_degps"],
            pawn.conf["max_yaw_rate_degps"],
        ]
    )

    min_distance_m = np.inf
    for _ in range(int(10.0 / DT_S)):
        step(game, targets=[target])
        min_distance_m = min(
            min_distance_m, np.linalg.norm(target.position - pawn.position)
        )
        assert np.linalg.norm(pawn.speed) == pytest.approx(launch_speed_mps)
        assert np.all(np.abs(pawn.pqr) <= max_rates_radps + 1e-9)
        if min_distance_m < TARGET_HIT_BOX_RADIUS_M:
            break

    assert min_distance_m < TARGET_HIT_BOX_RADIUS_M


def test_missile_flies_straight_once_its_target_is_lost(game):
    """
    When the target leaves the interactions (destroyed), the missile drops its
    guidance and flies straight on.
    """
    target = make_target(position=[500.0, 1500.0, 0.0], speed=[0.0, 0.0, 0.0])
    game.interactions.actors.append(target)
    controller = launch(game, "concussion_missile", target_id=target.id)
    step(game, n_frames=30)
    assert controller.navigator is not None

    game.interactions.actors.remove(target)
    step(game, n_frames=30)  # guidance dropped, turn rates settle (filter)
    velocity = controller.pawn.speed.copy()
    step(game, n_frames=30)

    assert controller.navigator is None
    assert controller.pilot is None
    np.testing.assert_allclose(controller.pawn.speed, velocity, atol=1e-2)


# ---------------------------
# end of life
# ---------------------------


def test_ordnance_disappears_silently_at_the_end_of_its_life(game):
    """
    At the end of its life the ordnance is removed: no explosion, no smoke, no
    task or registration left behind.
    """
    controller = launch(game, "rocket")
    life_time_s = controller.life_time_s

    step(game, n_frames=int(life_time_s / DT_S) - 2)
    assert controller in game.destructibles.alive_objects

    step(game, n_frames=4)

    assert controller not in game.destructibles.alive_objects
    assert controller not in game.destructibles.dying_objects
    assert controller.id not in game.method_lists
    assert controller.pawn is None
    game.fire_smoke_pool.assert_not_called()
    assert not game.fire_smoke_pool.method_calls


def test_on_impact_spends_the_ordnance_and_mutes_its_collider(game):
    """
    An impact spends the ordnance at once (its collider stops reporting) and it
    is removed at the next death handling.
    """
    controller = launch(game, "concussion_missile")
    collider = controller.pawn.collision_sphere_np

    controller.pawn.on_impact()

    assert collider.getPythonTag("owner") is None
    assert controller.get_health() == 0.0
    step(game)
    assert controller.pawn is None
    assert controller not in game.destructibles.alive_objects


def test_throttle_does_not_limit_ordnance_turn_rates():
    """
    An ordnance has no engine: its turn rates are not scaled by the throttle,
    unlike a ship's (see turn_rate_scale).
    """
    pawn = object.__new__(Ordnance)

    for throttle in (0.0, 0.6, 1.0, 2.0):
        assert pawn._turn_rate_scale(throttle) == 1.0


def test_impact_position_is_the_ordnance_position(game):
    """
    impact_position reports where the ordnance is.
    """
    pawn = launch(game, "rocket", ship=make_ship(position=(1.0, 2.0, 3.0))).pawn

    assert tuple(pawn.impact_position()) == pytest.approx((1.0, 2.0, 3.0))


# ---------------------------
# "missile incoming" message
# ---------------------------


def test_guided_missile_keeps_its_target_warned(game):
    """
    A guided missile sends its target an IncomingMissile message on its first
    frame, and keeps it up to date as it closes in.
    """
    target = make_target(position=[0.0, 1500.0, 0.0], speed=[0.0, 0.0, 0.0])
    game.interactions.actors.append(target)
    controller = launch(game, "concussion_missile", target_id=target.id)

    step(game)
    message = target.incoming_missiles[controller.id]
    first_distance_m = message.distance_m
    assert message.controller is controller
    # Sent from the controller's task: it may lag the integrated position by a
    # frame, but is consistent with itself
    assert first_distance_m == pytest.approx(
        np.linalg.norm(target.position - message.position)
    )
    assert np.linalg.norm(message.position - controller.pawn.position) < 10.0
    # Launched at 300 m/s on top of the ship's 100 m/s, straight at the target
    assert message.closing_speed_mps == pytest.approx(400.0, rel=1e-3)
    assert message.time_to_impact_s == pytest.approx(first_distance_m / 400.0, rel=1e-3)

    step(game, n_frames=30)
    assert target.incoming_missiles[controller.id].distance_m < first_distance_m


def test_unguided_ordnance_warns_nobody(game):
    """
    A missile launched without a lock flies blind: nobody is warned.
    """
    target = make_target(position=[0.0, 1500.0, 0.0], speed=[0.0, 0.0, 0.0])
    game.interactions.actors.append(target)
    launch(game, "concussion_missile")

    step(game, n_frames=5)

    assert target.incoming_missiles == {}


def test_warning_is_withdrawn_once_the_target_is_lost(game):
    """
    When the missile loses its target, its message is withdrawn.
    """
    target = make_target(position=[0.0, 1500.0, 0.0], speed=[0.0, 0.0, 0.0])
    game.interactions.actors.append(target)
    launch(game, "concussion_missile", target_id=target.id)
    step(game)
    assert target.incoming_missiles

    game.interactions.actors.remove(target)
    step(game)

    assert target.incoming_missiles == {}


def test_warning_is_withdrawn_when_the_missile_is_spent(game):
    """
    When the missile hits something, its message is withdrawn as it is removed.
    """
    target = make_target(position=[0.0, 1500.0, 0.0], speed=[0.0, 0.0, 0.0])
    game.interactions.actors.append(target)
    controller = launch(game, "concussion_missile", target_id=target.id)
    step(game)
    assert target.incoming_missiles

    controller.pawn.on_impact()
    step(game)

    assert target.incoming_missiles == {}


# ---------------------------
# flare decoy
# ---------------------------


def _missile_and_flare_in_reach(game):
    """
    A missile homing on a target 1500 m ahead, and an enemy flare dropped about
    300 m ahead of it and 20 deg off its nose: within its decoy range and cone.
    """
    target = make_target(position=[0.0, 1500.0, 0.0], speed=[0.0, 0.0, 0.0])
    game.interactions.actors.append(target)
    missile = launch(game, "concussion_missile", target_id=target.id)
    flare = launch(
        game, "flare", ship=make_ship(position=(100.0, 300.0, 0.0), team=2)
    ).pawn
    step(game)
    return target, missile, flare


def test_decoyed_missile_homes_on_the_flare_silently(game, monkeypatch):
    """
    A missile lured by a flare withdraws its target's warning and homes on the
    flare.
    """
    target, missile, flare = _missile_and_flare_in_reach(game)
    monkeypatch.setattr(np.random, "random", lambda: 0.0)

    assert missile.offer_decoy(flare) is True

    min_distance_m = np.inf
    for _ in range(int(3.0 / DT_S)):
        step(game)
        assert target.incoming_missiles == {}
        min_distance_m = min(
            min_distance_m, np.linalg.norm(flare.position - missile.pawn.position)
        )
    assert min_distance_m < flare.conf["collision_radius_m"]


def test_missile_not_lured_keeps_homing_on_its_target(game, monkeypatch):
    """
    A missile the flare does not lure (here, by chance) ignores it.
    """
    target, missile, flare = _missile_and_flare_in_reach(game)
    monkeypatch.setattr(np.random, "random", lambda: 1.0)

    assert missile.offer_decoy(flare) is False

    step(game)
    assert missile.decoy_pawn is None
    assert missile.id in target.incoming_missiles


def test_decoyed_missile_flies_straight_once_the_flare_is_spent(game, monkeypatch):
    """
    Once its flare burns out, a decoyed missile drops its guidance: it does not
    go back to its target.
    """
    target, missile, flare = _missile_and_flare_in_reach(game)
    monkeypatch.setattr(np.random, "random", lambda: 0.0)
    missile.offer_decoy(flare)
    step(game)

    flare.health = 0.0
    step(game, n_frames=2)

    assert missile.navigator is None
    assert missile.decoy_pawn is None
    assert target.incoming_missiles == {}


def test_unguided_ordnance_ignores_flares(game, monkeypatch):
    """
    Only a guided missile can be decoyed.
    """
    rocket = launch(game, "rocket")
    flare = launch(game, "flare", ship=make_ship(position=(0.0, 100.0, 0.0))).pawn
    monkeypatch.setattr(np.random, "random", lambda: 0.0)

    assert rocket.offer_decoy(flare) is False


def _guided_missile():
    """
    A guided missile at the origin flying +Y, decoyed within 400 m and 30 deg
    with a 0.7 chance, its controller built without a game.
    """
    controller = object.__new__(OrdnanceController)
    controller.name = "missile"
    controller.navigator = MagicMock()
    controller.decoy_pawn = None
    controller.warned_target = None
    controller.pawn = SimpleNamespace(
        position=np.zeros(3),
        forward=np.array([0.0, 1.0, 0.0]),
        conf={
            "decoy_range_m": 400.0,
            "decoy_cone_angle_deg": 30.0,
            "decoy_chance": 0.7,
        },
    )
    return controller


@pytest.mark.parametrize(
    "flare_position, draw, expected",
    [
        # Ahead, in range: lured if the draw is under the chance
        ([0.0, 300.0, 0.0], 0.5, True),
        ([0.0, 300.0, 0.0], 0.8, False),
        # Too far
        ([0.0, 500.0, 0.0], 0.0, False),
        # In range but outside the seeker cone (about 70 deg off the nose)
        ([280.0, 100.0, 0.0], 0.0, False),
        # Just inside the cone
        ([140.0, 260.0, 0.0], 0.0, True),
        # Right on the missile
        ([0.0, 0.0, 0.0], 0.0, True),
    ],
)
def test_flare_lures_a_missile_within_range_and_cone_by_chance(
    flare_position, draw, expected, monkeypatch
):
    """
    A flare lures a missile only within its decoy range and seeker cone, and
    then by chance.
    """
    controller = _guided_missile()
    flare = SimpleNamespace(position=np.array(flare_position, dtype=float))
    monkeypatch.setattr(np.random, "random", lambda: draw)

    assert controller.offer_decoy(flare) is expected
    assert (controller.decoy_pawn is flare) is expected


def test_a_decoyed_missile_ignores_further_flares(monkeypatch):
    """
    A missile already decoyed keeps chasing its first flare.
    """
    controller = _guided_missile()
    first = SimpleNamespace(position=np.array([0.0, 300.0, 0.0]))
    second = SimpleNamespace(position=np.array([0.0, 200.0, 0.0]))
    monkeypatch.setattr(np.random, "random", lambda: 0.0)

    assert controller.offer_decoy(first) is True
    assert controller.offer_decoy(second) is False
    assert controller.decoy_pawn is first
