import logging
from typing import List, Tuple

import numpy as np

from space_flight import DEBUG_DELETION
from space_flight.ai import INTERACT_MAX_DISTANCE_M, TARGET_DISTANCE_TOLERANCE_M
from space_flight.ai.auto_tactician import Intent
from space_flight.utils import get_current_time

LOGGER = logging.getLogger()

NO_DIRECTION = np.zeros(3), 0.0

# TODO: Navigator personality parameters ?
WAYPOINT_MEETING_TOLERANCE_M = 50
CHASE_DISTANCE_M = 80.0
OVERSHOOT_TIME_LIMIT_S = 1.5
# Extension
MINIMUM_EXTENSION_DURATION_S = 0.5
# Interception
INTERCEPT_LEAD_TIME_S = 1.5
MAXIMUM_INTERCEPT_DURATION_S = 10.0
MINIMUM_COS_ANGLE_IN_INTERCEPT_PHASE = np.cos(np.deg2rad(30))
# Attack
ATTACK_LEAD_TIME_S = 0.5
MAXIMUM_ATTACK_DURATION_S = 5.0
MINIMUM_COS_ANGLE_IN_ATTACK_PHASE = np.cos(np.deg2rad(20))
MINIMUM_FIRING_WINDOW_TIME_S = 0.5
MAX_ATTACK_DISTANCE_M = 800
MAX_FIRING_DISTANCE_M = 600
MAX_FIRING_ANGLE_RAD = np.deg2rad(5)
MIN_FIRING_COS_ANGLE = np.cos(MAX_FIRING_ANGLE_RAD)


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
        self.behaviour = "idle"
        self.behaviour_duration_s = 0.0
        self.last_update_time = get_current_time()

    def navigate(self, intent: int, target_dict: dict):
        """
        Turns the tactician's intent into explicit directions

        :return: The direction to point to and its reference distance
        """
        if intent == Intent.IDLE:
            self.engage_phase = ""
            return NO_DIRECTION
        elif intent == Intent.PATROL:
            self.engage_phase = ""
            return self.follow_waypoints()
        elif intent == Intent.ENGAGE:
            # Exact behaviour is defined and recorded inside engage_target
            return self.engage_target(target_dict)
        elif intent == Intent.EVADE:
            self.engage_phase = ""
            return self.evade_target(target_dict)
        elif intent == Intent.REGROUP:
            self.engage_phase = ""
            return self.regroup(target_dict)
        elif intent == Intent.DISENGAGE:
            self.engage_phase = ""
            return self.disengage(target_dict)
        else:
            return ValueError(f"Unknown intent: {intent}")

    def record_behaviour(self, behaviour: str):
        """
        Record which behaviour is currently running and for how long.

        TODO: Somehow manage to commit to a behaviour for a certain time ?

        :param behaviour: A str describing the behaviour currently in play
        """
        current_time = get_current_time()
        if behaviour == self.behaviour:
            # Increment time since last navigator update
            self.behaviour_duration_s += current_time - self.last_update_time
        else:
            # Reset counter and record new behaviour
            self.behaviour_duration_s = 0.0
            self.behaviour = behaviour
            if self.debug:
                LOGGER.info(
                    f"Navigator {self.ship.parent.name} switched "
                    f"to behaviour {behaviour}"
                )
        self.last_update_time = current_time

    # %% ==== ENGAGE ====
    def engage_target(self, target_dict: dict = {}) -> Tuple[np.ndarray, float]:
        """
        Engages a target and tries to attack it

        - By default, tries to intercept
        - If attack conditions are met, launch attack run
        - If breaking off conditions are met, reposition/extend

        :param target_dict: A dictionary with the target's direction, distance,
            alignment and relative velocity
        :return: The direction to point to and its reference distance
        """
        # Case where there is no target (Should not happen, but you never know...)
        if target_dict == {}:
            LOGGER.warning(
                f"Navigator {self.ship.parent.name} told to engage "
                "but there's no attached target"
            )
            return NO_DIRECTION

        # Identify self and target in interactions
        my_actor_index = self.app.interactions.get_actor_index_from_id(self.ship.id)
        try:
            target_actor_index = self.app.interactions.get_actor_index_from_id(
                target_dict["target_id"]
            )
        except ValueError:
            if self.debug:
                LOGGER.info(
                    f"Navigator {self.ship.parent.name}: "
                    "Target has been destroyed since last intent update."
                )
            return NO_DIRECTION

        # Get necessary info from interactions and pre compute target properties
        distance = self.app.interactions.distances[my_actor_index, target_actor_index]
        direction = self.app.interactions.directions[
            my_actor_index, target_actor_index, :
        ]
        relative_speed = self.app.interactions.rel_velocities[
            my_actor_index, target_actor_index, :
        ]
        alignment = self.app.interactions.alignments[my_actor_index, target_actor_index]
        target_current_position = self.ship.position + distance * direction
        target_current_speed = self.ship.speed + relative_speed

        if self.check_overshoot_risk(
            direction=direction, relative_speed=relative_speed, distance=distance
        ):
            self.record_behaviour(behaviour="reposition")
            return self.reposition(direction=direction, distance=distance)

        if self.check_extend_conditions(alignment=alignment):
            self.record_behaviour(behaviour="extend")
            return self.extend()

        if self.check_attack_conditions(
            direction=direction,
            relative_speed=relative_speed,
            distance=distance,
            alignment=alignment,
        ):
            self.record_behaviour(behaviour="attack")
            return self.attack_target(
                target_current_position=target_current_position,
                target_current_speed=target_current_speed,
                distance=distance,
            )
        # Default behaviour
        self.record_behaviour(behaviour="intercept")
        return self.intercept_target(
            target_current_position=target_current_position,
            target_current_speed=target_current_speed,
        )

    def check_attack_conditions(
        self,
        direction: np.ndarray,
        relative_speed: np.ndarray,
        distance: float,
        alignment: float,
    ) -> bool:
        """
        - distance is good
        - alignment is good
        - lasers have enough energy #TODO
        - Firing window will be long enough

        :param direction: The direction to the target
        :param relative_speed: The relative speed of the target relative to self
        :param distance: The distance to the target
        :param alignment: The cos of the angle to target
        :return: Whether to begin an attack run
        """
        return (
            (distance <= MAX_ATTACK_DISTANCE_M)
            and (alignment >= MINIMUM_COS_ANGLE_IN_ATTACK_PHASE)
            and True  # Lasers TODO
            and (
                self.compute_firing_window_length(
                    direction=direction,
                    relative_speed=relative_speed,
                    distance=distance,
                )
                >= MINIMUM_FIRING_WINDOW_TIME_S
            )
        )

    def compute_firing_window_length(
        self,
        direction: np.ndarray,
        relative_speed: np.ndarray,
        distance: float,
    ) -> float:
        """
        Computes an estimation of the firing window length based on lateral relative
        speed of target, its distance and the angular width of a shooting window

        :param direction: The direction to the target
        :param relative_speed: The relative speed of the target relative to self
        :param distance: The distance to the target
        :return: The estimated shooting window length
        """
        firing_window_width_m = 2 * distance * np.tan(MAX_FIRING_ANGLE_RAD)
        lateral_relative_speed_mps = np.linalg.norm(np.cross(relative_speed, direction))
        if lateral_relative_speed_mps < 0.1:
            # Nearly no lateral movement, all the time in the world to shoot
            return 1e6
        return firing_window_width_m / lateral_relative_speed_mps

    def check_extend_conditions(self, alignment: float) -> bool:
        """
        Check whether the current engagement behaviour has expired.
        - Has it been too long ?
        - Is the angle to target too big ?
        - Has previous extend behaviour been long enough ?

        :param alignment: The cos of the angle to target
        :return: Whether to extend the trajectory
        """
        if (
            self.behaviour == "intercept"
            and self.behaviour_duration_s >= MAXIMUM_INTERCEPT_DURATION_S
            and alignment < MINIMUM_COS_ANGLE_IN_INTERCEPT_PHASE
        ):
            if self.debug:
                angle_deg = np.rad2deg(np.arccos(alignment))
                LOGGER.info(
                    f"Navigator {self.ship.parent.name}: "
                    "Intercept took too long with unsatisfying angle "
                    f"({angle_deg} deg). Extending trajectory."
                )
            return True
        elif (
            self.behaviour == "attack"
            and self.behaviour_duration_s >= MAXIMUM_ATTACK_DURATION_S
            and alignment < MINIMUM_COS_ANGLE_IN_ATTACK_PHASE
        ):
            if self.debug:
                angle_deg = np.rad2deg(np.arccos(alignment))
                LOGGER.info(
                    f"Navigator {self.ship.parent.name}: "
                    "Attack took too long with unsatisfying angle "
                    f"({angle_deg} deg). Extending trajectory."
                )
            return True
        elif (
            self.behaviour == "extend"
            and self.behaviour_duration_s < MINIMUM_EXTENSION_DURATION_S
        ):
            return True
        else:
            return False

    def check_overshoot_risk(
        self,
        direction: np.ndarray,
        relative_speed: np.ndarray,
        distance: float,
    ) -> bool:
        """
        Check if the current trajectory risks taking self farther than the target

        :param direction: The direction to the target
        :param relative_speed: The relative speed of the target relative to self
        :param distance: The distance to the target
        :return: Whether self should reposition
        """
        closing_speed_mps = -np.dot(direction, relative_speed)
        if closing_speed_mps <= 0:
            # Target pulling away, no risk of overshoot
            return False
        overshoot_time_prediction_s = distance / closing_speed_mps

        return overshoot_time_prediction_s < OVERSHOOT_TIME_LIMIT_S

    def reposition(
        self, direction: np.ndarray, distance: float
    ) -> Tuple[np.ndarray, float]:
        """
        Turn hard away from the target to avoid passing in front of it
        Therefore, simply point in the opposite direction with the same distance

        TODO: do something for immobile targets (turrets. They should not be evaded
        the same way as ships)

        :param direction: The direction to the target
        :param distance: The distance to the target
        :return: The direction to point to and its reference distance
        """
        return -direction, distance

    def extend(self) -> Tuple[np.ndarray, float]:
        """
        Go straight ahead and accelerate to break the pattern

        :return: The direction to point to and its reference distance
        """
        return np.zeros(3), INTERACT_MAX_DISTANCE_M

    def attack_target(
        self,
        target_current_position: np.ndarray,
        target_current_speed: np.ndarray,
        distance: float,
    ) -> Tuple[np.ndarray, float]:
        """
        Intercepts the target with a reduced lead time and fire if angle is small enough

        :param target_current_position: The absolute position of the target
        :param target_current_speed: Its absolute speed
        :param distance: The distance to the target
        :return: The direction to point to and its reference distance
        """

        # Got slightly ahead of the target
        target_future_direction, reference_distance_m = self.intercept_target(
            target_current_position=target_current_position,
            target_current_speed=target_current_speed,
            lead_time_s=ATTACK_LEAD_TIME_S,
        )
        # Decide whether to shoot
        firing_alignment = np.dot(target_future_direction, self.ship.forward)
        if distance < MAX_FIRING_DISTANCE_M and firing_alignment > MIN_FIRING_COS_ANGLE:
            self.ship.laser_cannon.fire()

        return target_future_direction, reference_distance_m

    def intercept_target(
        self,
        target_current_position: np.ndarray,
        target_current_speed: np.ndarray,
        lead_time_s: float = INTERCEPT_LEAD_TIME_S,
    ) -> Tuple[np.ndarray, float]:
        """
        Intercepts the target by flying to its future position

        TODO: Should I do a lead pursuit or a lag pursuit ?

        :param target_current_position: The absolute position of the target
        :param target_current_speed: Its absolute speed
        :return: The direction to point to and its reference distance
        """
        target_future_position = (
            target_current_position + target_current_speed * lead_time_s
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
            LOGGER.warning(
                f"Navigator {self.ship.parent.name} told to evade but "
                "there's no attached target"
            )
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
