"""
A development sandbox level that usually demonstrates the latest implemented
features.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from space_flight.actors.player import Player
from space_flight.game.scenario import WaveSpec
from space_flight.scenes.scenes import scene_factory

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
)

# A squadron of fighters, for CPU load profiling.
ENEMY_FIGHTER_SQUADRON = WaveSpec(
    name="enemy_fighter_squadron",
    ship_model="tie-fighter",
    size=17,
    bot_type="fighter",
    team=2,
    spawn_point=[-300, -1500, 500],
    spawn_orientation=[1, 0, 0, 0],
    record=True,
    formation="arrowhead",
    waypoints=PATROL_ROUTE,
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
    game.player = Player(
        game=game,
        ship_type="a-wing",
        # ship_type="x-wing",
        # ship_type="y-wing",
        # ship_type="tie-interceptor",
        # ship_type="tie-fighter",
        # ship_type="tie-bomber",
        ini_position=np.array([100, -1500, 505]),
        is_neutral=True,
        has_ai=False,
        record=True,
    )
    # `asteroids` or `lava_planet` or `ocean_planet` or `debug`
    game.scene = scene_factory(game=game, scene_name="lava_planet")
    game.scene.build_upfront()


def dev_mission(m: Mission) -> Iterator[None]:
    """
    The dev sandbox's mission body

    :param m: The level's :class:`Mission`
    """
    yield from m.wait(2)
    m.hud("Enemy forces inbound")
    capital_ship = m.spawn(ENEMY_CAPITAL_SHIP)
    frigate = m.spawn(ALLIED_FRIGATE, target=[capital_ship])
    print(frigate)
    # m.spawn(ENEMY_FIGHTER_SQUADRON)
    # Targets are resolved as each Y-wing spawns: let the big ships spawn first
    # yield from m.wait(1)
    # m.spawn(ALLIED_PATROL, target=[frigate, capital_ship])
