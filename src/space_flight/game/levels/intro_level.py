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
from space_flight.game.scenario import Scenario
from space_flight.game.scenario.conditions import (
    AllOf,
    AnyOf,
    Delay,
    after_seconds,
    all_destroyed,
    any_destroyed,
    fired,
    reached_waypoint,
)
from space_flight.game.scenario.loader import load_waves
from space_flight.game.scenario.mission import Mission
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


def intro_mission(m: Mission) -> Iterator[None]:
    """
    The intro level's mission body: escort a convoy of transports past an
    enemy blockade.

    Reproduces the original three timed waves, then two chained events
    (reinforcements after the first wave is wiped, and a win condition on
    escort progress). The chained/conditional rules (third_wave, blockade_past,
    victory, transport_destroyed, all_transports_destroyed, defeat) are
    registered up front as reactive rules via :meth:`Mission.on` -- they must
    hold throughout the mission regardless of where the sequential part below
    currently is, since e.g. the first wave could be wiped out before or after
    the second wave even arrives. The three timed waves are purely
    time-sequenced, so they are simply waited out in order.

    :param m: The level's :class:`Mission`
    """
    # --- chained / reactive rules, live for the whole mission ---------------

    # The third wave arrives either at 200s OR 3s after the first wave is
    # wiped, whichever comes first -- and only once, because a single trigger
    # owns a single one-shot guard (two triggers pointing at one wave would
    # double-spawn it).
    def _spawn_third_wave(game) -> None:
        m.hud("Enemy reinforcements detected!")
        m.spawn(m.waves["third_wave"])

    m.on(
        AnyOf(after_seconds(200), Delay(all_destroyed("first_wave"), seconds=3)),
        _spawn_third_wave,
        name="third_wave",
    )

    # Mission won once the convoy reaches its final waypoint (index 8, the
    # last of its 9-waypoint route) and wave 2 is gone.
    m.on(
        AllOf(reached_waypoint("transports", 8), all_destroyed("second_wave")),
        lambda game: m.hud("Convoy past the blockade — well done."),
        name="blockade_past",
    )
    m.on(
        Delay(fired("blockade_past"), seconds=3),
        lambda game: m.victory("The convoy reached the fleet. Mission accomplished."),
        name="victory",
    )

    # Warning when the first transport is destroyed.
    m.on(
        any_destroyed("transports"),
        lambda game: m.speech(
            "A transport has been destroyed! Focus fire on the bombers!",
            speaker="Red Leader",
            display_time_s=5,
        ),
        name="transport_destroyed",
    )

    # Mission lost if all transports are destroyed.
    m.on(
        all_destroyed("transports"),
        lambda game: m.speech(
            "All transports have been destroyed. Let's retreat!",
            speaker="Red Leader",
            display_time_s=5,
        ),
        name="all_transports_destroyed",
    )
    m.on(
        Delay(fired("all_transports_destroyed"), seconds=3),
        lambda game: m.defeat("The convoy has been destroyed."),
        name="defeat",
    )

    # --- the original timed waves, purely sequential -------------------------
    yield from m.wait(0.1)
    m.spawn(m.waves["transports"])

    yield from m.wait(0.9)  # total: 1.0s
    m.spawn(m.waves["escort"])
    m.speech("Red squadron standing by.", speaker="Red Leader", display_time_s=5)

    yield from m.wait(9)  # total: 10s
    m.hud("First wave")
    m.spawn(m.waves["first_wave"])

    yield from m.wait(20)  # total: 30s
    m.hud("Second wave")
    m.spawn(m.waves["second_wave"])


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
    # Wave data (sizes, ship models, spawn points, ...) lives in the sibling
    # YAML; the mission's actual sequence of events is written in Python
    # above, via the Mission API (see docs/source/scenario_scripting.md).
    game.scenario = Scenario()
    mission = Mission(game)
    mission.waves = load_waves(Path(__file__).with_suffix(".yaml"))
    game.scenario.schedule(intro_mission(mission))
    yield "scenario"
