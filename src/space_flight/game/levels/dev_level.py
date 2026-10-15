"""
A development sandbox level that usually demonstrates the latest implemented
features.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import numpy as np

from space_flight.actors.player import Player
from space_flight.game.scenario import WaveSpec
from space_flight.scenes.scenes import scene_factory
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

# A squadron of fighters, for CPU load profiling.
# What the star destroyer's hangar holds: fighters of each type
ENEMY_CAPITAL_SHIP_HANGAR_STOCK = {
    "tie-fighter": 12,
    "tie-interceptor": 6,
    "tie-bomber": 6,
}

# A debug ion loadout
ION_LOADOUT = replace(default_loadout("a-wing"), lasers=ION).with_ordnance(
    concussion_missile=0,
    ion_missile=6,
    rocket=0,
    ion_torpedo=6,
    proton_torpedo=0,
    ion_bomb=6,
)

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
    loadouts={"tie-fighter": ION_LOADOUT},
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
        loadout=ION_LOADOUT,
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
    m.objective("Keep the frigate alive", failed=frigate.all_destroyed)
    yield from m.wait(5)
    hangar = capital_ship.pawns()[0].hangars[0]
    hangar.set_stock(ENEMY_CAPITAL_SHIP_HANGAR_STOCK)
    m.hud("TIEs launching")
    squadron = m.launch(hangar, "tie-fighter", 3, target=frigate, loadout=ION_LOADOUT)
    m.objective("Destroy the TIE squadron", progress=squadron.destroyed_count, goal=3)
    m.on(squadron.all_destroyed, lambda: m.hud("TIE squadron destroyed"))
    yield from m.wait(20)
    bombers = m.launch(hangar, "tie-bomber", 6, target=frigate, loadout=ION_LOADOUT)
    m.objective(
        "Shoot down 2 TIEs yourself",
        progress=m.kills([squadron, bombers], by_player=True),
        goal=2,
    )
    m.spawn(ENEMY_FIGHTER_SQUADRON)
    # Targets are resolved as each Y-wing spawns: let the big ships spawn first
    # yield from m.wait(1)
    # m.spawn(ALLIED_PATROL, target=[frigate, capital_ship])
