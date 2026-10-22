"""
A WorldBuilder planet under the level: its spherical terrain, drawn (and
detailed) around the player.

The planet is WorldBuilder's as is: its centre sits straight below the world
origin, so sea level is at z = 0 there, like the flat ocean's. SpaceFlight's
flat world frame is the planet's frame shifted by one radius: the ground under
the origin is the planet's +z pole. Away from the origin the surface drops
below z = 0 (about 80 m at 10 km on a 600 km planet), which the flat flight
model ignores.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Generator
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from world_builder.terrain.level import load_level
from world_builder.terrain.terrain import Terrain

if TYPE_CHECKING:
    from space_flight.game.flight_state import FlightState

LOGGER = logging.getLogger(__name__)

# The ground counts as loaded once Terrain.loading has stayed False this long:
# it turns on briefly whenever detail refines, so one quiet frame is not enough.
GROUND_QUIET_S = 0.5
# Give up waiting for the ground after this long (and say so)
GROUND_TIMEOUT_S = 60.0


class PlanetSurface:
    """
    The terrain of a WorldBuilder level file (its planet, stamps and paints),
    built with the player's terrain quality settings.

    :ivar terrain: The WorldBuilder terrain, under render
    """

    def __init__(
        self,
        game: FlightState,
        level_path: Path,
        sun_direction: np.ndarray,
    ):
        """
        :param game: The game/flight state
        :param level_path: The WorldBuilder level file (YAML)
        :param sun_direction: Toward the sun, in the world frame
        """
        spec, _camera_pose = load_level(level_path)
        world = game.app.graphics_settings.world_settings()
        # Under render, not root_node: the terrain rebases itself around the
        # player in float64 (see update)
        self.terrain = Terrain(
            game.app.render,
            spec,
            position=(0.0, 0.0, -spec.radius),
            sun_direction=sun_direction,
            settings=world.settings_for(Terrain),
        )
        # No swell ocean: the terrain draws the sea itself
        self.terrain.set_sea_surface(True)

    @property
    def loading(self) -> bool:
        """True while the last level-of-detail pass still wanted chunks."""
        return self.terrain.loading

    def update(self, player_position: np.ndarray):
        """
        Place the terrain around the player, and refine it there. Call once
        per frame, after the render origin was moved onto the player.

        :param player_position: The player's world position (float64), at the
            render origin
        """
        self.terrain.update(player_position)

    def wait_until_loaded(
        self,
        player_position: np.ndarray,
        clock: Callable[[], float] = time.monotonic,
    ) -> Generator[str, None, None]:
        """
        Load the ground around the player: update the terrain once per step
        until it has stopped loading for :data:`GROUND_QUIET_S` (ground not
        drawn yet is not solid), or for at most :data:`GROUND_TIMEOUT_S`.

        :param player_position: The player's world position
        :param clock: Real time, in seconds (the game is paused while loading)
        :return: A generator to advance once per frame
        """
        start = clock()
        quiet_since = None
        while True:
            self.update(player_position)
            now = clock()
            if self.loading:
                quiet_since = None
            elif quiet_since is None:
                quiet_since = now
            elif now - quiet_since >= GROUND_QUIET_S:
                return
            if now - start >= GROUND_TIMEOUT_S:
                LOGGER.warning(
                    f"Ground still loading after {GROUND_TIMEOUT_S:.0f} s: "
                    "starting anyway"
                )
                return
            yield "ground"

    def clean(self):
        """Remove the terrain and stop its workers."""
        self.terrain.destroy()
        self.terrain = None
