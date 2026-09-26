"""
The tutorial race level: the player and three friendly rivals race through a
series of checkpoints in an asteroid field.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from space_flight.actors.player import Player
from space_flight.game.scenario import Scenario
from space_flight.game.scenario.conditions import near
from space_flight.game.scenario.loader import load_waves
from space_flight.game.scenario.mission import Mission
from space_flight.scenes.scenes import scene_factory

if TYPE_CHECKING:
    from collections.abc import Iterator

    from space_flight.game.flight_state import FlightState

# The course (shared by the player and the rivals).
FINISH_POINT = [-3000, 12000, 500]
CHECKPOINT_RADIUS_M = 350


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


def race_mission(m: Mission) -> Iterator[None]:
    """
    The race's mission body: start the rivals and the player's guide route,
    have them razz the player at each checkpoint, then end the level for
    whoever crosses the finish line first.

    The checkpoint banter and the finish are registered as reactive rules
    (:meth:`Mission.on`) rather than sequenced with ``yield from``, since they
    can happen in any order relative to each other and to the main sequence
    below (the player might reach a checkpoint before or after this body has
    even finished spawning the rivals).

    :param m: The level's :class:`Mission`
    """
    yield from m.wait(1)
    m.hud("RACE — first to the finish wins!")
    rivals = m.spawn(m.waves["rivals"])
    m.speech("Last one to the finish buys the drinks!", speaker="Wedge")
    # Guide the player through the course with targetable waypoint spheres.
    m.player_waypoints(
        [
            [0, 2000, 500],
            [3000, 4000, 600],
            [3000, 8000, 500],
            [-1000, 10000, 600],
            FINISH_POINT,
        ]
    )

    # --- friendly banter as the player passes each checkpoint --------------
    m.on(
        near("player", [0, 2000, 500], CHECKPOINT_RADIUS_M),
        lambda game: m.speech("Not bad, rookie. Now try to keep up!", speaker="Hobbie"),
        name="cp1",
    )
    m.on(
        near("player", [3000, 4000, 600], CHECKPOINT_RADIUS_M),
        lambda game: m.speech(
            "Mind the rocks — they don't move for anyone.", speaker="Wedge"
        ),
        name="cp2",
    )
    m.on(
        near("player", [3000, 8000, 500], CHECKPOINT_RADIUS_M),
        lambda game: m.speech("Hey, you're actually gaining on us!", speaker="Janson"),
        name="cp3",
    )
    m.on(
        near("player", [-1000, 10000, 600], CHECKPOINT_RADIUS_M),
        lambda game: m.speech("Final stretch! Don't get cocky now.", speaker="Wedge"),
        name="cp4",
    )

    # --- finish: whoever crosses first ends the race -----------------------
    # The player's win is registered first, so a simultaneous cross goes to
    # the player (Mission.update fires triggers in registration order).
    m.on(
        near("player", FINISH_POINT, CHECKPOINT_RADIUS_M),
        lambda game: m.victory(
            "You crossed the line first! Drinks are on the rest of the squadron."
        ),
        name="player_finish",
    )
    m.on(
        near(rivals.name, FINISH_POINT, CHECKPOINT_RADIUS_M),
        lambda game: m.defeat(
            "A rival beat you to the finish. Better luck next time, rookie."
        ),
        name="rival_finish",
    )


def build_race_level(game: FlightState) -> Iterator[str]:
    """
    Build the tutorial race level.

    The player and three friendly rivals race through a string of checkpoints in
    an asteroid field. Everyone is on the same team — a friendly contest with
    plenty of radio teasing. The rivals, the win/lose conditions, and the banter
    are all scripted in Python via :func:`race_mission`; this builder only sets
    up the player, the scene, and the mission's wave data.

    :param game: The game/flight state
    """
    # Rest of the scene (skybox, planet, lights, dust, ...)
    yield from game.scene.build_decomposed()

    # Wave data (sizes, ship models, spawn points, ...) lives in the sibling
    # YAML; the mission's actual sequence of events is written in Python
    # above, via the Mission API (see docs/source/scenario_scripting.md).
    game.scenario = Scenario()
    mission = Mission(game)
    mission.waves = load_waves(Path(__file__).with_suffix(".yaml"))
    game.scenario.schedule(race_mission(mission))
    yield "scenario"
