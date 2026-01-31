import logging
from typing import List, Tuple

import numpy as np

from space_flight import DEBUG_DELETION, DISTANCE_TOLERANCE_M

LOGGER = logging.getLogger()

NO_DIRECTION = np.zeros(3), 0.0

# TODO: Navigator parameters ?
WAYPOINT_MEETING_TOLERANCE_M = 10
TARGET_DISTANCE_TOLERANCE_M = 1
CHASE_DISTANCE_M = 80.0
EVADE_TIME_S = 5.0
LEAD_TIME_S = 0.5


class AutoNavigator:
    """
    A class to bundle the tactician's wishes and outputs a direction
    to point to and a reference distance
    TODO
    Reuse the relative positions, distance and speed from Interactions
    """

    def __init__(self, ship):
        self.ship = ship
        self.waypoints = []
        self.next_waypoint_idx = 0
        self.distance_to_waypoint_m = 0.0
        self.has_waypoint_loop = False

    def set_waypoints(self, waypoints: List[np.ndarray], is_loop: bool = False):
        """
        Initializes waypoints for a trajectory or a loop

        :param waypoints: A list of waypoint coordinates
        """
        assert len(waypoints) >= 1
        self.waypoints = waypoints
        self.next_waypoint_idx = 0
        self.distance_to_waypoint_m = 0.0
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
                    f"Action `{action}` not supported by the navigator"
                )
            # Update direction and distance
            temp_direction += direction * weight
            if weight > max_weight:
                max_weight = weight
                reference_distance_m = distance_m

        # Find whether the bot is going somewhere
        direction_norm = np.linalg.norm(direction)
        if direction_norm < DISTANCE_TOLERANCE_M:
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
        self.distance_to_waypoint_m = np.linalg.norm(waypoint_direction)

        # Handle the case where the next waypoint has been met already
        if self.distance_to_waypoint_m < WAYPOINT_MEETING_TOLERANCE_M:
            # Do nothing this turn and target the next waypoint next time
            self.next_waypoint_idx += 1
            return NO_DIRECTION

        # Go to the next waypoint
        direction = waypoint_direction / self.distance_to_waypoint_m
        return direction, self.distance_to_waypoint_m

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
        return target_future_direction, reference_distance_m

    def evade_target(self, target=None) -> Tuple[np.ndarray, float]:
        """
        Passes behind a target by pointing towards the position it would have
        held one second earlier were its speed constant.

        If its speed is zero, do nothing.

        TODO: This behaviour is _too_ effective, chasing a prey is not fun...

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
        reference_distance_m = 1 / np.linalg.norm(
            target_current_position - self.ship.position
        )
        return target_past_direction, reference_distance_m

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
