import uuid
from typing import Callable

import numpy as np

from space_flight.ai.auto_navigator import AutoNavigator
from space_flight.ai.auto_pilot import AutoPilot
from space_flight.ai.auto_tactician import AutoTactician
from space_flight.ship import Ship
from space_flight.ui.input_system import input_system_factory
from space_flight.ui.rear_view_mirror import RearViewMirror
from space_flight.utils import rotate_single_vector

# Camera movement parameters
CAMERA_ANGLE_INCREMENT = 2.0
COCKPIT_ANTI_GRAVITY_MODULE_INV_STRENGTH = 0.001
HEAD_ROTATION_POSITION_FACTOR_DEGPM = 500.0
HEAD_ROTATION_SHIP_ROTATION_RATE_FACTOR_DEGSPRAD = 1.0

IMPACT_FEELING_FACTOR = 2000


class Player:
    def __init__(
        self,
        game,
        ship_type: str,
        ini_position: np.ndarray = np.zeros(3),
        ini_orientation: np.ndarray = np.array([1.0, 0.0, 0.0, 0.0]),
        is_neutral: bool = False,
        has_ai: bool = False,
    ):
        self.game = game
        self.name = "player"
        self.id = uuid.uuid4()
        if is_neutral:
            team = 0
        else:
            team = 1

        # Add update mehods to the game's update methods list
        self.game.actor_methods[self.id] = []
        self.add_task(method=self.move_player)

        self.ship = Ship(
            game=self.game,
            parent=self,
            ship_type=ship_type,
            ini_position=ini_position,
            ini_orientation=ini_orientation,
            is_cockpit=True,
            team=team,
        )

        # Initialize input system
        self.has_ai = has_ai
        if self.has_ai:
            self.pilot = AutoPilot(game=self.game, ship=self.ship)
            self.navigator = AutoNavigator(game=self.game, ship=self.ship, debug=True)
            self.tactician = AutoTactician(game=self.game, ship=self.ship, debug=True)
        self.input_system = input_system_factory(game=self.game, player=self)

        # Initialize rear view mirror
        self.rear_view_mirror = RearViewMirror(
            game=self.game, player_node=self.ship.node
        )

        # Anchor camera to player ship node
        self.initialize_camera()

        # Initialize targetting list
        self.available_targets = [{None: ""}]  # TODO remove

        # Add self to the interacting actors
        self.game.interactions.add_actor(self.ship)

    def move_player(self):
        """
        Moves the camera and the skybox along with the player's
        position.

        The cockpit is linked to the camera, so it should move
        without being told to.
        """
        if self.has_ai:
            intent, target_dict = self.tactician.think()
            target_direction, desired_speed_mps = self.navigator.navigate(
                intent=intent, target_dict=target_dict
            )
            throttle, yaw_rate, pitch_rate, roll_rate = self.pilot.pilot(
                target_direction=target_direction, desired_speed_mps=desired_speed_mps
            )
        else:
            throttle, yaw_rate, pitch_rate, roll_rate = self.input_system.get_inputs()
        self.ship.move_ship(
            throttle=throttle,
            yaw_rate=yaw_rate,
            pitch_rate=pitch_rate,
            roll_rate=roll_rate,
        )

        # Move camera relative to the ship node
        self.move_camera()

    def add_task(self, method: Callable):
        """
        Add a task linked to this object

        :param method: the method to be called by the task
        """
        self.game.actor_methods[self.id].append(method)

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
        self.head_damping_ratio = 0.8  # Slightly suboptimal damping
        self.head_inv_mass_pkg = 0.2
        self.head_damping_coefficient_nspm = (
            2
            * self.head_damping_ratio
            * np.sqrt(self.head_spring_coefficient_npm / self.head_inv_mass_pkg)
        )

        # Turn head voluntarily
        self.head_pivot = self.head_jolt.attachNewNode("head_pivot")
        # Attach camera to head
        self.game.app.camera.reparentTo(self.head_pivot)
        # Allow near objects to be rendered
        # self.game.app.camLens.setNear(0.01)

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
        # Special treatment for impacts that should be more sensible
        ship_acceleration_world_mps2 += (
            (IMPACT_FEELING_FACTOR - 1) * self.ship.impact_force_n / self.ship.mass_kg
        )

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

        new_state = self.game.integrator.first_order_euler_step(
            state_derivative=state_derivative, state=previous_state
        )
        self.head_position_m = new_state[0:3]
        self.head_velocity_mps = new_state[3:6]

    def play_impact_sound(self, relative_hit_point: np.ndarray, kind: str):
        """
        Plays a sound when impacting something

        :param relative_hit_point: The position of the hit relative to the player node
        :param kind: The kind of impact
        """
        if kind == "laser":
            self.game.app.sfx.laser_impact_hit_on_player(
                game=self.game,
                relative_hit_point=relative_hit_point,
                is_shield=self.ship.shield > 0,
            )
        else:
            raise NotImplementedError

    def clean(self):
        """
        Cleans the player object before it is deleted
        """
        self.game.app.camera.reparentTo(self.game.app.render)
        self.head_pivot.removeNode()
        self.head_jolt.removeNode()

        if self.has_ai:
            self.pilot.clean()
            self.navigator.clean()
            self.tactician.clean()
            self.pilot = None
            self.navigator = None
            self.tactician = None

        self.rear_view_mirror.clean()
        self.rear_view_mirror = None

        self.available_targets = None
        self.input_system.clean()
        self.input_system = None
        self.game = None

        # No need to clean the ship :
        # It has already been done when all actors were cleaned
