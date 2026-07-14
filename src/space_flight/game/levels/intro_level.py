"""
The intro level: escort a convoy of transports past an enemy blockade.

Built in two phases — :func:`build_intro_upfront` (heavy work, on a black screen)
and :func:`build_intro_level` (the rest, incrementally during the hyperspace
animation) — with the scripted events defined in the sibling YAML scenario.
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


def build_intro_upfront(game: FlightState) -> None:
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
        ini_position=np.array([0, -2600, 250]),
        is_neutral=False,
        has_ai=False,
    )
    # `asteroids` or `lava_planet` or `ocean_planet` or `debug`
    game.scene = scene_factory(game=game, scene_name="ocean_planet")
    game.scene.build_upfront()


def build_intro_level(game: FlightState) -> Iterator[str]:
    """
    A generator that builds the rest of the level one step at a time, DURING the
    hyperspace animation. Each yield hands control back to the render loop so
    the animation keeps playing; the loading overlay advances it once per frame.

    Assumes :func:`build_intro_upfront` has already created the player and the
    scene and built the scene's heavy objects.

    :param game: The game/flight state
    :return: A generator yielding a label for each build step
    """
    # Rest of the scene (skybox, planet, lights, dust, ...)
    yield from game.scene.build_decomposed()

    """
    Initialize scenario
    """
    # Mission events (waves, objectives) are defined declaratively in the
    # sibling YAML and driven by the generic scenario engine. The standing
    # groups built above are registered by name so triggers can reference them.
    game.scenario = load_scenario(Path(__file__).with_suffix(".yaml"))
    # game.scenario.register(name="transports", bots=game.transport_bots)
    # game.scenario.register(name="escort", bots=game.escort_bots)
    yield "scenario"
