"""
The tutorial race level: the player and three friendly rivals race through a
series of checkpoints in an asteroid field.
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


def build_race_upfront(game: FlightState) -> None:
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
        ship_type="x-wing",
        ini_position=np.array([0, -600, 550]),
        is_neutral=False,
        has_ai=False,
    )

    # Asteroids double as race obstacles.
    game.scene = scene_factory(game=game, scene_name="lava_planet")
    game.scene.build_upfront()


def build_race_level(game: FlightState) -> Iterator[str]:
    """
    Build the tutorial race level.

    The player and three friendly rivals race through a string of checkpoints in
    an asteroid field. Everyone is on the same team — a friendly contest with
    plenty of radio teasing. The rivals, the win/lose conditions, and the banter
    are all driven by the sibling YAML scenario; this builder only sets up the
    player and the scene.

    :param game: The game/flight state
    """
    # Rest of the scene (skybox, planet, lights, dust, ...)
    yield from game.scene.build_decomposed()

    # Mission events (waves, objectives) are defined declaratively in the
    # sibling YAML and driven by the generic scenario engine. The standing
    # groups built above are registered by name so triggers can reference them.
    game.scenario = load_scenario(Path(__file__).with_suffix(".yaml"))
    yield "scenario"
