"""
A development sandbox level that usually demonstrates the latest implemented
features.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from space_flight.game.levels.common import build_upfront
from space_flight.game.scenario import WaveSpec
from space_flight.weapons import ION
from space_flight.weapons.loadout import default_loadout

if TYPE_CHECKING:
    from collections.abc import Iterator

    from space_flight.game.flight_state import FlightState
    from space_flight.game.scenario import Mission

# A loop around the origin, shared by both waves below.
PATROL_ROUTE = [
    [0, 0, 500],
    [200, 1000, 500],
    [500, 2000, 500],
    [1000, 3000, 500],
    [1000, 2000, 500],
    [500, 1000, 500],
    [0, 0, 500],
    [-200, -1000, 500],
    [-500, -2000, 500],
    [-1000, -3000, 500],
    [-1000, -2000, 500],
    [-500, -1000, 500],
    [0, 0, 500],
]

# A lone allied CR-90 frigate. It carries a bot-controlled turret on its hull
# (declared in the ship config), which spawns and fights along with it.
ALLIED_FRIGATE = WaveSpec(
    name="allied_frigate",
    ship_model="cr-90",
    size=1,
    bot_type="major_ship",
    team=1,
    spawn_point=[0, -1500, 500],
    spawn_orientation=[1, 0, 0, 0],
    record=True,
    waypoints=PATROL_ROUTE,
    hyperspace=False,  # already on stage when the level starts
)

# An enemy Imperial Star Destroyer: a scripted capital ship that only patrols
# its racetrack (no tactician, no collision avoidance). Its turn radius is
# close to a kilometre, hence the wide route.
ENEMY_CAPITAL_SHIP = WaveSpec(
    name="enemy_isd",
    ship_model="isd",
    size=1,
    bot_type="major_ship",
    team=2,
    spawn_point=[0, 1000, 900],
    spawn_orientation=[1, 0, 0, 0],
    record=True,
    waypoints=[
        [3000, 5000, 900],
        [1000, 5000, 900],
        [1000, -3000, 900],
        [3000, -3000, 900],
    ],
    hyperspace=False,  # already on stage when the level starts
)

# A debug ion loadout
ION_LOADOUT = replace(default_loadout("a-wing"), lasers=ION).with_ordnance(
    concussion_missile=0,
    ion_missile=6,
    rocket=0,
    ion_torpedo=6,
    proton_torpedo=0,
    ion_bomb=6,
)

# The player's squadron: it drops in behind the player, then follows its lead,
# through its local warps too (see WarpEscort)
PLAYER_SQUADRON = WaveSpec(
    name="player_squadron",
    ship_model="x-wing",
    size=4,
    bot_type="fighter",
    team=1,
    spawn_point=[100, -1800, 505],
    spawn_orientation=[1, 0, 0, 0],
    formation="arrowhead",
)

# An allied Y-wing patrol, given the enemy big ships as primary targets (see
# dev_mission) to have it bomb and torpedo them.
ALLIED_PATROL = WaveSpec(
    name="allied_patrol",
    ship_model="y-wing",
    size=10,
    bot_type="fighter",
    team=1,
    spawn_point=[0, -2100, 500],
    spawn_orientation=[1, 0, 0, 0],
    record=True,
    formation="arrowhead",
    waypoints=[[0, 50000, 500]] + PATROL_ROUTE[1:],
)


def build_dev_upfront(game: FlightState):
    """
    Build the heavy, up-front part of the level — run synchronously on a black
    screen BEFORE the hyperspace animation starts.

    :param game: The game/flight state
    """
    build_upfront(
        game,
        # `asteroids` or `lava_planet` or `solar_system` or `debug`
        scene_name="lava_planet",
        player_ship_type="a-wing",
        # player_ship_type="x-wing",
        # player_ship_type="y-wing",
        # player_ship_type="tie-interceptor",
        # player_ship_type="tie-fighter",
        # player_ship_type="tie-bomber",
        player_position=[100, -1500, 505],
        player_record=True,
        player_loadout=ION_LOADOUT,
    )


def dev_mission(m: Mission) -> Iterator[None]:
    """
    The dev sandbox's mission body

    :param m: The level's :class:`Mission`
    """
    squadron = m.spawn(PLAYER_SQUADRON)
    yield from m.wait_until(lambda: len(squadron.pawns()) == PLAYER_SQUADRON.size)
    squadron.follow(m.game.player)
    m.hud("Your squadron is with you: it follows you, even through hyperspace")
    yield from m.wait(2)
    m.hud("Enemy forces inbound")
    capital_ship = m.spawn(ENEMY_CAPITAL_SHIP)
    frigate = m.spawn(ALLIED_FRIGATE, target=[capital_ship])
    m.objective("Keep the frigate alive", failed=frigate.all_destroyed)
    # Targets are resolved as each Y-wing spawns: let the big ships spawn first
    # yield from m.wait(1)
    # m.spawn(ALLIED_PATROL, target=[frigate, capital_ship])
