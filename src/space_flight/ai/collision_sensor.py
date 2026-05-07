import logging

import numpy as np

from space_flight import DEBUG_DELETION
from space_flight.game.collisions import attach_collision_sphere

LOGGER = logging.getLogger()


class CollisionSensor:
    """
    A class to define a collision sensor for bot navigators

    3 consecutive collision spheres intersect with dangerous objects
    """

    def __init__(
        self,
        game,
        ship,
        collision_reference_distance_m=200.0,
        ship_distance_1_m=5,
        radius_1_m=30,
        ship_distance_2_m=50,
        radius_2_m=50,
        ship_distance_3_m=125,
        radius_3_m=100,
    ):
        self.obstacles = []
        self.ship = ship
        self.collision_reference_distance_m = collision_reference_distance_m
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

    def compute_repulsion(self) -> tuple[np.ndarray, float]:
        """
        Computes the repulsion vector at every frame,
        then wipes the recorded obstacles

        :return: The repulsion vector and the repulsion weight
        """
        repulsion_vector = np.zeros(3)
        total_weight = 0.0
        self_position = self.ship.position

        for obstacle in self.obstacles:
            normal = obstacle["normal"]
            hit_point = obstacle["hit_point"]

            obstacle_direction = hit_point - self_position
            distance_m = np.linalg.norm(obstacle_direction)

            if distance_m > 1e-4:
                # Fallback if normal is degenerate
                if np.linalg.norm(normal) < 1e-4:
                    normal = obstacle_direction / distance_m
                # Compute obstacle weight
                weight = self.collision_reference_distance_m / distance_m
                repulsion_vector += weight * normal
                total_weight += weight

        if len(self.obstacles) > 0:
            total_weight /= len(self.obstacles)

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
