import gc
import logging
import sys
import uuid
from typing import Any

import numpy as np
import quaternion
import yaml
from direct.showbase.ShowBase import ShowBase
from panda3d.core import NodePath, Quat

from space_flight import DATAFILES_PATH, DEBUG_DELETION, FLIGHT_MODEL
from space_flight.collisions import attach_collision_sphere
from space_flight.laser_cannon import LaserCannon
from space_flight.ship_model import ShipModel
from space_flight.utils import get_time_step, rotate_single_vector

LOGGER = logging.getLogger()
RHO = 1  # A fictive "air" density" for atmospheric-like flight feeling
DAMAGE_TO_FORCE_FACTOR = 100000.0
DAMAGE_FORCE_APPLICATION_DURATION_S = 0.1


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
    X axis is to the right, Z axis is up
    """

    def __init__(
        self,
        app: ShowBase,
        parent: Any,
        ship_type: str,
        ini_position: np.ndarray = np.zeros(3),
        ini_orientation: np.ndarray = np.array([1.0, 0.0, 0.0, 0.0]),
        ini_speed: np.ndarray = np.zeros(3),
        is_cockpit: bool = True,
        team: int = 0,
    ):
        self.app = app
        self.parent = parent
        self.is_dead = False
        self.id = uuid.uuid4()
        self.team = team

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
        self.additional_force_n = np.zeros(3)  # For collisions, hits, gravity, etc.
        self.drag_factor = (
            0.5
            * RHO
            * self.conf["reference_surface_m2"]
            * self.conf["drag_coefficient"]
        )
        self.lift_factor = (
            0.5
            * RHO
            * self.conf["reference_surface_m2"]
            * self.conf["lift_coefficient_slope_pdeg"]
        )
        self.lateral_lift_factor = (
            0.5
            * RHO
            * self.conf["reference_surface_m2"]
            * self.conf["lateral_lift_coefficient_slope_pdeg"]
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
        self.collision_sphere_np = attach_collision_sphere(
            app=self.app,
            name="ship",
            radius=self.conf["hit_box_radius_m"],
            collider_type="destructible",
            parent_node=self.node,
            parent_object=self,
        )

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

    def compute_derivatives(self):
        """
        This is the flight model for the ships

        Depends on the FLIGHT_MODEL global variable
        - "arcade": airplane-like flight with drag, velocity always aligned with forward
        - "airplane": airplane-like flight with lift, drag, AoA, sideslip
        - "space": Thrust is all you have, if you dare !

        Rotation rates are assumed to be perfectly-controlled inputs

        A Ship has 10 state variables
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

        # Find and store ship directions
        forward_body = np.array([0.0, 1.0, 0.0])
        self.forward = rotate_single_vector(quat, forward_body)
        right_body = np.array([1.0, 0.0, 0.0])
        self.right = rotate_single_vector(quat, right_body)
        up_body = np.array([0.0, 0.0, 1.0])
        self.up = rotate_single_vector(quat, up_body)

        # Compute derivative of speed with forces:
        # Thrust is aligned with ship direction
        thrust_n = self.scalar_thrust * self.forward

        if FLIGHT_MODEL == "arcade":
            # Drag is opposed to speed
            speed_norm = np.linalg.norm(speed)
            drag_n = -self.drag_factor * speed_norm * speed
            # No lift
            lift_n = np.zeros(3)
        elif FLIGHT_MODEL == "airplane":
            speed_norm = np.linalg.norm(speed)
            if np.isnan(speed_norm) or (speed_norm <= 1e-4):
                # No lift or drag without speed
                drag_n = np.zeros(3)
                lift_n = np.zeros(3)
            else:
                # Drag is opposed to speed
                drag_n = -self.drag_factor * speed_norm * speed
                # Lift is perpendicular to ship side and airflow
                # and proportional to angle of attack
                # + And perpendicular to ship up and airflow
                # and proportional to side-slip angle
                airflow_speed_body = -rotate_single_vector(quat.conjugate(), speed)
                airflow_direction_body = airflow_speed_body / speed_norm
                angle_of_attack_deg = -np.rad2deg(
                    np.arctan2(-airflow_speed_body[2], -airflow_speed_body[1])
                )
                side_slip_angle_deg = np.rad2deg(
                    np.arcsin(airflow_speed_body[0] / speed_norm)
                )
                lift_body = (
                    self.lift_factor
                    * speed_norm**2
                    * angle_of_attack_deg
                    * np.cross(airflow_direction_body, right_body)
                    + self.lateral_lift_factor
                    * speed_norm**2
                    * side_slip_angle_deg
                    * np.cross(
                        up_body,
                        airflow_direction_body,
                    )
                )
                # Turn lift in world coordinates
                lift_n = rotate_single_vector(quat, lift_body)
        elif FLIGHT_MODEL == "space":
            # No lift or drag
            drag_n = np.zeros(3)
            lift_n = np.zeros(3)
        else:
            raise NotImplementedError(f"Unknown flight model {FLIGHT_MODEL}")
        # Assemble thrust, lift, drag and accidental forces
        acceleration_mps2 = (
            thrust_n + drag_n + lift_n + self.additional_force_n
        ) / self.mass_kg
        self.state_dot[7:10] = acceleration_mps2

    def move_ship_physics(self):
        """
        Gets the new ship's state, then prepare the next
        integration step.
        """
        # Get state
        self.state = self.app.integrator.get_state_variables(
            first_idx=self.integrator_idx,
            n_var=10,
        )
        # Clip speed norm
        self.speed = self.state[7:10]
        speed_norm = np.linalg.norm(self.speed)

        # Record position
        self.position = self.state[:3]

        if FLIGHT_MODEL == "arcade":
            # Clip speed norm
            speed_norm = min(speed_norm, self.max_speed_mps)
            # Since there is no lift model,
            # we align the velocity with the nose of the ship
            # Normalize ship orientation
            self.orientation = self.state[3:7].copy()
            self.orientation /= np.linalg.norm(self.orientation)
            self.state[3:7] = self.orientation.copy()
            # Reorient speed in ship direction
            self.speed = self.forward * speed_norm
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

        # TODO position and orientation => already attributes
        ship_pos = self.state[0:3]
        ship_quat = self.state[3:7]

        self.node.setPos(*ship_pos)
        self.node.setQuat(Quat(*ship_quat))

    def take_hit(self, damage: float, normal_body_vector: np.ndarray):
        """
        Take damage from hits and jolt from the impact TODO

        :param damage: The amount of damage to take
        :param normal_body_vector: The collision normal in body coordinates
        """
        # Apply damage to health and shield
        if self.shield - damage >= 0.0:
            self.shield -= damage
        else:
            health_damage = damage - self.shield
            self.health -= health_damage
            self.shield = 0.0

        # Apply momentum change
        hit_force_body_n = (
            -DAMAGE_TO_FORCE_FACTOR * damage * np.array([*normal_body_vector])
        )
        quat = np.quaternion(*self.state[3:7])
        hit_force_world_n = rotate_single_vector(quat, hit_force_body_n)
        self.additional_force_n += hit_force_world_n
        # Remove this additional force later on
        self.app.doMethodLater(
            DAMAGE_FORCE_APPLICATION_DURATION_S,
            self.remove_hit_force,
            "Reset_damage_force",
            extraArgs=[hit_force_world_n],
            appendTask=True,
        )

    def remove_hit_force(self, hit_force_world_n: np.ndarray, task):
        """
        A method to remove a hit force from the additional forces

        :param hit_force_world_n: The force to remove
        """
        self.additional_force_n -= hit_force_world_n
        return task.done

    def ship_handle_health(self, task):
        """
        Monitors the ships health and shield

        :param task: _description_
        """
        dt = get_time_step()
        self.shield = min(
            max(0.0, self.shield + dt * self.shield_regen_rate), self.max_shield
        )
        self.health = min(self.health, self.max_health)

        return task.cont

    def clean(self):
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
            LOGGER.info(self.app.taskMgr.getAllTasks)
            LOGGER.info("Deleted ship")
