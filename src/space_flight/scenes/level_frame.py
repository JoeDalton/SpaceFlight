"""
The world frame of a level built on a WorldBuilder level file.

The file's chart is flat metres (x east, y north) around its reference point;
WorldBuilder's planets are never rotated, so that point is not at the world's
+z pole. The frame puts the planet so the reference point's sea level is the
world origin, and converts chart coordinates (and altitudes above sea level)
to world positions and orientations, so a level can be written on the chart.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import quaternion
from world_builder.terrain.chart import AzimuthalEquidistantChart, TangentFrame
from world_builder.terrain.planet import PlanetSpec


class LevelFrame:
    """
    :ivar radius: The planet's radius, metres
    :ivar east: World unit vector toward chart +x at the reference point
    :ivar north: World unit vector toward chart +y at the reference point
    :ivar up: World unit vector up at the reference point
    :ivar centre: The planet's centre, world position
    """

    def __init__(self, spec: PlanetSpec):
        """
        :param spec: The level's planet (see load_level)
        """
        self.radius = float(spec.radius)
        self._chart = AzimuthalEquidistantChart(
            spec.reference_lat, spec.reference_lon, self.radius
        )
        frame: TangentFrame = self._chart.frame
        self.east, self.north, self.up = frame.east, frame.north, frame.up
        self.centre = -self.radius * self.up

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
