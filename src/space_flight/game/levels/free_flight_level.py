"""
Mission 3: Escort -- escort a convoy of transports past an
enemy blockade.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from space_flight.game.levels.common import build_upfront

if TYPE_CHECKING:
    from collections.abc import Iterator

    from space_flight.game.flight_state import FlightState
    from space_flight.game.scenario import Mission


PLAYER_POSITION = [0, -2600, 250]


def build_free_flight_upfront(game: FlightState):
    """
    Build the heavy, up-front part of the level — run synchronously on a black
    screen BEFORE the hyperspace animation starts.

    This is the player plus the scene's terrain (shaders, textures, worker
    processes); its ground is loaded during the animation. The whole mission
    flies over the shallow sea of the earth-like demo world.

    :param game: The game/flight state
    """
    build_upfront(
        game,
        scene_name="earthlike_planet",
        player_ship_type="a-wing",
        player_position=PLAYER_POSITION,
    )


def free_flight_mission(m: Mission) -> Iterator[None]:
    """
    The mission3 level's mission body.

    Two timed waves, plus reactive rules registered up front (they must hold
    wherever the timed sequence currently is): a third wave at 200s or once
    the first wave is wiped, and the win/lose conditions on the convoy.

    :param m: The level's :class:`Mission`
    """
    yield from m.wait(2.5)
    m.hint("Explore the world freely!")
