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

# A lone enemy CR-90 frigate. It carries a bot-controlled turret on its hull
# (declared in the ship config), which spawns and fights along with it.
ENEMY_FRIGATE = WaveSpec(
    name="enemy_frigate",
    ship_model="cr-90",
    size=1,
    bot_type="capital_ship",
    team=2,
    spawn_point=[0, -1500, 500],
    spawn_orientation=[1, 0, 0, 0],
    record=True,
    waypoints=PATROL_ROUTE,
)

# Not spawned by default: available for trying things out in the sandbox
# (e.g. m.spawn(ALLIED_PATROL, target=frigate) to have it bomb the frigate).
ALLIED_PATROL = WaveSpec(
    name="allied_patrol",
    ship_model="y-wing",
    size=1,
    bot_type="fighter",
    team=1,
    spawn_point=[0, -2100, 500],
    spawn_orientation=[1, 0, 0, 0],
    record=True,
    formation="arrowhead",
    waypoints=[[0, 50000, 500]] + PATROL_ROUTE[1:],
)


def build_dev_upfront(game: FlightState) -> None:
    """
    Build the heavy, up-front part of the level — run synchronously on a black
    screen BEFORE the hyperspace animation starts.

    This is the player plus the scene's GPU-heavy objects (ocean, cloud field),
    whose one-time first-render preparation would otherwise spike a frame in the
    middle of the animation. The player is created here first because the scene's
    ocean reflection camera copies the player camera's lens.

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
        is_neutral=False,
        has_ai=False,
        record=True,
    )
    # `asteroids` or `lava_planet` or `ocean_planet` or `debug`
    game.scene = scene_factory(game=game, scene_name="debug")
    game.scene.build_upfront()


def dev_mission(m: Mission) -> Iterator[None]:
    """
    The dev sandbox's mission body: a lone enemy frigate arrives after a
    couple of seconds. There is no win/lose condition here -- it is a sandbox
    for trying out the latest implemented features, not a scripted mission.

    :param m: The level's :class:`Mission`
    """
    yield from m.wait(2)
    m.hud("Enemy frigate inbound")
    m.spawn(ENEMY_FRIGATE)
