"""
The chart a level is written on, placed in the world.

A level wants to say "2 km north of the coast, 1200 m up", not a position in
the world's axes. WorldBuilder's planets are never rotated, so a place on a
planet is not at the world's +z pole and its east, north and up are not the
world's x, y and z. A :class:`LevelFrame` converts between the two for one
planet.

What the frame is made of, all from the planet's body in the world file:

- **The reference point**: the planet's ``reference_lat`` and ``reference_lon``.
  It is the chart's origin, at sea level. Its east, north and up are the
  chart's x, y and z.
- **The radius**: ``PlanetSpec.radius``, which makes chart distances arcs of
  the sphere.
- **The centre**: the body's ``position`` in the world file. The frame does
  not choose it: a planet moved in the file carries the whole chart with it.

Changing planet (another body, or another planet in the body's file) changes
all three: the chart's origin is wherever the new planet's reference point is,
and the same chart positions are then another place, on another ground. A
level's positions stay meaningful only while that place suits them (the
Mission 3 tests check its routes clear the ground).
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import quaternion
from world_builder.terrain.chart import AzimuthalEquidistantChart, TangentFrame
from world_builder.terrain.planet import PlanetSpec
from world_builder.world import BodyLook


class LevelFrame:
    """
    :ivar radius: The planet's radius, metres
    :ivar east: World unit vector toward chart +x at the reference point
    :ivar north: World unit vector toward chart +y at the reference point
    :ivar up: World unit vector up at the reference point
    :ivar centre: The planet's centre, world position
    """

    @classmethod
    def of(cls, body: BodyLook) -> LevelFrame:
        """
        :param body: A body of a world file (see ``parse_world``)
        :return: The chart of its planet, around the position the file gives it
        """
        return cls(body.spec, centre=body.position)

    def __init__(self, spec: PlanetSpec, centre: Sequence[float]):
        """
        :param spec: The planet: its reference point and radius
        :param centre: The planet's centre in the world, metres
        """
        self.radius = float(spec.radius)
        self._chart = AzimuthalEquidistantChart(
            spec.reference_lat, spec.reference_lon, self.radius
        )
        frame: TangentFrame = self._chart.frame
        self.east, self.north, self.up = frame.east, frame.north, frame.up
        self.centre = np.asarray(centre, dtype=float)

    def position(self, x: float, y: float, z: float = 0.0) -> np.ndarray:
        """
        :param x: Chart metres east of the reference point
        :param y: Chart metres north of the reference point
        :param z: Altitude above sea level, metres
        :return: The world position
        """
        direction = self._chart.to_dirs(x, y)[0]
        return (self.radius + z) * direction + self.centre

    def vector(self, east: float, north: float, up: float) -> np.ndarray:
        """
        :return: A (east, north, up) vector at the reference point, in world
            axes
        """
        return east * self.east + north * self.north + up * self.up

    def up_at(self, position: Sequence[float]) -> np.ndarray:
        """:return: The unit vector away from the planet's centre"""
        radial = np.asarray(position, dtype=float) - self.centre
        return radial / np.linalg.norm(radial)

    def orientation(
        self, position: Sequence[float], toward: Sequence[float]
    ) -> np.ndarray:
        """
        A level orientation: nose along the horizontal direction toward a
        point, +z away from the planet. (Ship bodies are x right, y forward,
        z up.)

        :param position: The world position
        :param toward: A world position (not straight above or below)
        :return: The orientation quaternion (w, x, y, z)
        """
        up = self.up_at(position)
        offset = np.asarray(toward, dtype=float) - np.asarray(position, dtype=float)
        forward = offset - np.dot(offset, up) * up
        forward /= np.linalg.norm(forward)
        right = np.cross(forward, up)
        return quaternion.as_float_array(
            quaternion.from_rotation_matrix(np.column_stack((right, forward, up)))
        )
