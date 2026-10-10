"""
Unit tests for the Hangar subsystem (space_flight.actors.major_ship.hangar).

Hangars are built for real on a mock game; spawn_bot is patched with a fake
that registers each launched fighter's pawn in a stand-in Interactions, so
tests can count live fighters and kill them.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest
from panda3d.core import CollisionBox, NodePath

from space_flight.actors.major_ship.hangar import HANGAR_ACTOR_SLOT_RESERVE, Hangar
from space_flight.actors.major_ship.sub_system import SubSystem
from space_flight.actors.ship import load_ship_configuration
from space_flight.utils import rotation_matrix_coefficients

# The star destroyer's ventral bay and hull sphere (see isd/configuration.yaml)
ISD_BAY_CENTRE = np.array([0.0, 131.0, -30.0])
ISD_BAY_HALF_EXTENTS = np.array([90.0, 169.0, 30.0])
ISD_HULL_RADIUS_M = 120.0


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def get_current_time(self):
        return self.t


class FakeInteractions:
    """Just what a hangar reads: live actors by id, and the free slots."""

    def __init__(self, free_slots: int = 50):
        self.actors = []
        self.actors_id_dict = {}
        self.free_slots = list(range(free_slots))

    def add_actor(self, actor):
        self.actors_id_dict[actor.id] = len(self.actors)
        self.actors.append(actor)

    def remove_actor(self, actor):
        self.actors_id_dict.pop(actor.id, None)


def make_game_and_ship(team: int = 2, free_slots: int = 50):
    """
    A mock game (with a controllable clock) and a host ship at the origin,
    axes aligned with the world.
    """
    game = MagicMock()
    game.destructibles.alive_objects = []
    game.method_lists = {}
    game.root_node = NodePath("root")
    game.game_time = FakeClock()
    game.interactions = FakeInteractions(free_slots=free_slots)
    ship = SimpleNamespace(
        team=team,
        node=NodePath("ship"),
        is_dead=False,
        health=1000.0,
        position=np.zeros(3),
        speed=np.zeros(3),
        right=np.array([1.0, 0.0, 0.0]),
        forward=np.array([0.0, 1.0, 0.0]),
        up=np.array([0.0, 0.0, 1.0]),
        orientation=np.array([1.0, 0.0, 0.0, 0.0]),
        parent=SimpleNamespace(name="isd", is_dying=False),
    )
    ship.node.reparentTo(game.root_node)
    return game, ship


# A stock large enough not to run out, unless a test says otherwise
PLENTY = {"tie-fighter": 50, "tie-interceptor": 50, "tie-bomber": 50}


def make_hangar(game, ship, stock=PLENTY, **kwargs) -> Hangar:
    """
    A hangar on ship, with the star destroyer's bay unless overridden, stocked
    as the level would (None leaves it unstocked).
    """
    kwargs.setdefault("relative_position", ISD_BAY_CENTRE)
    kwargs.setdefault("half_extents_m", ISD_BAY_HALF_EXTENTS)
    hangar = Hangar(game=game, parent=ship, **kwargs)
    if stock is not None:
        hangar.set_stock(stock)
    return hangar


@pytest.fixture
def spawned(monkeypatch):
    """
    Patch spawn_bot: each launched fighter is a fake bot whose pawn joins the
    game's interactions. Returns the list of spawn_bot call kwargs.
    """
    calls = []

    def fake_spawn_bot(game, **kwargs):
        calls.append(kwargs)
        pawn = SimpleNamespace(id=uuid.uuid4(), formation=None)
        bot = SimpleNamespace(
            pawn=pawn, tactician=SimpleNamespace(primary_target_ids=[])
        )
        pawn.parent = bot
        game.interactions.add_actor(pawn)
        return bot

    monkeypatch.setattr("space_flight.actors.bot.spawn_bot", fake_spawn_bot)
    return calls


def run(game, hangar, until_s: float, step_s: float = 0.1):
    """Step the hangar's update until game time until_s."""
    while game.game_time.t <= until_s + 1e-9:
        hangar.update()
        game.game_time.t += step_s


def kill(game, pawn):
    """A launched fighter dies."""
    game.interactions.remove_actor(pawn)


# ---------------------------
# Construction
# ---------------------------


def test_hangar_is_a_targetable_subsystem_with_a_box_collider():
    """
    A hangar builds as a SubSystem of its ship, its collider a box of the bay's
    size, its radius the box's bounding radius. It holds nothing until the
    level stocks it.
    """
    game, ship = make_game_and_ship(team=2)

    hangar = make_hangar(game, ship, stock=None)

    assert isinstance(hangar, SubSystem)
    assert hangar.team == 2
    assert hangar.category == "sub_system"
    assert hangar in game.destructibles.alive_objects
    solid = hangar.collision_np.node().getSolid(0)
    assert isinstance(solid, CollisionBox)
    np.testing.assert_allclose(
        solid.getMax() - solid.getMin(), 2.0 * ISD_BAY_HALF_EXTENTS, atol=1e-3
    )
    assert hangar.hit_box_radius_m == pytest.approx(
        np.linalg.norm(ISD_BAY_HALF_EXTENTS)
    )
    assert hangar.stock == {}


@pytest.mark.parametrize(
    "fighter_type", ["tie-fighter", "tie-interceptor", "tie-bomber"]
)
def test_launch_point_clears_the_bay_and_the_star_destroyer_hull(fighter_type):
    """
    With the star destroyer's config, a fighter is launched just below the bay
    box, its collision sphere clear of the box by the margin, and outside the
    hull sphere.
    """
    game, ship = make_game_and_ship()
    hangar = make_hangar(game, ship)
    radius_m = load_ship_configuration(fighter_type)["hit_box_radius_m"]

    point = hangar.launch_point(radius_m)

    bay_floor_z = ISD_BAY_CENTRE[2] - ISD_BAY_HALF_EXTENTS[2]
    assert point[2] == pytest.approx(bay_floor_z - radius_m - hangar.launch_margin_m)
    np.testing.assert_allclose(point[:2], ISD_BAY_CENTRE[:2])
    assert np.linalg.norm(point) > ISD_HULL_RADIUS_M + radius_m


# ---------------------------
# Stock
# ---------------------------


def test_set_stock_copies_the_levels_dictionary():
    """The level's stock dictionary is copied: launches never change it."""
    game, ship = make_game_and_ship()
    stock = {"tie-fighter": 2}
    hangar = make_hangar(game, ship, stock=stock)

    hangar.stock["tie-fighter"] = 0

    assert stock == {"tie-fighter": 2}


def test_set_stock_rejects_unknown_types_and_negative_counts():
    """An unknown ship type or a negative count is refused."""
    game, ship = make_game_and_ship()
    hangar = make_hangar(game, ship, stock=None)

    with pytest.raises(FileNotFoundError):
        hangar.set_stock({"millennium-falcon": 1})
    with pytest.raises(ValueError):
        hangar.set_stock({"tie-fighter": -1})
    assert hangar.stock == {}


def test_launching_a_type_not_in_the_stock_raises(spawned):
    """A fighter type the hangar is not stocked with raises at the request."""
    game, ship = make_game_and_ship()
    hangar = make_hangar(game, ship, stock={"tie-fighter": 3})

    with pytest.raises(KeyError, match="tie-bomber"):
        hangar.launch("tie-bomber", 1)
    assert hangar.orders == []


def test_launching_an_empty_type_does_nothing(spawned):
    """A request for a type whose stock is empty launches nothing."""
    game, ship = make_game_and_ship()
    hangar = make_hangar(game, ship, stock={"tie-fighter": 0})

    order = hangar.launch("tie-fighter", 3)
    run(game, hangar, until_s=10.0)

    assert spawned == []
    assert order.cancelled and order.ids == []
    assert hangar.orders == []


def test_a_type_running_out_cancels_only_its_requests(spawned):
    """
    Each launch spends one fighter of its type; once that type is spent, what
    is left of its request is cancelled, and the next request goes on.
    """
    game, ship = make_game_and_ship()
    hangar = make_hangar(game, ship, stock={"tie-fighter": 2, "tie-bomber": 5})

    fighters = hangar.launch("tie-fighter", 3)
    bombers = hangar.launch("tie-bomber", 2)
    run(game, hangar, until_s=20.0)

    assert [call["pawn_model"] for call in spawned] == [
        "tie-fighter",
        "tie-fighter",
        "tie-bomber",
        "tie-bomber",
    ]
    assert fighters.cancelled and len(fighters.ids) == 2
    assert bombers.done and not bombers.cancelled
    assert hangar.stock == {"tie-fighter": 0, "tie-bomber": 3}


# ---------------------------
# Launching
# ---------------------------


def test_launches_are_staggered(spawned):
    """
    Fighters leave one at a time, launch_interval_s apart, until the order is
    filled.
    """
    game, ship = make_game_and_ship()
    hangar = make_hangar(game, ship, launch_interval_s=1.5)

    order = hangar.launch("tie-fighter", 3)
    run(game, hangar, until_s=1.4)
    assert len(spawned) == 1
    run(game, hangar, until_s=1.6)
    assert len(spawned) == 2
    run(game, hangar, until_s=10.0)
    assert len(spawned) == 3
    assert order.done and not order.cancelled
    assert order.ids == [pawn.id for pawn in hangar.launched_pawns()]


def test_launch_defaults_to_a_group(spawned):
    """A launch request without a count gets group_size fighters."""
    game, ship = make_game_and_ship()
    hangar = make_hangar(game, ship, group_size=2)

    hangar.launch("tie-fighter")
    run(game, hangar, until_s=10.0)

    assert len(spawned) == 2


def test_launches_the_requested_type(spawned):
    """Every fighter of a request is of its fighter type."""
    game, ship = make_game_and_ship()
    hangar = make_hangar(game, ship)

    hangar.launch("tie-interceptor", 2)
    run(game, hangar, until_s=10.0)

    assert [call["pawn_model"] for call in spawned] == ["tie-interceptor"] * 2


def test_launched_fighters_ride_the_ships_motion(spawned):
    """
    A fighter is launched at the ship-local launch point (set by its own
    radius) and with the ship's velocity plus the launch velocity, both turned
    with the ship, nose first out of the bay, with the ship's current team, as
    a fighter bot.
    """
    game, ship = make_game_and_ship(team=2)
    hangar = make_hangar(game, ship, launch_speed_mps=30.0)
    # The ship flies at x=1000, turned 90 deg left: its forward is world -x
    ship.position = np.array([1000.0, 0.0, 0.0])
    ship.right = np.array([0.0, 1.0, 0.0])
    ship.forward = np.array([-1.0, 0.0, 0.0])
    ship.speed = np.array([-40.0, 0.0, 0.0])
    ship.orientation = np.array([np.sqrt(0.5), 0.0, 0.0, np.sqrt(0.5)])
    ship.team = 3

    hangar.launch("tie-bomber", 1)
    hangar.update()

    kwargs = spawned[0]
    radius_m = load_ship_configuration("tie-bomber")["hit_box_radius_m"]
    local = hangar.launch_point(radius_m)
    expected_position = ship.position + np.array([-local[1], local[0], local[2]])
    np.testing.assert_allclose(kwargs["ini_position"], expected_position)
    np.testing.assert_allclose(kwargs["ini_speed"], [-40.0, 0.0, -30.0])
    _, forward, _ = body_axes(kwargs["ini_orientation"])
    np.testing.assert_allclose(forward, [0.0, 0.0, -1.0], atol=1e-9)
    assert kwargs["team"] == 3
    assert kwargs["bot_type"] == "fighter"
    assert kwargs["pawn_model"] == "tie-bomber"
    assert kwargs["name"] == "isd_hangar_0"


def body_axes(orientation) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The (right, forward, up) world axes of an orientation (w, x, y, z)."""
    c = rotation_matrix_coefficients(*orientation)
    return (
        np.array([c[0], c[3], c[6]]),
        np.array([c[1], c[4], c[7]]),
        np.array([c[2], c[5], c[8]]),
    )


@pytest.mark.parametrize(
    "launch_direction, expected_up",
    [
        ((0.0, 0.0, -1.0), (0.0, 1.0, 0.0)),  # ventral bay: top toward the bow
        ((0.0, 0.0, 1.0), (0.0, 1.0, 0.0)),  # dorsal bay: top toward the bow
        ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),  # bow bay: top up
        ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),  # side bay: top toward the bow
    ],
    ids=["ventral", "dorsal", "bow", "side"],
)
def test_fighters_leave_the_bay_nose_first(launch_direction, expected_up):
    """
    A launched fighter points along launch_direction (its thrust then carries it
    away from the bay), its top toward the ship axis the most across it, in the
    ship's frame however the ship is turned.
    """
    game, ship = make_game_and_ship()
    hangar = make_hangar(game, ship, launch_direction=launch_direction)
    # The ship turned 90 deg left: ship x, y, z are world y, -x, z
    body_to_world = np.column_stack(
        ([0.0, 1.0, 0.0], [-1.0, 0.0, 0.0], [0.0, 0.0, 1.0])
    )

    right, forward, up = body_axes(hangar.launch_orientation(body_to_world))

    np.testing.assert_allclose(forward, body_to_world @ launch_direction, atol=1e-9)
    np.testing.assert_allclose(up, body_to_world @ expected_up, atol=1e-9)
    np.testing.assert_allclose(right, np.cross(forward, up), atol=1e-9)


def test_launched_group_flies_in_formation_with_its_targets(spawned):
    """
    A launched group forms up on its first fighter, gets the order's primary
    targets, and each fighter is reported to on_launched.
    """
    game, ship = make_game_and_ship()
    hangar = make_hangar(game, ship, formation="arrowhead")
    launched = []

    order = hangar.launch(
        "tie-fighter", 3, on_launched=launched.append, primary_target_ids=["prey"]
    )
    run(game, hangar, until_s=10.0)

    pawns = hangar.launched_pawns()
    assert order.formation.ship_ids == [pawn.id for pawn in pawns]
    assert all(pawn.formation is order.formation for pawn in pawns)
    assert [bot.pawn for bot in launched] == pawns
    assert all(bot.tactician.primary_target_ids == ["prey"] for bot in launched)


def test_orders_are_filled_in_turn(spawned):
    """A second request launches once the first one is filled."""
    game, ship = make_game_and_ship()
    hangar = make_hangar(game, ship)

    first = hangar.launch("tie-fighter", 2)
    second = hangar.launch("tie-interceptor", 1)
    run(game, hangar, until_s=10.0)

    assert len(first.ids) == 2 and len(second.ids) == 1
    assert [call["pawn_model"] for call in spawned] == [
        "tie-fighter",
        "tie-fighter",
        "tie-interceptor",
    ]


# ---------------------------
# Limits
# ---------------------------


def test_launches_wait_while_max_active_fighters_are_alive(spawned):
    """
    No more than max_active of its fighters are alive at once: the next launch
    waits for one of them to die.
    """
    game, ship = make_game_and_ship()
    hangar = make_hangar(game, ship, max_active=2)

    order = hangar.launch("tie-fighter", 3)
    run(game, hangar, until_s=10.0)
    assert len(spawned) == 2 and hangar.n_active == 2
    assert not order.done

    kill(game, hangar.launched_pawns()[0])
    run(game, hangar, until_s=20.0)

    assert len(spawned) == 3
    assert order.done


def test_launches_wait_for_free_interaction_slots(spawned):
    """
    A launch waits while no more than HANGAR_ACTOR_SLOT_RESERVE interaction
    slots are free, so fighters never take the last ones.
    """
    game, ship = make_game_and_ship(free_slots=HANGAR_ACTOR_SLOT_RESERVE)
    hangar = make_hangar(game, ship)

    hangar.launch("tie-fighter", 1)
    run(game, hangar, until_s=5.0)
    assert spawned == []

    game.interactions.free_slots.append(99)
    run(game, hangar, until_s=10.0)

    assert len(spawned) == 1


# ---------------------------
# Destruction
# ---------------------------


@pytest.mark.parametrize(
    "destroy",
    [
        lambda hangar, ship: setattr(hangar, "health", 0.0),
        lambda hangar, ship: setattr(ship, "is_dead", True),
        lambda hangar, ship: setattr(ship, "health", 0.0),
        lambda hangar, ship: setattr(ship.parent, "is_dying", True),
    ],
    ids=["hangar_destroyed", "ship_dead", "ship_wrecked", "ship_dying"],
)
def test_a_destroyed_hangar_or_ship_cancels_the_launches(spawned, destroy):
    """
    Once the hangar or its ship is destroyed, what is left to launch is
    cancelled, and new requests are cancelled straight away.
    """
    game, ship = make_game_and_ship()
    hangar = make_hangar(game, ship)
    order = hangar.launch("tie-fighter", 3)
    hangar.update()  # one fighter out

    destroy(hangar, ship)
    run(game, hangar, until_s=10.0)

    assert len(spawned) == 1
    assert order.cancelled and order.done
    assert not hangar.is_operational
    assert hangar.launch("tie-fighter", 2).cancelled


def test_clean_cancels_the_launches(spawned):
    """Cleaning the hangar cancels what is left to launch."""
    game, ship = make_game_and_ship()
    hangar = make_hangar(game, ship)
    order = hangar.launch("tie-fighter", 3)

    hangar.clean()

    assert order.cancelled
    assert hangar.is_clean
