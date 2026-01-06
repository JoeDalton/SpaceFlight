import logging
from typing import List, Tuple

import numpy as np
from direct.showbase.ShowBaseGlobal import globalClock
from simple_pid import PID

from space_flight import DEBUG_DELETION
from space_flight.utils import (
    low_pass_filter_first_order,
    rotate_single_vector,
    safe_angle_rad,
)

LOGGER = logging.getLogger()


NO_DIRECTION = np.zeros(3), 0.0

# TODO: Pilot parameters ?
ROLL_TOLERANCE = 1e-2

# TODO: Navigator parameters ?
WAYPOINT_MEETING_TOLERANCE_M = 10
MIX_DISTANCE_TOLERANCE_M = 1e-2
TARGET_DISTANCE_TOLERANCE_M = 1
CHASE_DISTANCE_M = 80.0
EVADE_TIME_S = 1.0
LEAD_TIME_S = 1.0


class AutoPilot:
    def __init__(self, ship):
        self.ship = ship
        self.pid_yaw = PID(
            Kp=1.0,
            Ki=0.0,
            Kd=0.0,
            setpoint=0.0,
            starting_output=0.0,
            sample_time=0.1,
            error_map=safe_angle_rad,
            time_fn=globalClock.getFrameTime,
            output_limits=(-1.0, 1.0),
        )
        self.pid_pitch = PID(
            Kp=-1.0,
            Ki=0.0,
            Kd=0.0,
            setpoint=0.0,
            starting_output=0.0,
            sample_time=0.1,
            error_map=safe_angle_rad,
            time_fn=globalClock.getFrameTime,
            output_limits=(-1.0, 1.0),
        )
        self.pid_roll = PID(
            Kp=-1.0,
            Ki=0.0,
            Kd=0.0,
            setpoint=0.0,
            starting_output=0.0,
            sample_time=0.1,
            error_map=safe_angle_rad,
            time_fn=globalClock.getFrameTime,
            output_limits=(-1.0, 1.0),
        )
        self.filter_time = 0.5

        self.yaw_rate = 0.0
        self.pitch_rate = 0.0
        self.roll_rate = 0.0
        self.throttle = 0.0
        self.throttle_rate = 0.0

        self.angle_to_target_deg = 0.0

        # Debug
        self.target_x = 0.0
        self.target_y = 0.0
        self.target_z = 0.0
        self.yaw_error_deg = 0.0
        self.pitch_error_deg = 0.0
        self.roll_error_deg = 0.0
        self.yaw_rate_command = 0.0
        self.pitch_rate_command = 0.0
        self.roll_rate_command = 0.0
        self.throttle_command = 0.0

    def set_on(
        self,
        current_normalized_yaw_rate_command: float = 0.0,
        current_normalized_pitch_rate_command: float = 0.0,
        current_normalized_roll_rate_command: float = 0.0,
    ):
        """
        Sets the Auto pilot on
        """
        self.pid_yaw.set_auto_mode(
            True, last_output=current_normalized_yaw_rate_command
        )
        self.pid_pitch.set_auto_mode(
            True, last_output=current_normalized_pitch_rate_command
        )
        self.pid_roll.set_auto_mode(
            True, last_output=current_normalized_roll_rate_command
        )

    def set_off(self):
        """
        Sets the Auto pilot off
        """
        self.pid_yaw.set_auto_mode(False)
        self.pid_pitch.set_auto_mode(False)
        self.pid_roll.set_auto_mode(False)

    def pilot(
        self,
        target_direction: np.ndarray = np.zeros(3),
        reference_distance_m: float = 0.0,
    ):
        """
        Given a target direction and the current orientation of the ship, compute the
        yaw, pitch and roll rates that will be applied to the trajectory

        TODO : take into account the speed vector instead of ship axes to account for
        nicer flight dynamics (sideslip, AoA) ?

        TODO : Add pilot skill modifiers ?
        """
        dt = globalClock.getDt()

        # Update throttle
        throttle_command = max(min(self.throttle + dt * self.throttle_rate, 1.0), 0.0)

        # Compute directions
        target_direction_norm = np.linalg.norm(target_direction)
        if target_direction_norm == 0.0:
            yaw_error = 0.0
            pitch_error = 0.0
            roll_error = 0.0
            self.angle_to_target_deg = 0.0
        else:
            # Find ship axes
            # TODO remove normalization since the autonavigator is supposed to give
            # either a null or a unit direction
            target_direction = target_direction / target_direction_norm
            ship_quat = np.quaternion(*self.ship.orientation)
            ship_x = rotate_single_vector(ship_quat, np.array([1.0, 0.0, 0.0]))
            ship_y = rotate_single_vector(ship_quat, np.array([0.0, 1.0, 0.0]))
            ship_z = rotate_single_vector(ship_quat, np.array([0.0, 0.0, 1.0]))
            # Project target direction on ship axes
            target_x = np.dot(ship_x, target_direction)
            target_y = np.dot(ship_y, target_direction)
            target_z = np.dot(ship_z, target_direction)
            # Find angle errors
            yaw_error = np.arctan2(target_x, target_y)
            pitch_error = np.arctan2(target_z, target_y)
            roll_error = np.arctan2(target_x, target_z)
            # Clip roll error to zero if pitch and roll errors are small enough
            if (yaw_error**2 + pitch_error**2) < ROLL_TOLERANCE:
                roll_error = 0.0

            # Debug output
            self.target_x = target_x
            self.target_y = target_y
            self.target_z = target_z
            self.yaw_error_deg = np.rad2deg(yaw_error)
            self.pitch_error_deg = np.rad2deg(pitch_error)
            self.roll_error_deg = np.rad2deg(roll_error)

            angle_to_target_rad = np.arccos(np.dot(ship_y, target_direction))
            self.angle_to_target_deg = np.rad2deg(angle_to_target_rad)

        # Update throttle command
        self.throttle_rate = AutoPilot.simple_throttle_controller(
            angle_to_target_deg=self.angle_to_target_deg,
            reference_distance_m=reference_distance_m,
        )

        # Update PID commands for turn rates
        yaw_rate_command = self.pid_yaw(yaw_error)
        pitch_rate_command = self.pid_pitch(pitch_error)
        roll_rate_command = self.pid_roll(roll_error)

        # Debug
        self.yaw_rate_command = yaw_rate_command
        self.pitch_rate_command = pitch_rate_command
        self.roll_rate_command = roll_rate_command

        # Low-pass filter on command to find "realistic" turn rates
        [
            self.throttle,
            self.yaw_rate,
            self.pitch_rate,
            self.roll_rate,
        ] = low_pass_filter_first_order(
            value=np.array(
                [
                    throttle_command,
                    yaw_rate_command,
                    pitch_rate_command,
                    roll_rate_command,
                ]
            ),
            previous=np.array(
                [self.throttle, self.yaw_rate, self.pitch_rate, self.roll_rate]
            ),
            dt=dt,
            rise_time=self.filter_time,
            fall_time=self.filter_time,
        )

        return self.throttle, self.yaw_rate, self.pitch_rate, self.roll_rate

    @staticmethod
    def simple_throttle_controller(
        angle_to_target_deg: float, reference_distance_m: float
    ) -> float:
        """
        I want the reference distance to go to zero and the angle to target to go to
        zero.
        First, decrease throttle for too high angles, especially if it's been too long
        => PI controller
        Second, we want a reference distance to go to zero
        =>
         - Increase if getting away while in the right direction, diminish otherwise
         - The opposite if getting closer => P(I)D controller with a twist ?

        TODO: Use 2nd order polynomials instead of if conditions

        TODO: Not sure this is a good controller. Especially with reference distances
        that are difficult to determine for boids

        :param angle_to_target_deg: _description_
        :param reference_distance_float_deg: _description_
        :return: _description_
        """
        throttle_rate = 0.0
        throttle_factor = 0.05
        # Decrease throttle if the target is at too much of an angle
        if angle_to_target_deg > 30:
            throttle_rate -= throttle_factor
        elif angle_to_target_deg > 60:
            throttle_rate -= 2 * throttle_factor
        elif angle_to_target_deg > 90:
            throttle_rate -= 3 * throttle_factor
        elif angle_to_target_deg > 120:
            throttle_rate -= 4 * throttle_factor
        # Increase throttle if the target is too far, TODO the opposite if <0
        if reference_distance_m > 10:
            throttle_rate += 0.5 * throttle_factor
        elif reference_distance_m > 100:
            throttle_rate += 1.5 * throttle_factor
        elif reference_distance_m > 200:
            throttle_rate += 5 * throttle_factor
        elif reference_distance_m > 400:
            throttle_rate += 10 * throttle_factor

        return throttle_rate

    def clean(self):
        self.ship = None
        if DEBUG_DELETION:
            LOGGER.info("Cleaned autopilot")

    def __del__(self):
        if DEBUG_DELETION:
            LOGGER.info("Deleted autopilot")


class AutoNavigator:
    """
    A class to bundle the tactician's wishes and outputs a direction
    to point to and a reference distance
    TODO
    Determines the direction vector that the AutoPilot should aim for by computing the
    behaviour forces and using the weights from the AutoTactician
    """

    def __init__(self, ship):
        self.ship = ship
        self.waypoints = []
        self.next_waypoint_idx = 0
        self.distance_to_waypoint = 0.0
        self.has_waypoint_loop = False

    def set_waypoints(self, waypoints: List[np.ndarray], is_loop: bool = False):
        """
        Initializes waypoints for a trajectory or a loop

        :param waypoints: A list of waypoint coordinates
        """
        assert len(waypoints) >= 1
        self.waypoints = waypoints
        self.next_waypoint_idx = 0
        self.distance_to_waypoint = 0.0
        self.has_waypoint_loop = is_loop

    def navigate(self, tactician_thoughts: List[dict] = []) -> Tuple[np.ndarray, float]:
        """
        Bundles the tactician's wishes and outputs a direction
        to point to and a reference distance

        :return: The direction to point to and its reference distance
        """
        # # Temporary: follow waypoints (or idle if no waypoints)
        # return self.follow_waypoints()

        # Handle the case where the tactician has no thoughts
        if len(tactician_thoughts) == 0:
            return NO_DIRECTION

        # Loop over the tactician's thoughts
        temp_direction = np.zeros(3)
        max_weight = 0
        reference_distance_m = 0.0
        for thought in tactician_thoughts:
            # Compute the direction and distance for this thought
            action = thought["action"]
            weight = thought["weight"]
            if action == "follow_waypoints":
                direction, distance_m = self.follow_waypoints()
            elif action == "chase_target":
                target = thought["target"]
                direction, distance_m = self.chase_target(target=target)
            elif action == "evade_target":
                target = thought["target"]
                direction, distance_m = self.evade_target(target=target)
            elif action == "flee_from_target":
                target = thought["target"]
                direction, distance_m = self.flee_from_target(target=target)
            else:
                raise NotImplementedError(
                    f"Action {action} not supported by the navigator"
                )
            # Update direction and distance
            temp_direction += direction * weight
            if weight > max_weight:
                reference_distance_m = distance_m

        # Find whether the bot is going somewhere
        direction_norm = np.linalg.norm(direction)
        if direction_norm < MIX_DISTANCE_TOLERANCE_M:
            # LOGGER.info("Navigator: direction mix has a too low norm")
            return NO_DIRECTION

        # Normalize direction and return
        direction = direction / direction_norm
        return direction, reference_distance_m

    def follow_waypoints(self) -> Tuple[np.ndarray, float]:
        """
        Goes to the next available waypoint

        :return: The direction to point to and its reference distance
        """
        # Handle the case where waypoints have already been visited
        if self.next_waypoint_idx == len(self.waypoints):
            if self.has_waypoint_loop:
                # Start the loop again
                self.next_waypoint_idx = 0
            else:
                # It's not a loop.
                # Empty list and return no direction
                self.waypoints = []
                self.next_waypoint_idx = 0
                return NO_DIRECTION

        # Find next waypoint
        next_waypoint = self.waypoints[self.next_waypoint_idx]
        waypoint_direction = next_waypoint - self.ship.position
        # Keep the distance as an attribute for debugging
        self.distance_to_waypoint = np.linalg.norm(waypoint_direction)

        # Handle the case where the next waypoint has been met already
        if self.distance_to_waypoint < WAYPOINT_MEETING_TOLERANCE_M:
            # Do nothing this turn and target the next waypoint next time
            self.next_waypoint_idx += 1
            return NO_DIRECTION

        # Go to the next waypoint
        direction = waypoint_direction / self.distance_to_waypoint
        return direction, self.distance_to_waypoint

    def chase_target(self, target=None) -> Tuple[np.ndarray, float]:
        """
        Chases a target by pointing towards the position it will hold LEAD_TIME_S later
        should its speed remain constant.
        The reference distance is the distance to the target itself.

        Can also be used to follow a formation leader.

        :param target: A target object with a position attribute and an optional
                speed attribute
        :return: The direction to point to and its reference distance
        """
        # Case where there is no target
        if target is None:
            return NO_DIRECTION

        # Find the future position of the target
        target_current_position = target.position
        try:
            target_current_speed = target.speed
        except AttributeError:
            target_current_speed = np.zeros(3)
        target_future_position = (
            target_current_position + target_current_speed * LEAD_TIME_S
        )

        # Compute direction to point to
        target_future_direction = target_future_position - self.ship.position
        target_future_distance_m = np.linalg.norm(target_future_direction)
        if target_future_distance_m < TARGET_DISTANCE_TOLERANCE_M:
            target_future_direction = np.zeros(3)
        else:
            target_future_direction /= target_future_distance_m

        # Find reference distance. It's the distance to the target minus the distance
        # that should be left behind the bot and the target
        reference_distance_m = max(
            0.0,
            np.linalg.norm(target_current_position - self.ship.position)
            - CHASE_DISTANCE_M,
        )
        return target_future_position, reference_distance_m

    def evade_target(self, target=None) -> Tuple[np.ndarray, float]:
        """
        Passes behind a target by pointing towards the position it would have
        held one second earlier were its speed constant.

        If its speed is zero, do nothing.

        :param target: A target object with a position attribute and an optional
                speed attribute
        :return: The direction to point to and its reference distance
        """
        # Case where there is no target
        if target is None:
            return NO_DIRECTION

        # Find the past position of the target
        target_current_position = target.position
        try:
            target_current_speed = target.speed
        except AttributeError:
            # Immobile target, nothing to evade from
            return NO_DIRECTION
        target_past_position = (
            target_current_position - target_current_speed * EVADE_TIME_S
        )
        # Compute direction to point to
        target_past_direction = target_past_position - self.ship.position
        target_past_distance_m = np.linalg.norm(target_past_direction)
        if target_past_distance_m < TARGET_DISTANCE_TOLERANCE_M:
            target_past_direction = np.zeros(3)
        else:
            target_past_direction /= target_past_distance_m
        # Find reference distance
        reference_distance_m = np.linalg.norm(
            target_current_position - self.ship.position
        )
        return target_past_position, reference_distance_m

    def flee_from_target(self, target=None) -> Tuple[np.ndarray, float]:
        """
        Get as far away from the target as possible.
        TODO: use boost if possible ?

        Can also be used to avoid a collision

        :param target: A target object with a position attribute
        :return: The direction to point to and its reference distance
        """
        # Case where there is no target
        if target is None:
            return NO_DIRECTION

        # Find the target's direction
        target_current_position = target.position

        target_current_direction = target_current_position - self.ship.position
        target_current_distance_m = np.linalg.norm(target_current_direction)
        if target_current_distance_m < TARGET_DISTANCE_TOLERANCE_M:
            target_current_direction = np.zeros(3)
        else:
            target_current_direction /= target_current_distance_m
        # Find fleeing direction
        fleeing_direction = -target_current_direction
        # Find reference distance
        reference_distance_m = 1e4

        return fleeing_direction, reference_distance_m

    def clean(self):
        self.ship = None
        if DEBUG_DELETION:
            LOGGER.info("Cleaned autonavigator")

    def __del__(self):
        if DEBUG_DELETION:
            LOGGER.info("Deleted autonavigator")


class AutoTactician:
    """
    TODO
    Finds the proper strategy for a bot:
    - Select the most valuable target (enemy to kill, friend to escort,
        patrol to do, should be scriptable ?)
    - Weigh the behaviour forces
    - The weights could depend on an aggressive/defensive/cowardly personnality
    - They may depend on the situation and/or a scenario
    """

    def __init__(self, ship):
        self.ship = ship

    def think(self):
        """
        Example of result

        behaviours = [
            {
                "action": "flee",
                "target": <some asteroid that's too close>,
                "weight": 10,
            },
            {
                "action": "evade",
                "target": <a menacing enemy ship>,
                "weight": 5,
            },
            {
                "action": "follow_waypoints", # Only one of those please
                "weight": 1,
            },
            {
                "action": "chase",
                "target": <a vulnerable enemy>, # Or a leader to follow
                "weight": 1,
            },
        ]

        Then:
        - The navigator uses the distance associated with the most weighted behaviour
        - The navigator makes a weighted average of all behaviour directions. If
            the average is null, return NO_DIRECTION

        TODO: For the flee problem, use a global array of all collidable objects ?
        Or use the collision system of panda3d ?
        Aaaaaaaaaaaaaaaaaaah, paniiiiiiic !!!

        """
        my_thoughts = [
            {
                "action": "follow_waypoints",
                "weight": 1,
            },
        ]

        return my_thoughts

    def clean(self):
        self.ship = None
        if DEBUG_DELETION:
            LOGGER.info("Cleaned autotactician")

    def __del__(self):
        if DEBUG_DELETION:
            LOGGER.info("Deleted autotactician")
