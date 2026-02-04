import logging
from typing import List, Tuple

import numpy as np

from space_flight import DEBUG_DELETION
from space_flight.ai import (
    INTERACT_MAX_DISTANCE_M,
    SHOOTING_MAX_DISTANCE_M,
    SHOOTING_MIN_COS_ANGLE,
    TARGET_DISTANCE_TOLERANCE_M,
)
from space_flight.ai.auto_tactician import Intent

LOGGER = logging.getLogger()

NO_DIRECTION = np.zeros(3), 0.0

# TODO: Navigator parameters ?
WAYPOINT_MEETING_TOLERANCE_M = 50
CHASE_DISTANCE_M = 80.0
LEAD_TIME_S = 0.5


class AutoNavigator:
    """
    A class to define the aim of a bot given an intent given by a tactician, and
    passes its decision to a pilot that steers the ship.

    Outputs a direction to point to and a reference distance
    """

    def __init__(self, app, ship, debug: bool = False):
        self.app = app
        self.ship = ship
        self.waypoints = []
        self.next_waypoint_idx = 0
        self.distance_to_waypoint_m = 0.0
        self.has_waypoint_loop = False
        self.debug = debug

    def navigate(self, intent: int, target_dict: dict):
        """
        Turns the tactician's intent into

        :return: The direction to point to and its reference distance
        """
        if intent == Intent.IDLE:
            return NO_DIRECTION
        elif intent == Intent.PATROL:
            return self.follow_waypoints()
        elif intent == Intent.ENGAGE:
            return self.engage_target(target_dict)
        elif intent == Intent.EVADE:
            return self.evade_target(target_dict)
        elif intent == Intent.REGROUP:
            return self.regroup(target_dict)
        elif intent == Intent.DISENGAGE:
            return self.disengage(target_dict)
        else:
            return ValueError(f"Unknown intent: {intent}")

    # %% ==== ENGAGE ====
    def engage_target(self, target_dict: dict = {}) -> Tuple[np.ndarray, float]:
        """
        Engages a target and tries to attack it

        TODO: fine attack/reposition/chase logic

        :param target_dict: A dictionary with the target's direction, distance,
            alignment and relative velocity
        :return: The direction to point to and its reference distance
        """
        # Case where there is no target (Should not happen, but you never know...)
        if target_dict == {}:
            LOGGER.warning(f"{self} told to engage but there's no attached target")
            return NO_DIRECTION

        # Identify self and target in interactions
        my_actor_index = self.app.interactions.get_actor_index_from_id(self.ship.id)
        try:
            target_actor_index = self.app.interactions.get_actor_index_from_id(
                target_dict["target_id"]
            )
        except ValueError:
            if self.debug:
                LOGGER.info("Target has been destroyed since last intent update.")
            return NO_DIRECTION

        # Get necessary info from interactions
        distance = self.app.interactions.distances[my_actor_index, target_actor_index]
        direction = self.app.interactions.directions[
            my_actor_index, target_actor_index, :
        ]
        relative_speed = self.app.interactions.rel_velocities[
            my_actor_index, target_actor_index, :
        ]
        alignment = self.app.interactions.alignments[my_actor_index, target_actor_index]

        # Use the old "chase target method" but using the interactions info
        # Find the future position of the target
        target_current_position = self.ship.position + distance * direction
        target_current_speed = self.ship.speed + relative_speed
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

        # Decide whether to shoot
        if distance < SHOOTING_MAX_DISTANCE_M and alignment > SHOOTING_MIN_COS_ANGLE:
            self.ship.laser_cannon.fire()

        return target_future_direction, reference_distance_m

    # %% ==== EVADE ====

    def evade_target(self, target_dict: dict = {}) -> Tuple[np.ndarray, float]:
        """
        Passes behind a target: since the target is threatening, it means that it's
        roughly pointing towards self.
        Therefore, simply point in its direction with 2x the distance

        TODO: do something for immobile targets (turrets. They should not be evaded
        the same way as ships)

        TODO: add randomness to avoid locking in circles

        :param target_dict: A dictionary with the target's direction and distance
        :return: The direction to point to and its reference distance
        """
        # Case where there is no target (Should not happen, but you never know...)
        if target_dict == {}:
            LOGGER.warning(f"{self} told to evade but there's no attached target")
            return NO_DIRECTION

        # Identify self and target in interactions
        my_actor_index = self.app.interactions.get_actor_index_from_id(self.ship.id)
        target_actor_index = self.app.interactions.get_actor_index_from_id(
            target_dict["target_id"]
        )

        distance = self.app.interactions.distances[my_actor_index, target_actor_index]

        # Case where the target is at zero distance (Should not happen once ship-ship
        # collisions are implemented)
        if distance < TARGET_DISTANCE_TOLERANCE_M:
            return NO_DIRECTION

        direction = self.app.interactions.directions[
            my_actor_index, target_actor_index, :
        ]

        return direction, 2 * distance

    # %% ==== REGROUP ====
    def regroup(self, target_dict={}) -> Tuple[np.ndarray, float]:
        """
        Regroups with allies. If none are left, go to the center of the world

        :param target_dict: A dictionary with the target's position
        :return: The direction to point to and its reference distance
        """
        target_relative_position = target_dict["position"] - self.ship.position
        target_distance = np.linalg.norm(target_relative_position)

        # Case where the target is at zero distance
        if target_distance < TARGET_DISTANCE_TOLERANCE_M:
            return NO_DIRECTION

        return target_relative_position / target_distance, target_distance

    # %% ==== DISENGAGE ====
    def disengage(self, target_dict={}) -> Tuple[np.ndarray, float]:
        """
        Flees from the danger zone, defined as the center of gravity of all foes

        :param target_dict: A dictionary with the target's position
        :return: The direction to point to and its reference distance
        """
        target_relative_position = target_dict["position"] - self.ship.position
        target_distance = np.linalg.norm(target_relative_position)

        # Case where the target is at zero distance
        if target_distance < TARGET_DISTANCE_TOLERANCE_M:
            return NO_DIRECTION

        fleeing_direction = -target_relative_position / target_distance

        return fleeing_direction, INTERACT_MAX_DISTANCE_M

    # %% ==== PATROL ====

    def set_waypoints(self, waypoints: List[np.ndarray], is_loop: bool = False):
        """
        Initializes waypoints for a trajectory or a loop

        :param waypoints: A list of waypoint coordinates
        """
        assert len(waypoints) >= 1
        self.waypoints = waypoints
        self.next_waypoint_idx = 0
        self.has_waypoint_loop = is_loop

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
        distance_to_waypoint_m = np.linalg.norm(waypoint_direction)

        # Handle the case where the next waypoint has been met already
        if distance_to_waypoint_m < WAYPOINT_MEETING_TOLERANCE_M:
            # Do nothing this turn and target the next waypoint next time
            self.next_waypoint_idx += 1
            return NO_DIRECTION

        # Go to the next waypoint
        direction = waypoint_direction / distance_to_waypoint_m
        return direction, distance_to_waypoint_m

    # %% ==== DELETING THE BOT ====

    def clean(self):
        self.ship = None
        if DEBUG_DELETION:
            LOGGER.info("Cleaned autonavigator")

    def __del__(self):
        if DEBUG_DELETION:
            LOGGER.info("Deleted autonavigator")
