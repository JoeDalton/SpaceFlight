import gc
import logging
import sys
from typing import Any

import numpy as np
import quaternion
import yaml
from direct.showbase.ShowBase import ShowBase
from direct.showbase.ShowBaseGlobal import globalClock
from panda3d.core import CollisionNode, CollisionSphere, NodePath, Quat

from space_flight import DATAFILES_PATH, SHIP_BIT
from space_flight.laser_cannon import LaserCannon
from space_flight.ship_model import ShipModel
from space_flight.utils import rotate_single_vector

DEBUG_DELETION = True
LOGGER = logging.getLogger()
RHO = 1  # A fictive "air" density" for atmospheric-like flight feeling


class Ship:
    """
    A SimpleShip has 10 state variables
    - position (3)
    - orientation (4)
    - linear speed (3)

    The linear speed is integrated from the ship's acceleration.
    However, the rotation rate is given directly (from user input
    or PNJ behaviour)

    "Forward" is on an object's Y axis in panda3d, so thrust is in +Y
    """

    def __init__(
        self,
        app: ShowBase,
        parent: Any,
        ship_type: str,
        ini_position: np.ndarray = np.zeros(3),
        ini_orientation: np.ndarray = np.array([1.0, 0.0, 0.0, 0.0]),
        ini_speed: np.ndarray = np.zeros(3),
        lift_model: bool = False,
        is_cockpit: bool = True,
    ):
        self.app = app
        self.parent = parent
        self.is_dead = False

        # Load configuration
        filepath = DATAFILES_PATH / f"models/ships/{ship_type}/configuration.yaml"
        with open(filepath, "r") as f:
            self.conf = yaml.safe_load(f)
        self.mass_kg = self.conf["mass_kg"]
        self.max_thrust_n = self.conf["max_thrust_n"]
        self.max_speed_mps = self.conf["max_speed_mps"]  # TODO: from thrust and drag
        self.max_pitch_rate_radps = np.deg2rad(self.conf["max_pitch_rate_degps"])
        self.max_yaw_rate_radps = np.deg2rad(self.conf["max_yaw_rate_degps"])
        self.max_roll_rate_radps = np.deg2rad(self.conf["max_roll_rate_degps"])
        self.drag_factor = (
            0.5
            * RHO
            * self.conf["reference_surface_m2"]
            * self.conf["drag_coefficient"]
        )

        # Setup health and shield
        self.max_health = self.conf["health"]
        self.max_shield = self.conf["shield"]
        self.health = self.max_health
        self.shield = self.max_shield
        self.shield_regen_rate = self.conf["shield_regen_rate"]

        # Create a dummy node to attach models
        self.node = NodePath("ship_node")
        self.node.reparentTo(self.app.render)

        # Setup state vector
        self.position = ini_position.copy()
        self.orientation = ini_orientation.copy()
        self.speed = ini_speed.copy()
        self.state = np.zeros(10)  # position (3), orientation (4), speed (3)
        self.state[:3] = ini_position
        self.state[3:7] = ini_orientation
        self.state_dot = np.zeros(10)
        self.state_dot_previous = np.zeros(10)
        self.pqr = np.zeros(3)
        self.scalar_thrust = 0

        # Assign physics
        if not lift_model:
            self.compute_derivatives = self.compute_derivatives_simple_physics
            self.move_ship_physics = self.move_ship_simple_physics
        else:
            # TODO: more "realistic" flight model
            raise NotImplementedError

        # Prepare first integration step
        self.compute_derivatives()
        self.state_dot_previous = self.state_dot.copy()
        self.integrator_idx = self.app.integrator.set_state_variables(
            partial_x=self.state,
            partial_x_dot=self.state_dot,
            partial_x_dot_previous=self.state_dot_previous,
        )

        # Initialize cannons
        self.laser_cannon = LaserCannon(app=self.app, parent_ship=self)

        # Initialize collisions
        self.hit_box_radius_m = self.conf["hit_box_radius_m"]
        self.target_cnode = CollisionNode("ship")
        self.target_cnode.addSolid(CollisionSphere(0, 0, 0, self.hit_box_radius_m))
        self.target_cnode.setFromCollideMask(0)
        self.target_cnode.setIntoCollideMask(SHIP_BIT)
        self.ship_np = self.node.attachNewNode(self.target_cnode)
        self.ship_np.setPythonTag("owner", self)
        self.ship_np.show()

        # Handle ship health and shield
        self.parent.add_task(
            method=self.ship_handle_health, task_name="ship_handle_health"
        )

        # Create render
        self.model = ShipModel(app=self.app, ship_type=ship_type, is_cockpit=is_cockpit)
        self.model.anchor_model(self.node)

    def set_inputs(
        self, throttle: float, yaw_rate: float, pitch_rate: float, roll_rate: float
    ):
        """
        Sets the scalar thrust and rotational rates of the ship

        Panda3d seems to use the pitch-roll-yaw convention
        """
        self.scalar_thrust = throttle * self.max_thrust_n
        self.pqr = np.array(
            [
                pitch_rate * self.max_pitch_rate_radps,
                roll_rate * self.max_roll_rate_radps,
                yaw_rate * self.max_yaw_rate_radps,
            ]
        )

    def compute_derivatives_simple_physics(self):
        """
        This is the flight model for the ships

        Since there is no lift model, the velocity is always aligned
        with the nose of the ship

        A SimpleShip has 10 state variables
        - position (3)
        - orientation (4)
        - linear speed (3)
        """
        # Save last derivative
        self.state_dot_previous = self.state_dot.copy()

        # Compute derivative of position
        speed = self.state[7:10]
        self.state_dot[0:3] = speed
        # Compute derivative of orientation
        quat = np.quaternion(*self.state[3:7])
        quat_pqr = np.quaternion(0, *self.pqr)
        # Formula for pqr in body axes
        quat_dot = 0.5 * quat * quat_pqr
        self.state_dot[3:7] = quaternion.as_float_array(quat_dot)

        # Compute derivative of speed:
        # Drag is opposed to speed, thrust is aligned to ship direction
        speed_norm = np.linalg.norm(speed)
        drag = -self.drag_factor * speed_norm * speed
        thrust_body = np.array([0.0, self.scalar_thrust, 0.0])
        thrust = rotate_single_vector(quat, thrust_body)
        acceleration = (thrust + drag) / self.mass_kg
        self.state_dot[7:10] = acceleration

    def move_ship_simple_physics(self):
        """
        Gets the new ship's state, then prepare the next
        integration step.

        Since there is no lift model, the velocity is always aligned
        with the nose of the ship
        """
        # Get state
        self.state = self.app.integrator.get_state_variables(
            first_idx=self.integrator_idx,
            n_var=10,
        )
        # Clip speed norm
        speed = self.state[7:10]
        speed_norm = np.linalg.norm(speed)
        speed_norm = min(speed_norm, self.max_speed_mps)

        # Record position
        self.position = self.state[:3]

        # Normalize ship orientation
        self.orientation = self.state[3:7].copy()
        self.orientation /= np.linalg.norm(self.orientation)
        self.state[3:7] = self.orientation.copy()
        # Reorient speed in ship direction
        quat = np.quaternion(*self.orientation)
        speed_body = np.array([0.0, speed_norm, 0.0])
        self.speed = rotate_single_vector(quat, speed_body)
        self.state[7:10] = self.speed.copy()

        # Prepare next integration step
        self.compute_derivatives()
        self.integrator_idx = self.app.integrator.set_state_variables(
            partial_x=self.state,
            partial_x_dot=self.state_dot,
            partial_x_dot_previous=self.state_dot_previous,
        )

    def move_ship(
        self, throttle: float, yaw_rate: float, pitch_rate: float, roll_rate: float
    ):
        """
        Moves the ship given throttle and turn rates

        :param throttle: _description_
        :param yaw_rate: _description_
        :param pitch_rate: _description_
        :param roll_rate: _description_
        """
        self.set_inputs(
            throttle=throttle,
            yaw_rate=yaw_rate,
            pitch_rate=pitch_rate,
            roll_rate=roll_rate,
        )
        self.move_ship_physics()

        ship_pos = self.state[0:3]
        ship_quat = self.state[3:7]

        self.node.setPos(*ship_pos)
        self.node.setQuat(Quat(*ship_quat))

    def count_hit(self, damage: float):
        """
        Take damage from hits

        :param damage: The amount of damage to take
        """
        if self.shield - damage >= 0.0:
            self.shield -= damage
        else:
            health_damage = damage - self.shield
            self.health -= health_damage
            self.shield = 0.0

    def ship_handle_health(self, task):
        """
        Monitors the ships health and shield

        :param task: _description_
        """
        dt = globalClock.getDt()
        self.shield = min(
            max(0.0, self.shield + dt * self.shield_regen_rate), self.max_shield
        )
        self.health = min(self.health, self.max_health)

        return task.cont

    def clean(self):
        self.laser_cannon.clean()
        self.laser_cannon = None
        self.ship_np.setPythonTag("owner", None)
        self.ship_np.remove_node()
        self.ship_np = None
        self.node.remove_node()
        self.node = None
        self.is_dead = True
        self.parent = None

        if DEBUG_DELETION:
            LOGGER.info("Cleaned ship")
            LOGGER.info(f"ship nref = {sys.getrefcount(self)}")
            LOGGER.info(f"ship references {gc.get_referrers(self)}")
            LOGGER.info(self.app.taskMgr.getAllTasks)

    def __del__(self):
        if DEBUG_DELETION:
            # TODO: apparently this never happens. There must be some references hidden
            # somewhere but I can't find them. Bot deletes fine, though. Children,
            # including panda3d objects are properly deleted, I believe, so this
            # should not have too much of a memory impact. It's still enraging, though..
            LOGGER.info("Deleted ship")
