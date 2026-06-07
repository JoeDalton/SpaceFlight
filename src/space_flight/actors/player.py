import uuid
from typing import Callable

import numpy as np

from space_flight import RECORD_GAME, TARGET_FILTERS
from space_flight.actors.fighter import Fighter
from space_flight.ai.fighter.fighter_navigator import FighterNavigator
from space_flight.ai.fighter.fighter_pilot import FighterPilot
from space_flight.ai.fighter.fighter_tactician import FighterTactician
from space_flight.ui.rear_view_mirror import RearViewMirror
from space_flight.utils import rotate_single_vector, smooth_step_down

# Camera movement parameters
CAMERA_ANGLE_INCREMENT = 2.0
COCKPIT_ANTI_GRAVITY_MODULE_INV_STRENGTH = 0.001
HEAD_SPRING_COEFFICIENT_NPM = 17
HEAD_DAMPING_RATIO = 0.8  # Slightly suboptimal damping
HEAD_ROTATION_POSITION_FACTOR_DEGPM = 500.0
HEAD_ROTATION_SHIP_ROTATION_RATE_FACTOR_DEGSPRAD = 1.0

IMPACT_FEELING_FACTOR = 1000


class Player:
    def __init__(
        self,
        game,
        ship_type: str,
        ini_position: np.ndarray = np.zeros(3),
        ini_orientation: np.ndarray = np.array([1.0, 0.0, 0.0, 0.0]),
        is_neutral: bool = False,
        has_ai: bool = False,
        record: bool = False,
    ):
        self.game = game
        self.name = "player"
        self.id = uuid.uuid4()
        self.record = record
        if is_neutral:
            team = 0
        else:
            team = 1

        # Add update mehods to the game's update methods list
        self.game.method_lists[self.id] = []
        self.add_task(method=self.move_player)

        self.pawn = Fighter(
            game=self.game,
            parent=self,
            ship_type=ship_type,
            ini_position=ini_position,
            ini_orientation=ini_orientation,
            is_cockpit=True,
            team=team,
        )

        # Flight state written by FlightInputContext (or AI pilot) each frame
        self.throttle = 0.0
        self.yaw_rate = 0.0
        self.pitch_rate = 0.0
        self.roll_rate = 0.0
        self.view_offset = np.zeros(2)

        self.has_ai = has_ai
        if self.has_ai:
            self.pilot = FighterPilot(game=self.game, pawn=self.pawn)
            self.navigator = FighterNavigator(
                game=self.game, pawn=self.pawn, debug=True
            )
            self.tactician = FighterTactician(
                game=self.game, pawn=self.pawn, debug=True
            )

        # Initialize rear view mirror
        self.rear_view_mirror = RearViewMirror(
            game=self.game, player_node=self.pawn.node
        )

        # Anchor camera to player ship node
        self.initialize_camera()

        # Add self to the interacting actors
        self.game.interactions.add_actor(self.pawn)

        # Prepare targetting filters
        self.target_filter: str = "All"

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
            (
                self.throttle,
                self.yaw_rate,
                self.pitch_rate,
                self.roll_rate,
            ) = self.pilot.pilot(
                target_direction=target_direction, desired_speed_mps=desired_speed_mps
            )
        self.pawn.move(
            throttle=self.throttle,
            yaw_rate=self.yaw_rate,
            pitch_rate=self.pitch_rate,
            roll_rate=self.roll_rate,
        )

        # Move camera relative to the ship node
        self.move_camera()

        # Record state if needed
        if RECORD_GAME and self.record:
            self.record_state()

    def add_task(self, method: Callable):
        """
        Add a task linked to this object

        :param method: the method to be called by the task
        """
        self.game.method_lists[self.id].append(method)

    def initialize_camera(self):
        """
        Initialize the node structure to hold the camera
        """
        # Get jolted by hits, ship acceleration, etc.
        self.head_jolt = self.pawn.node.attachNewNode("head_jolt")
        self.head_acceleration_mps2 = np.zeros(3)
        self.head_velocity_mps = np.zeros(3)
        self.head_position_m = np.zeros(3)
        self.head_spring_coefficient_npm = HEAD_SPRING_COEFFICIENT_NPM
        self.head_damping_ratio = HEAD_DAMPING_RATIO
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
        roll_rate_radps = self.pawn.pqr[1]
        self.head_jolt.setR(
            roll_rate_radps * HEAD_ROTATION_SHIP_ROTATION_RATE_FACTOR_DEGSPRAD
        )

        # Pilot turning their head TODO smoother system, independent of framerate
        self.head_pivot.setP(self.view_offset[0] * CAMERA_ANGLE_INCREMENT)
        self.head_pivot.setH(self.view_offset[1] * CAMERA_ANGLE_INCREMENT)

    def compute_head_acceleration(self):
        """
        Compute head acceleration given ship movements and pilot neck strength
        with a simple damped spring system
        """
        # Take ship acceleration into account
        ship_acceleration_world_mps2 = self.pawn.state_dot[7:10]
        # Special treatment for impacts that should be more sensible
        ship_acceleration_world_mps2 += (
            (IMPACT_FEELING_FACTOR - 1) * self.pawn.impact_force_n / self.pawn.mass_kg
        )

        quat = np.quaternion(*self.pawn.state[3:7])
        ship_acceleration_body_mps2 = rotate_single_vector(
            quat.conjugate(), ship_acceleration_world_mps2
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
                is_shield=self.pawn.shield > 0,
            )
        else:
            raise NotImplementedError

    def loop_target(self, increment: int = 1):
        """
        Loops over available targets

        :param increment: Target list loop increment
        """
        my_actor_index = self.game.interactions.get_actor_index_from_id(self.pawn.id)
        self.update_target_mask(player_actor_index=my_actor_index)
        # Case of no available targets
        if np.sum(self.target_mask) == 0:
            self.pawn.target = None
            self.pawn.target_idx = None
            return

        # Find indices of available targets
        available_indices = np.where(self.target_mask)[0]
        # Find current target in available targets
        target_available_index = np.where(available_indices == self.pawn.target_idx)[0]
        # Reset index if current target is not in the available targets
        # (Filter might have changed, for example)
        if len(target_available_index) == 0:
            target_available_index = -1
        else:
            target_available_index = target_available_index[0]
        # Loop over target list
        next_available_target_idx = available_indices[
            (target_available_index + increment) % len(available_indices)
        ]
        self.set_target_from_actor_index(target_idx=next_available_target_idx)

    def point_target(self):
        """
        Finds the closest and most forward available target
        """
        my_actor_index = self.game.interactions.get_actor_index_from_id(self.pawn.id)
        self.update_target_mask(player_actor_index=my_actor_index)
        # Case of no available targets
        if np.sum(self.target_mask) == 0:
            self.pawn.target = None
            self.pawn.target_id = None
            self.pawn.target_idx = None
            return
        # Find the best prey
        distances = self.game.interactions.distances[
            my_actor_index, self.game.interactions.alive
        ]
        alignments = self.game.interactions.alignments[
            my_actor_index, self.game.interactions.alive
        ]
        # Distance contribution
        distance_scores = smooth_step_down(
            x=distances,
            x_step=3000,
            slope=0.01,
        )
        # Forwardness contribution
        forward_scores = (0.5 + 0.5 * alignments) ** 2
        # Assemble all contributions
        prey_scores = self.target_mask * distance_scores * forward_scores
        # Select highest scoring prey
        max_prey_score_idx = np.nanargmax(prey_scores)
        # Case of no interesting target
        if prey_scores[max_prey_score_idx] < 1e-4:
            self.pawn.target = None
            self.pawn.target_id = None
            self.pawn.target_idx = None
            return
        self.set_target_from_actor_index(target_idx=max_prey_score_idx)

    def set_target_from_actor_index(self, target_idx: int):
        """
        Sets the target of the player

        :param target_idx: The index of the target in the actor list
        """
        self.pawn.target = self.game.interactions.live_actors[target_idx]
        self.pawn.target_id = self.pawn.target.id
        self.pawn.target_idx = self.game.interactions.get_actor_index_from_id(
            self.pawn.target_id
        )

    def update_target_mask(self, player_actor_index: int) -> np.ndarray:
        """
        Updates the target mask depending on the player's wishes

        :param player_actor_index: Index of the player in the interactions class
        :return: the target mask
        """
        if (self.target_filter == "All") or (self.target_filter == ""):
            self.target_mask = np.ones(self.game.interactions.n_actors)
        elif self.target_filter == "Enemies":
            self.target_mask = self.game.interactions.interact[
                player_actor_index, self.game.interactions.alive
            ]
            # TODO: other filters
        else:
            # Don't change the target mask
            pass
        self.target_mask[player_actor_index] = 0

    def open_radial_target_menu(self):
        """
        Prepare the radial target menu
        """

        def set_player_filter(idx: int | None):
            if idx is None:
                self.target_filter = ""
            else:
                self.target_filter = TARGET_FILTERS[idx]

        self.game.app.state_manager.push(
            state_class=self.game.app.state_manager.RADIAL_MENU_STATE,
            on_select=lambda idx: set_player_filter(idx),
            slice_labels=TARGET_FILTERS,
        )

    def record_state(self):
        """
        Records the player's state
        """
        self.game.record.record(variable_name="player_throttle", variable=self.throttle)
        self.game.record.record(
            variable_name="player_yaw_rate_radps", variable=self.yaw_rate
        )
        self.game.record.record(
            variable_name="player_pitch_rate_radps", variable=self.pitch_rate
        )
        self.game.record.record(
            variable_name="player_roll_rate_radps", variable=self.roll_rate
        )
        self.game.record.record(
            variable_name="player_impact_force_n", variable=self.pawn.impact_force_n
        )
        self.game.record.record(
            variable_name="player_additional_force_n",
            variable=self.pawn.additional_force_n,
        )
        self.game.record.record(
            variable_name="player_lift_n", variable=self.pawn.lift_n
        )
        self.game.record.record(
            variable_name="player_lift_body_n", variable=self.pawn.lift_body_n
        )
        self.game.record.record(
            variable_name="player_drag_n", variable=self.pawn.drag_n
        )
        self.game.record.record(
            variable_name="player_thrust_n", variable=self.pawn.thrust_n
        )
        self.game.record.record(
            variable_name="player_position_m", variable=self.pawn.position
        )
        self.game.record.record(
            variable_name="player_orientation_quat", variable=self.pawn.orientation
        )
        self.game.record.record(
            variable_name="player_speed_mps", variable=self.pawn.speed
        )
        self.game.record.record(
            variable_name="player_acceleration_mps2",
            variable=self.pawn.acceleration_mps2,
        )

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

        self.game = None

        # No need to clean the ship:
        # It has already been done when all actors were cleaned
