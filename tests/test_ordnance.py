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
from space_flight.actors.ordnance import Ordnance
from space_flight.game.integrator import Integrator
from space_flight.weapons.ordnance_launcher import OrdnanceLauncher

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
    )


def launch(game, name, ship=None, target_id=None):
    """
    Launch one ordnance from a fresh launcher, and return its controller.
    """
    ship = make_ship() if ship is None else ship
    launcher = OrdnanceLauncher(game=game, parent=ship, name=name, stock=1)
    launcher.last_fire_time = -np.inf  # no initial reload
    assert launcher.launch(target_id=target_id) is True
    (controller,) = [
        destructible
        for destructible in game.destructibles.alive_objects
        if getattr(destructible, "pawn", None) is not None
        and destructible.pawn.origin_ship is ship
    ]
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
