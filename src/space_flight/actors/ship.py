import gc
import logging
import sys
from typing import Any

import numpy as np
import quaternion
import yaml
from panda3d.core import NodePath, Quat

from space_flight import (
    DATAFILES_PATH,
    DEBUG_DELETION,
    FLIGHT_MODEL,
    FORWARD_BODY,
    RIGHT_BODY,
    UP_BODY,
)
from space_flight.actors.laser_cannon import LaserCannon
from space_flight.actors.pawn import Pawn
from space_flight.actors.ship_model import ShipModel
from space_flight.ai.auto_aim import AutoAim
from space_flight.game.collisions import attach_collision_sphere
from space_flight.utils import low_pass_filter_first_order, rotate_single_vector

LOGGER = logging.getLogger()
RHO = 1  # A fictive "air" density" for atmospheric-like flight feeling
WEAPON_DAMAGE_TO_FORCE_FACTOR = 2.0
DAMAGE_FORCE_APPLICATION_DURATION_S = 0.1
ZERO_THRUST_POSITION = 0.05  # TODO move to input_system ? Should be tunable ?


class Ship(Pawn):
    """
    A Ship has 10 state variables
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
        game,
        parent: Any,
        ship_type: str,
        ini_position: np.ndarray = np.zeros(3),
        ini_orientation: np.ndarray = np.array([1.0, 0.0, 0.0, 0.0]),
        ini_speed: np.ndarray = np.zeros(3),
        is_cockpit: bool = True,
        team: int = 0,
    ):
        super().__init__(game=game, parent=parent, team=team)

        # Set a low-pass filter time to emulate physical delay in
        # thrust and rotational rates
        self.physics_filter_time_s = 0.3

        # Load configuration
        filepath = DATAFILES_PATH / f"models/ships/{ship_type}/configuration.yaml"
        with open(filepath, "r") as f:
            self.conf = yaml.safe_load(f)
        self.mass_kg = self.conf["mass_kg"]
        self.max_thrust_n = self.conf["max_thrust_n"]
        self.brake_factor_nspm = self.conf["brake_factor_nspm"]
        self.max_pitch_rate_radps = np.deg2rad(self.conf["max_pitch_rate_degps"])
        self.max_yaw_rate_radps = np.deg2rad(self.conf["max_yaw_rate_degps"])
        self.max_roll_rate_radps = np.deg2rad(self.conf["max_roll_rate_degps"])
        self.additional_force_n = np.zeros(3)  # e.g. for gravity if applicable
        self.impact_force_n = np.zeros(3)  # e.g. for collisions and laser hits
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
        self.max_speed_mps = np.sqrt(self.max_thrust_n / self.drag_factor)

        # Setup health and shield
        self.max_health = self.conf["health"]
        self.max_shield = self.conf["shield"]
        self.health = self.max_health
        self.shield = self.max_shield
        self.shield_regen_rate = self.conf["shield_regen_rate"]

        # Create a dummy node to attach models
        self.node = NodePath("ship_node")
        self.node.reparentTo(self.game.root_node)
        self.node.set_pos(*ini_position)
        self.node.set_quat(Quat(*ini_orientation))

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
        self.scalar_thrust_n = 0

        # Prepare corrections due to collisions
        self.velocity_correction = np.zeros(3)
        self.position_correction = np.zeros(3)

        # Prepare first integration step
        self.compute_derivatives()
        self.state_dot_previous = self.state_dot.copy()
        self.integrator_idx = self.game.integrator.set_state_variables(
            partial_x=self.state,
            partial_x_dot=self.state_dot,
            partial_x_dot_previous=self.state_dot_previous,
        )

        # Initialize cannons
        # TODO auto-aim parameters from difficulty config file
        self.target_id = None
        self.auto_aim = AutoAim(game=self.game, parent=self)
        self.laser_cannon = LaserCannon(game=self.game, parent=self)

        # Initialize collisions
        self.hit_radius_m = self.conf["hit_box_radius_m"]
        self.collision_sphere_np = attach_collision_sphere(
            game=self.game,
            name="ship",
            radius=self.hit_radius_m,
            collider_type="destructible",
            parent_node=self.node,
            parent_object=self,
        )

        # Handle ship health and shield
        self.parent.add_task(method=self.ship_handle_health)
        # Set explosion size for death animation
        self.explosion_scale = self.conf["explosion_scale"]

        # Create render
        self.model = ShipModel(
            game=self.game,
            parent_node=self.node,
            ship_type=ship_type,
            is_cockpit=is_cockpit,
        )

        # Initialize engine sound for bot ships
        # TODO better
        if self.parent.name != "player":
            sound_file = DATAFILES_PATH / self.conf["exterior_engine_sound"]
            self.sound_pool = self.game.app.asset_manager.get_asset(
                asset_type="3d_sound",
                path=sound_file,
            )
            self.sound = self.sound_pool.get_sound()
            self.sound.setLoop(True)
            self.sound.setVolume(10.0)
            self.game.app.sfx.audio3d.attachSoundToObject(self.sound, self.node)

            # Automatic velocity tracking
            self.game.app.sfx.audio3d.setSoundVelocityAuto(self.node)

            # TODO Doppler does not seem to work great
            self.game.delayed_methods.do_method_later(
                delay_s=0.5,
                name="Play_engine_sound",
                method=self.sound.play,
            )

    def set_inputs(
        self, throttle: float, yaw_rate: float, pitch_rate: float, roll_rate: float
    ):
        """
        Sets the scalar thrust and rotational rates of the ship.

        Square throttle so the velocity is easier to modulate

        Run a low pass filter on them afterwards to emulate delay in physical systems

        Panda3d seems to use the pitch-roll-yaw convention
        """
        dt = self.game.game_time.get_time_step()

        if throttle >= ZERO_THRUST_POSITION:
            # Thrust is positive
            scalar_thrust_n = (
                (throttle - ZERO_THRUST_POSITION) / (1 - ZERO_THRUST_POSITION)
            ) ** 2 * self.max_thrust_n
        else:
            # Ship is braking, propotionally to its forward speed
            brake_intensity = (ZERO_THRUST_POSITION - throttle) / ZERO_THRUST_POSITION
            forward_speed_mps = max(0.0, np.dot(self.speed, self.forward))
            scalar_thrust_n = (
                -forward_speed_mps * self.brake_factor_nspm * brake_intensity
            )

        pqr = np.array(
            [
                pitch_rate * self.max_pitch_rate_radps,
                roll_rate * self.max_roll_rate_radps,
                yaw_rate * self.max_yaw_rate_radps,
            ]
        )

        [
            self.scalar_thrust_n,
            self.pqr[0],
            self.pqr[1],
            self.pqr[2],
        ] = low_pass_filter_first_order(
            value=np.array(
                [
                    scalar_thrust_n,
                    pqr[0],
                    pqr[1],
                    pqr[2],
                ]
            ),
            previous=np.array(
                [
                    self.scalar_thrust_n,
                    self.pqr[0],
                    self.pqr[1],
                    self.pqr[2],
                ]
            ),
            dt=dt,
            rise_time=self.physics_filter_time_s,
            fall_time=self.physics_filter_time_s,
        )

    def compute_derivatives(self):
        """
        This is the flight model for the ships

        Depends on the FLIGHT_MODEL global variable
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
        self.state_dot[0:3] = self.speed.copy()
        # Compute derivative of orientation
        quat = np.quaternion(*self.orientation)
        quat_pqr = np.quaternion(0, *self.pqr)
        # Formula for pqr in body axes
        quat_dot = 0.5 * quat * quat_pqr
        self.state_dot[3:7] = quaternion.as_float_array(quat_dot)

        # Find and store ship directions
        self.forward = rotate_single_vector(quat, FORWARD_BODY)
        self.right = rotate_single_vector(quat, RIGHT_BODY)
        self.up = rotate_single_vector(quat, UP_BODY)

        # Compute derivative of speed with forces:
        # Thrust is aligned with ship direction
        thrust_n = self.scalar_thrust_n * self.forward

        if FLIGHT_MODEL == "airplane":
            speed_norm = np.linalg.norm(self.speed)
            if np.isnan(speed_norm) or (speed_norm <= 1e-4):
                # No lift or drag without speed
                drag_n = np.zeros(3)
                lift_n = np.zeros(3)
            else:
                # Drag is opposed to speed
                drag_n = -self.drag_factor * speed_norm * self.speed
                # Lift is perpendicular to ship side and airflow
                # and proportional to angle of attack
                # + And perpendicular to ship up and airflow
                # and proportional to side-slip angle
                airflow_speed_body = -rotate_single_vector(quat.conjugate(), self.speed)
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
                    * np.cross(airflow_direction_body, RIGHT_BODY)
                    + self.lateral_lift_factor
                    * speed_norm**2
                    * side_slip_angle_deg
                    * np.cross(
                        UP_BODY,
                        airflow_direction_body,
                    )
                )
                # Turn lift in world coordinates
                lift_n = rotate_single_vector(quat, lift_body)
        elif FLIGHT_MODEL == "space":
            # Neither lift nor drag
            drag_n = np.zeros(3)
            lift_n = np.zeros(3)
        else:
            raise NotImplementedError(f"Unknown flight model {FLIGHT_MODEL}")

        # Assemble thrust, lift, drag and accidental forces
        acceleration_mps2 = (
            thrust_n + drag_n + lift_n + self.additional_force_n + self.impact_force_n
        ) / self.mass_kg
        self.state_dot[7:10] = acceleration_mps2

    def move_ship_physics(self):
        """
        Gets the new ship's state, then prepare the next
        integration step.
        """
        # Get state
        self.state = self.game.integrator.get_state_variables(
            first_idx=self.integrator_idx,
            n_var=10,
        )
        # Apply position and velocity collision corrections
        self.state[:3] += self.position_correction
        self.state[7:10] += self.velocity_correction
        # Reset collision corrections
        self.position_correction = np.zeros(3)
        self.velocity_correction = np.zeros(3)

        # Record position, orientation and speed
        self.position = self.state[:3]
        self.orientation = self.state[3:7]
        self.speed = self.state[7:10]

        # Prepare next integration step
        self.compute_derivatives()
        self.integrator_idx = self.game.integrator.set_state_variables(
            partial_x=self.state,
            partial_x_dot=self.state_dot,
            partial_x_dot_previous=self.state_dot_previous,
        )

    def move(
        self, throttle: float, yaw_rate: float, pitch_rate: float, roll_rate: float
    ):
        """
        Moves the ship given throttle and turn rates

        :param throttle: _description_
        :param yaw_rate: _description_
        :param pitch_rate: _description_
        :param roll_rate: _description_
        """
        # Register flight inputs
        self.set_inputs(
            throttle=throttle,
            yaw_rate=yaw_rate,
            pitch_rate=pitch_rate,
            roll_rate=roll_rate,
        )
        # Apply physics and integrate movement
        self.move_ship_physics()

        # Update render
        self.node.setPos(*self.position)
        self.node.setQuat(Quat(*self.orientation))

        # Compute target acquisition
        self.auto_aim.compute_acquisition()

    def take_hit(self, damage: float, normal_world_vector: np.ndarray):
        """
        Take damage from hits and jolt from the impact
        # TODO move force calculations to collisions.py
        # TODO allow energy (ion) damage when we add energy management

        :param damage: The amount of damage to take
        :param normal_world_vector: The collision normal in world coordinates
        """
        self.apply_damage(damage=damage, damage_type="physical")

        # Apply momentum change
        hit_force_world_n = (
            -WEAPON_DAMAGE_TO_FORCE_FACTOR * damage * np.array([*normal_world_vector])
        )
        self.impact_force_n += hit_force_world_n
        # Remove this additional force later on
        self.game.delayed_methods.do_method_later(
            delay_s=DAMAGE_FORCE_APPLICATION_DURATION_S,
            name="remove_hit_force",
            method=self.remove_hit_force,
            extra_args=[hit_force_world_n],
        )

    def push(
        self,
        damage: float,
        velocity_correction: np.ndarray,
        position_correction: np.ndarray,
    ):
        """
        Push self due to collision with a solid object

        We don't use collision forces because they are too stiff.
        Instead, we use impulse and position correction

        The corrections are stored and taken into account at the next "move_ship" call,
        then reset to zero.

        # TODO: sadly the head does not move with this method. Do something about it

        :param damage: The damage to take
        :param velocity_correction: The velocity correction to apply
        :param position_correction: The position correction to apply
        """
        self.apply_damage(damage=damage, damage_type="physical")
        self.velocity_correction = velocity_correction
        self.position_correction = position_correction

    def apply_damage(self, damage: float, damage_type: str):
        """
        Apply damage to the ship

        :param damage_type: the type of damage to apply (physical, energy)
        """
        # Apply damage to health and shield
        if damage_type == "physical":
            if self.shield - damage >= 0.0:
                self.shield -= damage
            else:
                health_damage = damage - self.shield
                self.health -= health_damage
                self.shield = 0.0
        else:
            raise NotImplementedError

    def remove_hit_force(self, hit_force_world_n: np.ndarray):
        """
        A method to remove a hit force from the impact forces
        once its application time has expired

        :param hit_force_world_n: The force to remove
        """
        self.impact_force_n -= hit_force_world_n

    def ship_handle_health(self):
        """
        Monitors the ships health and shield
        """
        dt = self.game.game_time.get_time_step()
        self.shield = min(
            max(0.0, self.shield + dt * self.shield_regen_rate), self.max_shield
        )
        self.health = min(self.health, self.max_health)

    def clean(self):
        """
        Clean references before deleting the ship so that they can be properly
        garbage collected
        """
        if not self.is_clean:
            # Remove ship from its formation if applicable
            if self.formation is not None:
                self.formation.remove_ship(self.id)
                self.formation = None
            self.model.clean()
            self.model = None
            self.auto_aim.clean()
            self.auto_aim = None
            self.laser_cannon.clean()
            self.laser_cannon = None
            self.collision_sphere_np.setPythonTag("owner", None)
            self.collision_sphere_np.remove_node()
            self.collision_sphere_np = None
            if self.parent.name != "player":
                # TODO: remove condition when the player's ship gets sound
                self.sound.stop()
                self.game.app.sfx.audio3d.detachSound(self.sound)
            self.sound = None
            self.node.remove_node()
            self.node = None
            self.is_dead = True
            self.parent = None

            if DEBUG_DELETION:
                LOGGER.info("Cleaned ship")
                LOGGER.info(f"ship nref = {sys.getrefcount(self)}")
                LOGGER.info(f"ship references {gc.get_referrers(self)}")
                LOGGER.info(self.game.app.taskMgr.getAllTasks)

            self.game = None
            self.is_clean = True

    def __del__(self):
        if DEBUG_DELETION:
            # TODO: apparently this never happens. There must be some references hidden
            # somewhere but I can't find them. Bot deletes fine, though. Children,
            # including panda3d objects are properly deleted, I believe, so this
            # should not have too much of a memory impact. It's still enraging, though..
            LOGGER.info(self.game.app.taskMgr.getAllTasks)
            LOGGER.info("Deleted ship")
