"""
A development sandbox level that usually demonstrates the latest implemented
features.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from space_flight.actors.player import Player
from space_flight.game.scenario.loader import load_scenario
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
        # ship_type="a-wing",
        # ship_type="x-wing",
        ship_type="y-wing",
        # ship_type="tie-interceptor",
        # ship_type="tie-fighter",
        # ship_type="tie-bomber",
        ini_position=np.array([100, -1500, 505]),
        is_neutral=True,
        has_ai=False,
        record=True,
    )
    # `asteroids` or `lava_planet` or `ocean_planet` or `debug`
    game.scene = scene_factory(game=game, scene_name="debug")
    game.scene.build_upfront()


def build_dev_level(game: FlightState) -> Iterator[str]:
    """
    Build the development sandbox level.

    :param game: The game/flight state
    """
    # Rest of the scene (skybox, planet, lights, dust, star destroyer)
    yield from game.scene.build_decomposed()

    # Mission events (waves, objectives) are defined declaratively in the
    # sibling YAML and driven by the generic scenario engine. The standing
    # groups built above are registered by name so triggers can reference them.
    game.scenario = load_scenario(Path(__file__).with_suffix(".yaml"))
    yield "scenario"
