from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np
from panda3d.core import BitMask32

from space_flight import DEBUG_DELETION
from space_flight.game.collisions import CollisionLayers, attach_collision_sphere
from space_flight.utils import magnitude

if TYPE_CHECKING:
    from space_flight.actors.ship import Ship
    from space_flight.game.flight_state import FlightState

LOGGER = logging.getLogger()


class CollisionSensor:
    """
    A bot navigator's collision sensor: 3 look-ahead spheres, centred at
    increasing distances along the ship's forward (+Y) axis, that detect obstacles
    """

    # Game time of the frame whose contacts `obstacles` holds, when recorded
    # through record_obstacle
    _obstacles_time_s = None
    # Whether the spheres take part in collision traversal (see set_active)
    active = True

    def __init__(
        self,
        game: FlightState,
        ship: Ship,
        collision_reference_distance_m: float = 100.0,
        ship_distance_1_m: float = 5,
        radius_1_m: float = 30,
        ship_distance_2_m: float = 50,
        radius_2_m: float = 50,
        ship_distance_3_m: float = 125,
        radius_3_m: float = 100,
    ):
        self.obstacles = []
        self._clock = game.game_time.get_current_time
        self.ship = ship
        self.collision_reference_distance_m = collision_reference_distance_m
        # Spheres are numbered from the innermost (1) to the outermost (3). A
        # navigator can shorten the reach by lowering active_range (a bomb run
        # drops the outer sphere to overfly a big target without being pushed off
        # it; the inner ones remain an anti-crash net). Reset to n_spheres by each
        # navigate().
        self.n_spheres = 3
        self.active_range = self.n_spheres
        self.sphere_1 = attach_collision_sphere(
            game=game,
            name="sensor",
            radius=radius_1_m,
            collider_type="sensor",
            parent_node=ship.node,
            parent_object=self,
            relative_position=[0, ship_distance_1_m, 0],
        )
        self.sphere_1.setPythonTag("owner", self)
        self.sphere_1.setPythonTag("sensor_range", 1)
        self.sphere_2 = attach_collision_sphere(
            game=game,
            name="sensor",
            radius=radius_2_m,
            collider_type="sensor",
            parent_node=ship.node,
            parent_object=self,
            relative_position=[0, ship_distance_2_m, 0],
        )
        self.sphere_2.setPythonTag("owner", self)
        self.sphere_2.setPythonTag("sensor_range", 2)
        self.sphere_3 = attach_collision_sphere(
            game=game,
            name="sensor",
            radius=radius_3_m,
            collider_type="sensor",
            parent_node=ship.node,
            parent_object=self,
            relative_position=[0, ship_distance_3_m, 0],
        )
        self.sphere_3.setPythonTag("owner", self)
        self.sphere_3.setPythonTag("sensor_range", 3)

    def set_active(self, active: bool):
        """
        Include the spheres in collision traversal, or leave them out: an
        inactive sensor costs nothing to traverse and records no contacts (its
        from-mask is empty). Its bot only reads contacts on its think frames.

        :param active: Whether the next traversals should detect obstacles
        """
        if active == self.active:
            return
        mask = CollisionLayers.SENSOR_FROM if active else BitMask32.allOff()
        for sphere in (self.sphere_1, self.sphere_2, self.sphere_3):
            sphere.node().setFromCollideMask(mask)
        self.active = active

    def record_obstacle(self, obstacle: dict):
        """
        Register a contact reported by the collision system this frame.

        Contacts are reported every frame while a sphere overlaps an obstacle,
        but the navigator may only consume them every few frames: keep the
        current frame's contacts only, or each obstacle would be counted once
        per frame since the last compute_repulsion.

        :param obstacle: The contact ("normal", "hit_point", "range")
        """
        now_s = self._clock()
        if now_s != self._obstacles_time_s:
            self.obstacles = []
            self._obstacles_time_s = now_s
        self.obstacles.append(obstacle)

    def compute_repulsion(self) -> tuple[np.ndarray, float]:
        """
        Computes the repulsion vector from this frame's contacts,
        then wipes the recorded obstacles

        :return: The repulsion vector and the repulsion weight
        """
        # Contacts from an earlier frame are gone: nothing touched the sensor
        # since.
        if (
            self._obstacles_time_s is not None
            and self._obstacles_time_s != self._clock()
        ):
            self.obstacles = []
        repulsion_vector = np.zeros(3)
        total_weight = 0.0
        n_contributing = 0
        self_position = self.ship.position

        for obstacle in self.obstacles:
            # Skip obstacles seen only by a sphere beyond the current reach (e.g. the
            # outer sphere while a bomb run has shortened active_range).
            if obstacle.get("range", 1) > self.active_range:
                continue
            # A Panda3D LVector3f: coerce it, since `float * LVector3f` (below,
            # with magnitude()'s plain float weight) is unsupported.
            normal = np.asarray(obstacle["normal"], dtype=float)
            hit_point = obstacle["hit_point"]

            obstacle_direction = hit_point - self_position
            distance_m = magnitude(obstacle_direction)

            if distance_m > 1e-4:
                # Fallback if normal is degenerate
                if magnitude(normal) < 1e-4:
                    normal = obstacle_direction / distance_m
                # Compute obstacle weight
                weight = self.collision_reference_distance_m / distance_m
                repulsion_vector += weight * normal
                total_weight += weight
                n_contributing += 1

        if n_contributing > 0:
            total_weight /= n_contributing

        self.obstacles = []

        if total_weight < 1e-4:
            return np.zeros(3), 0.0

        return repulsion_vector / total_weight, total_weight

    def clean(self):
        """
        Cleans the CollisionSensor object
        """
        self.ship = None
        self.sphere_1.setPythonTag("owner", None)
        self.sphere_1.remove_node()
        self.sphere_1 = None
        self.sphere_2.setPythonTag("owner", None)
        self.sphere_2.remove_node()
        self.sphere_2 = None
        self.sphere_3.setPythonTag("owner", None)
        self.sphere_3.remove_node()
        self.sphere_3 = None
        self.obstacles = None
        if DEBUG_DELETION:
            LOGGER.info("Cleaned CollisionSensor")

    def __del__(self):
        if DEBUG_DELETION:
            LOGGER.info("Deleted CollisionSensor")
