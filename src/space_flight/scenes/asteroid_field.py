import random
import uuid

import numpy as np
import quaternion
from panda3d.core import Quat

from space_flight import DATAFILES_PATH
from space_flight.collisions import attach_collision_sphere

random.seed(1)
np.random.seed(1)


class AsteroidField:
    """
    An asteroid field

    `n_asteroids` are created in a cube centered at (0,0,0)
    and of size `field_size`.

    Their position is fixed but they slowly rotate.

    The shapes, positions, rotations and scales are randomly chosen
    for each asteroid.

    TODO: if I want asteroids to be destructible, I may need to isolate them :(
    """

    def __init__(
        self,
        game,
        n_asteroids: int = 40,
        field_size: float = 200,
        scale_factor: float = 1.0,
        is_moving: bool = True,
    ):
        self.game = game
        self.id = uuid.uuid4()
        self.n_asteroids = n_asteroids
        self.asteroids = []

        # Load 3D models
        asteroid_models = [
            self.game.app.loader.load_model(
                DATAFILES_PATH / "models/asteroids/toutatis_asteroid/scene.gltf"
            ),
            self.game.app.loader.load_model(
                DATAFILES_PATH / "models/asteroids/54509_asteroid/scene.gltf"
            ),
        ]

        # Prepare integration
        self.is_moving = is_moving
        if self.is_moving:
            self.state = np.zeros(4 * self.n_asteroids)
            self.state_dot = np.zeros(4 * self.n_asteroids)
            self.state_dot_previous = np.zeros(4 * self.n_asteroids)
            self.omegas = np.zeros(3 * self.n_asteroids)

        # Initialize instances of asteroids
        for ast_idx in range(self.n_asteroids):
            asteroid_model = random.choice(asteroid_models)
            instance = self.game.app.render.attachNewNode("asteroid_instance")
            asteroid_model.instanceTo(instance)

            # Set initial position
            ini_pos = np.random.rand(3) * field_size - 0.5 * field_size

            instance.set_pos(*ini_pos)
            # instance.show_bounds()

            # Set scale
            scale = (np.random.rand() * 100 + 1) * scale_factor
            instance.setScale(scale)

            # Set initial orientation
            temp = np.random.rand(4)
            quat_array = temp / np.linalg.norm(temp) + 0.2
            instance.setQuat(Quat(*quat_array))
            if self.is_moving:
                self.state[4 * ast_idx : 4 * (ast_idx + 1)] = quat_array.copy()

            # Set rotational rate
            if self.is_moving:
                omega = 5000 * np.deg2rad(np.random.rand(3) - 0.5) / (scale**1.5)
                self.omegas[3 * ast_idx : 3 * (ast_idx + 1)] = omega.copy()

            # Initialize collisions
            hit_box_radius_m = 1.2
            self.collision_sphere_np = attach_collision_sphere(
                game=self.game,
                name="terrain",
                radius=hit_box_radius_m,
                collider_type="terrain",
                parent_node=instance,
                parent_object=self,
            )

            # Store the new instance
            self.asteroids.append(instance)

        # Prepare first integration step
        if self.is_moving:
            self.compute_derivatives()
            self.state_dot_previous = self.state_dot.copy()
            self.integrator_idx = self.game.integrator.set_state_variables(
                partial_x=self.state,
                partial_x_dot=self.state_dot,
                partial_x_dot_previous=self.state_dot_previous,
            )
            self.game.actor_methods[self.id] = [self.move_asteriods_task]

    def compute_derivatives(self):
        """
        Computes the derivative of the asteroids' states
        """
        self.state_dot_previous = self.state_dot.copy()
        for ast_idx in range(self.n_asteroids):
            quat = np.quaternion(*self.state[4 * ast_idx : 4 * (ast_idx + 1)])
            quat_omega = np.quaternion(0, *self.omegas[3 * ast_idx : 3 * (ast_idx + 1)])
            # Formula for omega in world axes
            quat_dot = 0.5 * quat_omega * quat
            self.state_dot[4 * ast_idx : 4 * (ast_idx + 1)] = quaternion.as_float_array(
                quat_dot
            )

    def move_asteriods_task(self):
        """
        Gets the asteroids' states from the integrator and
        update rendered instances, then prepare the next
        integration step.
        """
        # Get states
        self.state = self.game.integrator.get_state_variables(
            first_idx=self.integrator_idx,
            n_var=4 * self.n_asteroids,
        )

        # Update instances
        for ast_idx in range(self.n_asteroids):
            instance = self.asteroids[ast_idx]
            # Normalize quaternion in state vector
            new_quat = self.state[4 * ast_idx : 4 * (ast_idx + 1)]
            new_quat /= np.linalg.norm(new_quat)
            # Update instance orientation
            instance.setQuat(Quat(*new_quat))

        # Prepare next integration step
        self.compute_derivatives()
        self.integrator_idx = self.game.integrator.set_state_variables(
            partial_x=self.state,
            partial_x_dot=self.state_dot,
            partial_x_dot_previous=self.state_dot_previous,
        )
