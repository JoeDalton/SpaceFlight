"""
The intro level: escort a convoy of transports past an enemy blockade.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from space_flight.actors.player import Player
from space_flight.game.scenario import WaveSpec
from space_flight.game.scenario.conditions import all_of, any_of, reached_waypoint
from space_flight.scenes.scenes import scene_factory

if TYPE_CHECKING:
    from collections.abc import Iterator

    from space_flight.game.flight_state import FlightState
    from space_flight.game.scenario import Mission

# Orientations are quaternions (w, x, y, z).
FACING_NORTH = [1, 0, 0, 0]
FACING_SOUTH = [0, 0, 0, 1]

TRANSPORTS = WaveSpec(
    name="transports",
    ship_model="cr-90",  # or gr-75
    size=3,
    bot_type="capital_ship",
    team=1,
    spawn_point=[0, -2000, 200],
    spawn_orientation=FACING_NORTH,
    formation="arrowhead",
    formation_scale_m=150,
    waypoints=[
        [0, 0, 200],
        [0, 3000, 200],
        [500, 4000, 200],
        [1000, 4500, 200],
        [2000, 5000, 200],
        [5000, 5000, 200],
        [6000, 4500, 200],
        [6500, 4000, 200],
        [7000, 3000, 200],
    ],
)
# The convoy is past the blockade once it reaches its last waypoint.
CONVOY_LAST_WAYPOINT = len(TRANSPORTS.waypoints) - 1

ESCORT = WaveSpec(
    name="escort",
    ship_model="x-wing",
    size=6,
    team=1,
    spawn_point=[200, -2100, 300],
    spawn_orientation=FACING_NORTH,
    formation="arrowhead",
    # Flies alongside the convoy: 200m to its right, 100m above.
    waypoints=[[x + 200, y, z + 100] for x, y, z in TRANSPORTS.waypoints],
)

FIRST_WAVE = WaveSpec(
    name="first_wave",
    ship_model="tie-bomber",
    size=5,
    spawn_point=[300, 6000, 500],
    spawn_orientation=FACING_SOUTH,
    formation="arrowhead",
    waypoints=[[300, 0, 500], [300, -6000, 500]],
)

SECOND_WAVE = WaveSpec(
    name="second_wave",
    ship_model="tie-interceptor",
    size=5,
    spawn_point=[300, 6300, 800],
    spawn_orientation=FACING_SOUTH,
    formation="diamond",
    waypoints=[[300, 0, 500], [300, -6000, 500]],
)

THIRD_WAVE = WaveSpec(
    name="third_wave",
    ship_model="tie-bomber",
    size=8,
    spawn_point=[300, 0, 800],
    spawn_orientation=FACING_SOUTH,
    formation="diamond",
    waypoints=[[300, 6000, 500], [300, 0, 500]],
)


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

    Three timed waves, plus reactive rules registered up front (they must
    hold wherever the timed sequence currently is): reinforcements once the
    first wave is wiped, and the win/lose conditions on the convoy.

    :param m: The level's :class:`Mission`
    """
    # Handles first, so the rules below can refer to waves not spawned yet.
    transports = m.wave(TRANSPORTS)
    escort = m.wave(ESCORT)
    first_wave = m.wave(FIRST_WAVE)
    second_wave = m.wave(SECOND_WAVE)
    third_wave = m.wave(THIRD_WAVE)

    # --- reactive rules, live for the whole mission --------------------------

    # Reinforcements at 200s, or 3s after the first wave is wiped -- whichever
    # comes first, and only once.
    def spawn_third_wave() -> None:
        m.hud("Enemy reinforcements detected!")
        third_wave.spawn(target=transports)

    m.on(any_of(m.after(200), m.delay(first_wave.all_destroyed, 3)), spawn_third_wave)

    # Won once the convoy reaches its last waypoint and wave 2 is gone.
    blockade_past = all_of(
        reached_waypoint(transports, CONVOY_LAST_WAYPOINT), second_wave.all_destroyed
    )
    m.on(blockade_past, lambda: m.hud("Convoy past the blockade — well done."))
    m.on(
        m.delay(blockade_past, 3),
        lambda: m.victory("The convoy reached the fleet. Mission accomplished."),
    )

    m.on(
        transports.any_destroyed,
        lambda: m.speech(
            "A transport has been destroyed! Focus fire on the bombers!",
            speaker="Red Leader",
            display_time_s=5,
        ),
    )
    m.on(
        transports.all_destroyed,
        lambda: m.speech(
            "All transports have been destroyed. Let's retreat!",
            speaker="Red Leader",
            display_time_s=5,
        ),
    )
    m.on(
        m.delay(transports.all_destroyed, 3),
        lambda: m.defeat("The convoy has been destroyed."),
    )

    # --- the timed waves ------------------------------------------------------
    yield from m.wait(0.1)
    transports.spawn()

    yield from m.wait(0.9)  # total: 1s
    escort.spawn()
    m.speech("Red squadron standing by.", speaker="Red Leader", display_time_s=5)

    yield from m.wait(9)  # total: 10s
    m.hud("First wave")
    first_wave.spawn(target=transports)

    yield from m.wait(20)  # total: 30s
    m.hud("Second wave")
    second_wave.spawn(target=escort)
