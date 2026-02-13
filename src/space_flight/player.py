from typing import Callable

import numpy as np
from direct.showbase.ShowBase import ShowBase

from space_flight.integrator import first_order_euler_step
from space_flight.ship import Ship
from space_flight.ui.input_system import input_system_factory
from space_flight.ui.rear_view_mirror import RearViewMirror
from space_flight.utils import rotate_single_vector

# Camera movement parameters
CAMERA_ANGLE_INCREMENT = 2.0
COCKPIT_ANTI_GRAVITY_MODULE_INV_STRENGTH = 0.001
HEAD_ROTATION_POSITION_FACTOR_DEGPM = 500.0
HEAD_ROTATION_SHIP_ROTATION_RATE_FACTOR_DEGSPRAD = 1.0

# TODO head should move more for impacts


class Player:
    def __init__(
        self,
        app: ShowBase,
        ship_type: str,
        ini_position: np.ndarray = np.zeros(3),
        ini_orientation: np.ndarray = np.array([1.0, 0.0, 0.0, 0.0]),
        is_neutral: bool = False,
    ):
        self.app = app
        self.name = "player"
        self.tasks = []
        if is_neutral:
            team = 0
        else:
            team = 1

        self.ship = Ship(
            app=self.app,
            parent=self,
            ship_type=ship_type,
            ini_position=ini_position,
            ini_orientation=ini_orientation,
            is_cockpit=True,
            team=team,
        )
        self.input_system = input_system_factory(app=self.app, player=self)
        self.rear_view_mirror = RearViewMirror(app=self.app, player_node=self.ship.node)

        # Anchor camera to player ship node
        self.initialize_camera()

        # Initialize targetting list
        self.available_targets = [{None: ""}]  # TODO remove

        # Initialize movement task
        self.initialize_move()

        # Add self to the interacting actors
        self.app.interactions.add_actor(self.ship)

    def initialize_move(self):
        """
        Initializes the player move task. Must be done after the
        integrator task init
        """
        self.add_task(method=self.move_player_task, task_name="move_player_task")

    def move_player_task(self, task):
        """
        Moves the camera and the skybox along with the player's
        position.

        The cockpit is linked to the camera, so it should move
        without being told to.
        """
        throttle, yaw_rate, pitch_rate, roll_rate = self.input_system.get_inputs()
        self.ship.move_ship(
            throttle=throttle,
            yaw_rate=yaw_rate,
            pitch_rate=pitch_rate,
            roll_rate=roll_rate,
        )

        # Move camera relative to the ship node
        self.move_camera()

        return task.cont

    def add_task(self, method: Callable, task_name: str):
        """
        Add a task linked to this object

        :param method: the method to be called by the task
        :param task_name: The name of the task
        """
        self.tasks.append(self.app.taskMgr.add(method, task_name))

    def add_target(self, target, name: str):
        """
        TODO: use Interactions for targets and remove

        :param target: _description_
        :param name: _description_
        """
        self.available_targets.append({target: name})

    def remove_target(self, target_to_remove):
        """
        TODO: use Interactions for targets and remove

        :param target_to_remove: _description_
        """
        for target_idx in range(len(self.available_targets)):
            target_dict = self.available_targets[target_idx]
            target, _ = list(target_dict.items())[0]
            if target == target_to_remove:
                idx_to_remove = target_idx
                break
        self.available_targets.pop(idx_to_remove)

    def initialize_camera(self):
        """
        Initialize the node structure to hold the camera
        """
        # Get jolted by hits, ship acceleration, etc.
        self.head_jolt = self.ship.node.attachNewNode("head_jolt")
        self.head_acceleration_mps2 = np.zeros(3)  # Initialization
        self.head_velocity_mps = np.zeros(3)  # Initialization
        self.head_position_m = np.zeros(3)
        self.head_spring_coefficient_npm = 25.0
        self.head_damping_ratio = 0.5  # Suboptimal damping
        self.head_inv_mass_pkg = 0.2
        self.head_damping_coefficient_nspm = (
            2
            * self.head_damping_ratio
            * np.sqrt(self.head_spring_coefficient_npm / self.head_inv_mass_pkg)
        )

        # Turn head voluntarily
        self.head_pivot = self.head_jolt.attachNewNode("head_pivot")
        # Attach camera to head
        self.app.camera.reparentTo(self.head_pivot)
        # Allow near objects to be rendered
        self.app.camLens.setNear(0.01)

    def move_camera(self):
        """
        Animate camera with:
        - Ship accelerations and taking hits
        - Ship having rotational speed
        - Pilot resisting accelerations
        - Pilot turning their head
        """

        # Ship accelerating and taking hits
        self.compute_head_acceleration()
        self.compute_head_position()
        self.head_jolt.setPos(*self.head_position_m)

        # Set head angular position proportional and opposite to ship roll rate
        roll_rate_radps = self.ship.pqr[1]
        self.head_jolt.setR(
            roll_rate_radps * HEAD_ROTATION_SHIP_ROTATION_RATE_FACTOR_DEGSPRAD
        )

        # Pilot turning their head TODO smoother system, independent of framerate
        self.head_pivot.setP(self.input_system.view_offset[0] * CAMERA_ANGLE_INCREMENT)
        self.head_pivot.setH(self.input_system.view_offset[1] * CAMERA_ANGLE_INCREMENT)

    def compute_head_acceleration(self):
        """
        Compute head acceleration given ship movements and pilot neck strength
        with a simple damped spring system
        """
        # Take ship acceleration into account
        ship_acceleration_world_mps2 = self.ship.state_dot[7:10]
        quat = np.quaternion(*self.ship.state[3:7])
        ship_acceleration_body_mps2 = rotate_single_vector(
            -quat, ship_acceleration_world_mps2
        )
        # Scale down, because real world accelerations are biiiig
        ship_acceleration_body_mps2 *= COCKPIT_ANTI_GRAVITY_MODULE_INV_STRENGTH

        # Compute the pilot's neck spring force
        spring_force_n = -self.head_spring_coefficient_npm * self.head_position_m
        # Compute the pilot's neck damping force
        damping_force_n = -self.head_damping_coefficient_nspm * self.head_velocity_mps

        # Assemble head acceleration
        self.head_acceleration_mps2 = (
            -ship_acceleration_body_mps2  # inertial pseudo force
            + (spring_force_n + damping_force_n) * self.head_inv_mass_pkg
        )

    def compute_head_position(self):
        """
        A simple explicit first order Euler scheme to integrate the head's trajectory
        """
        previous_state = np.zeros(6)
        state_derivative = np.zeros(6)
        previous_state[0:3] = self.head_position_m.copy()
        previous_state[3:6] = self.head_velocity_mps.copy()
        state_derivative[0:3] = self.head_velocity_mps.copy()
        state_derivative[3:6] = self.head_acceleration_mps2.copy()

        new_state = first_order_euler_step(
            state_derivative=state_derivative, state=previous_state
        )
        self.head_position_m = new_state[0:3]
        self.head_velocity_mps = new_state[3:6]
