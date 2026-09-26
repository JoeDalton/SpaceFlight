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
# Where the convoy turns east along the coast, about halfway.
CONVOY_HALFWAY_WAYPOINT = 4

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
        m.speech(
            "More bombers, eight of them, dropping out of the clouds!",
            speaker="Red Two",
        )
        third_wave.spawn(target=transports)

    m.on(any_of(m.after(200), m.delay(first_wave.all_destroyed, 3)), spawn_third_wave)

    # Won once the convoy reaches its last waypoint and wave 2 is gone.
    blockade_past = all_of(
        reached_waypoint(transports, CONVOY_LAST_WAYPOINT), second_wave.all_destroyed
    )

    def on_blockade_past() -> None:
        m.hud("Convoy past the blockade — well done.")
        m.speech(
            "We're through! Thank you, Red squadron. We owe you one.",
            speaker="Convoy Lead",
        )

    m.on(blockade_past, on_blockade_past)
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
        m.delay(transports.any_destroyed, 3),
        lambda: m.speech(
            "We just lost a transport, crew and all. Don't let it happen again!",
            speaker="Convoy Lead",
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

    # --- combat chatter -------------------------------------------------------
    m.on(
        first_wave.any_destroyed,
        lambda: m.speech("Scratch one bomber!", speaker="Red Two"),
    )
    m.on(
        first_wave.all_destroyed,
        lambda: m.speech(
            "That's the last of the first wave. Nice shooting, Red squadron.",
            speaker="Red Leader",
        ),
    )
    m.on(
        second_wave.all_destroyed,
        lambda: m.speech(
            "Interceptors are down! They're off our backs.", speaker="Red Three"
        ),
    )
    m.on(
        third_wave.all_destroyed,
        lambda: m.speech(
            "Bombers cleared! Convoy, you're free to run.", speaker="Red Leader"
        ),
    )
    m.on(
        escort.any_destroyed,
        lambda: m.speech(
            "We've lost one of ours! Close up the gaps, Red squadron.",
            speaker="Red Leader",
        ),
    )
    m.on(
        reached_waypoint(transports, CONVOY_HALFWAY_WAYPOINT),
        lambda: m.speech(
            "Turning east along the coast. Halfway there, keep them off us!",
            speaker="Convoy Lead",
        ),
    )

    # --- the timed waves ------------------------------------------------------
    yield from m.wait(0.1)
    transports.spawn()

    yield from m.wait(0.9)  # total: 1s
    escort.spawn()
    m.speech(
        "Red squadron standing by. Red Seven, that A-wing's the fastest\n"
        "thing we've got: you're our interceptor. Stay near the convoy.",
        speaker="Red Leader",
    )

    yield from m.wait(5)  # total: 6s
    m.speech(
        "Convoy Lead to escort: we're slow, fat and full of medical supplies.\n"
        "We're counting on you.",
        speaker="Convoy Lead",
    )

    yield from m.wait(4)  # total: 10s
    m.hud("First wave")
    first_wave.spawn(target=transports)
    m.speech(
        "Bombers, dead ahead and coming in low! They're after the transports.\n"
        "Red Seven, break and engage!",
        speaker="Red Leader",
    )

    yield from m.wait(20)  # total: 30s
    m.hud("Second wave")
    second_wave.spawn(target=escort)
    m.speech("Interceptors! They're coming for us this time!", speaker="Red Two")
    yield from m.wait(3)
    m.speech(
        "Red Two, Three, with me on the fighters.\n"
        "Seven, keep those bombers off the convoy!",
        speaker="Red Leader",
    )
