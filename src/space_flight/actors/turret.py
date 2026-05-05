import gc
import logging
import sys
from typing import Any

import numpy as np
import yaml
from panda3d.core import NodePath, Quat

from space_flight import (
    DATAFILES_PATH,
    DEBUG_DELETION,
    FORWARD_BODY,
    RIGHT_BODY,
    UP_BODY,
)
from space_flight.actors.laser_cannon import LaserCannon
from space_flight.actors.pawn import Pawn
from space_flight.actors.turret_model import TurretModel
from space_flight.game.collisions import attach_collision_sphere
from space_flight.utils import low_pass_filter_first_order, rotate_single_vector

LOGGER = logging.getLogger()


class Turret(Pawn):
    """
    A Turret has 2 state variables
    - yaw
    - pitch

    Turrents have constrained and uninteresting movement,
    So we use an basic Euler 1 integrator.

    The rotation rate are given directly (from user input
    or PNJ behaviour)

    "Forward" is on an object's Y axis in panda3d, so thrust is in +Y
    X axis is to the right, Z axis is up
    """

    def __init__(
        self,
        game,
        parent: Any,
        turret_type: str,
        parent_object: Any,
        base_position: np.ndarray = np.zeros(3),
        base_orientation: np.ndarray = np.array([1.0, 0.0, 0.0, 0.0]),
        ini_yaw_deg: float = 0.0,
        ini_pitch_deg: float = 30.0,
        team: int = 0,
    ):
        super().__init__(game=game, parent=parent, team=team)
        self.parent_object = parent_object

        # Load configuration
        filepath = DATAFILES_PATH / f"models/turrets/{turret_type}/configuration.yaml"
        with open(filepath, "r") as f:
            self.conf = yaml.safe_load(f)

        # Set a low-pass filter time to emulate physical delay in rotational rates
        self.physics_filter_time_s = self.conf["inertia_filter_s"]

        # Set agility of turret
        self.max_pitch_rate_degps = self.conf["max_pitch_rate_degps"]
        self.max_yaw_rate_degps = self.conf["max_yaw_rate_degps"]

        # Setup health and shield
        self.max_health = self.conf["health"]
        self.health = self.max_health

        # Create a dummy node to attach models
        self.node = NodePath("turret_node")
        if isinstance(self.parent_object, NodePath):
            self.node.reparentTo(self.parent_object)
        else:
            self.node.reparentTo(self.parent_object.node)

        self.node.set_pos(*base_position)
        self.node.set_quat(Quat(*base_orientation))
        self.position = np.array(self.node.getPos(self.game.root_node))

        # Create render
        self.model = TurretModel(
            game=self.game,
            parent_node=self.node,
            turret_type=turret_type,
        )
        self.set_yaw = self.model.set_yaw
        self.set_pitch = self.model.set_pitch
        self.state = np.array([ini_yaw_deg, ini_pitch_deg])
        self.set_yaw(self.state[0])
        self.set_pitch(self.state[1])
        self.state_derivative = np.zeros(2)

        # Initialize cannons
        self.target_id = None
        # No auto aim : Auto-aiming turrets would be way too deadly!
        self.laser_cannon = LaserCannon(
            game=self.game, parent=self, parent_node=self.model.cannon_node
        )

        # Initialize collisions
        self.hit_radius_m = self.conf["hit_box_radius_m"]
        self.collision_sphere_np = attach_collision_sphere(
            game=self.game,
            name="turret",
            radius=self.hit_radius_m,
            collider_type="destructible",
            parent_node=self.node,
            parent_object=self,
        )

        # Handle ship health and shield
        self.parent.add_task(method=self.turret_handle_health)
        # Set explosion size for death animation
        self.explosion_scale = self.conf["explosion_scale"]

    def move(self, yaw_rate: float, pitch_rate: float):
        """
        Moves the turret given its turn rates
        Run a low pass filter on the turn rates beforehand
        to emulate delay in physical systems

        :param yaw_rate: _description_
        :param pitch_rate: _description_
        """
        dt = self.game.game_time.get_time_step()

        # Apply low pass filter on rotation rates
        self.state_derivative = low_pass_filter_first_order(
            value=np.array(
                [
                    yaw_rate * self.max_yaw_rate_degps,
                    pitch_rate * self.max_pitch_rate_degps,
                ]
            ),
            previous=self.state_derivative,
            dt=dt,
            rise_time=self.physics_filter_time_s,
            fall_time=self.physics_filter_time_s,
        )

        # Compute new angles
        new_state = self.game.integrator.first_order_euler_step(
            state_derivative=self.state_derivative, state=self.state
        )
        # Clip angles to the turret's possibilities
        new_state[1] = min(
            self.conf["max_pitch_deg"], max(new_state[1], self.conf["min_pitch_deg"])
        )
        self.state = new_state

        # Set angles on the model
        self.set_yaw(self.state[0])
        self.set_pitch(self.state[1])

        # Compute remarkable directions of the turret cannon
        cannon_quat = np.quaternion(
            *self.model.cannon_node.getQuat(self.game.root_node)
        )
        self.forward = rotate_single_vector(cannon_quat, FORWARD_BODY)
        base_quat = np.quaternion(*self.node.getQuat(self.game.root_node))
        self.base_forward = rotate_single_vector(base_quat, FORWARD_BODY)
        self.base_right = rotate_single_vector(base_quat, RIGHT_BODY)
        self.base_up = rotate_single_vector(base_quat, UP_BODY)

    def take_hit(self, damage: float, normal_world_vector: np.ndarray):
        """
        Take damage from hits
        # TODO allow energy (ion) damage when we add energy management

        :param damage: The amount of damage to take
        :param normal_world_vector: The collision normal in world coordinates
        """
        self.apply_damage(damage=damage, damage_type="physical")

    def apply_damage(self, damage: float, damage_type: str):
        """
        Apply damage to the turret

        :param damage_type: The type of damage to apply (physical, energy)
        """
        # Apply damage to health and shield
        if damage_type == "physical":
            self.health -= damage
        else:
            raise NotImplementedError

    def turret_handle_health(self):
        """
        Monitors the turret's health
        """
        self.health = min(self.health, self.max_health)

    def clean(self):
        """
        Clean references before deleting the turret so that they can be properly
        garbage collected
        """
        if not self.is_clean:
            self.model.clean()
            self.model = None
            # self.auto_aim.clean()
            # self.auto_aim = None
            self.laser_cannon.clean()
            self.laser_cannon = None
            self.collision_sphere_np.setPythonTag("owner", None)
            self.collision_sphere_np.remove_node()
            self.collision_sphere_np = None
            self.node.remove_node()
            self.node = None
            self.is_dead = True
            self.parent = None

            if DEBUG_DELETION:
                LOGGER.info("Cleaned turret")
                LOGGER.info(f"turret nref = {sys.getrefcount(self)}")
                LOGGER.info(f"turret references {gc.get_referrers(self)}")
                LOGGER.info(self.game.app.taskMgr.getAllTasks)

            self.game = None
            self.is_clean = True

    def __del__(self):
        if DEBUG_DELETION:
            LOGGER.info(self.game.app.taskMgr.getAllTasks)
            LOGGER.info("Deleted turret")
