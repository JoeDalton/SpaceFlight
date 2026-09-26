"""
A development sandbox level that usually demonstrates the latest implemented
features.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from space_flight.actors.player import Player
from space_flight.game.scenario import Scenario
from space_flight.game.scenario.loader import load_waves
from space_flight.game.scenario.mission import Mission
from space_flight.scenes.scenes import scene_factory

if TYPE_CHECKING:
    from collections.abc import Iterator

    from space_flight.game.flight_state import FlightState


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
    # Spawn the frigate first so any later ally can take it as a primary
    # target.
    yield from m.wait(2)
    m.hud("Enemy frigate inbound")
    m.spawn(m.waves["enemy_frigate"])

    # The wave data for an allied patrol (m.waves["allied_patrol"]) is also
    # available here for whoever is using this sandbox to bring in a second,
    # friendly wave a beat later, via the same m.wait / m.hud / m.spawn / m.speech
    # calls used above.


def build_dev_level(game: FlightState) -> Iterator[str]:
    """
    Build the development sandbox level.

    :param game: The game/flight state
    """
    # Rest of the scene (skybox, planet, lights, dust, star destroyer)
    yield from game.scene.build_decomposed()

    # Wave data (sizes, ship models, spawn points, ...) lives in the sibling
    # YAML; the mission's actual sequence of events is written in Python
    # below, via the Mission API (see docs/source/scenario_scripting.md).
    game.scenario = Scenario()
    mission = Mission(game)
    mission.waves = load_waves(Path(__file__).with_suffix(".yaml"))
    game.scenario.schedule(dev_mission(mission))
    yield "scenario"
