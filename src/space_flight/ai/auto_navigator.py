import logging
from typing import List, Tuple

import numpy as np

from space_flight import DEBUG_DELETION
from space_flight.ai import (
    INTERACT_MAX_DISTANCE_M,
    TARGET_DISTANCE_TOLERANCE_M,
    Personality,
)
from space_flight.ai.auto_tactician import Intent
from space_flight.utils import smooth_step_down, smooth_step_up

LOGGER = logging.getLogger()

NO_DIRECTION = np.zeros(3), 100.0
WAYPOINT_MEETING_TOLERANCE_M = 50
CHASE_DISTANCE_M = 80.0


class AutoNavigator:
    """
    A class to define the aim of a bot given an intent given by a tactician, and
    passes its decision to a pilot that steers the ship.

    Outputs a direction to point to and a reference distance
    """

    def __init__(
        self, game, ship, personality: dict = Personality.DEFAULT, debug: bool = False
    ):
        self.game = game
        self.ship = ship
        self.waypoints = []
        self.next_waypoint_idx = 0
        self.distance_to_waypoint_m = 0.0
        self.has_waypoint_loop = False
        self.personality = personality
        self.debug = debug
        self.behaviour = "idle"
        self.behaviour_duration_s = 0.0
        self.time_in_spiral_s = 0.0
        self.last_update_time = self.game.game_time.get_current_time()

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
            # TODO reset spiral time if new order ? May not be necessary
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
        TODO: Not necessary anymore ?

        :param behaviour: A str describing the behaviour currently in play
        """
        current_time = self.game.game_time.get_current_time()
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

        Blends:
        - A Constant Angle Pursuit for long distance approach
        - Lead pursuit for hitting with lasers
        - Lag pursuit for too close range (+ Waiting for energy TODO)

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
        my_actor_index = self.game.interactions.get_actor_index_from_id(self.ship.id)
        try:
            target_actor_index = self.game.interactions.get_actor_index_from_id(
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
        distance_m = self.game.interactions.distances[
            my_actor_index, target_actor_index
        ]
        direction = self.game.interactions.directions[
            my_actor_index, target_actor_index, :
        ]
        relative_speed_vector = self.game.interactions.rel_velocities[
            my_actor_index, target_actor_index, :
        ]
        longitudinal_speed_scalar_mps = np.dot(relative_speed_vector, direction)

        # Check if we risk passing ahead of the target or if we already passed it
        alignment = self.game.interactions.alignments[
            my_actor_index, target_actor_index
        ]
        target_is_behind = alignment <= 0
        if target_is_behind or self.check_overshoot_risk(
            closing_speed_mps=-longitudinal_speed_scalar_mps, distance_m=distance_m
        ):
            self.record_behaviour(behaviour="reposition")
            return self.reposition(direction=direction)

        # Check if we need to extend the trajectory to avoid a spiral of death
        longitudinal_speed_vector = longitudinal_speed_scalar_mps * direction
        lateral_speed_vector = relative_speed_vector - longitudinal_speed_vector
        lateral_speed_scalar_mps = np.linalg.norm(lateral_speed_vector)

        if self.check_extend_conditions(
            closing_speed_mps=-longitudinal_speed_scalar_mps,
            lateral_speed_scalar_mps=lateral_speed_scalar_mps,
        ):
            self.record_behaviour(behaviour="extend")
            return self.extend()

        # Free to pursue target
        target_current_position = self.ship.position + distance_m * direction
        target_current_speed = self.ship.speed + relative_speed_vector

        # Compute CAP contribution
        cap_direction = self.compute_constant_angle_pursuit(
            direction=direction,
            distance_m=distance_m,
            lateral_speed_vector=lateral_speed_vector,
        )
        # Compute lead pursuit contribution
        lead_direction = self.compute_lead_pursuit(
            target_current_position=target_current_position,
            target_current_speed=target_current_speed,
            lead_time_s=self.personality["navigator"]["attack"]["lead_time_s"],
        )
        # Compute lag_pursuit contribution
        lag_direction = self.compute_lead_pursuit(
            target_current_position=target_current_position,
            target_current_speed=target_current_speed,
            lead_time_s=self.personality["navigator"]["attack"]["lag_time_s"],
        )
        # Compute weigths of pursuit strategies
        cap_weight, lead_weight, lag_weight = self.compute_engage_weights(
            distance_m=distance_m
        )
        aim_vector = (
            self.personality["navigator"]["attack"]["cap_bias"]
            * cap_direction
            * cap_weight
            + self.personality["navigator"]["attack"]["lead_bias"]
            * lead_direction
            * lead_weight
            + self.personality["navigator"]["attack"]["lag_bias"]
            * lag_direction
            * lag_weight
        )
        aim_vector_norm = np.linalg.norm(aim_vector)
        if aim_vector_norm < 1e-5:
            aim_vector = np.zeros(3)
        else:
            aim_vector /= aim_vector_norm

        # Compute desired speed
        target_speed_mps = np.linalg.norm(target_current_speed)
        pursuit_speed_mps = self.compute_pursuit_speed(
            distance_m=distance_m,
            target_speed_mps=target_speed_mps,
            longitudinal_speed_scalar_mps=longitudinal_speed_scalar_mps,
        )

        # Decide whether to shoot
        firing_alignment = np.dot(lead_direction, self.ship.forward)
        if (
            distance_m < self.personality["navigator"]["fire"]["maximum_distance_m"]
        ) and (
            firing_alignment
            > self.personality["navigator"]["fire"]["minimum_cos_angle"]
        ):
            self.ship.laser_cannon.fire()

        return aim_vector, pursuit_speed_mps

    def compute_pursuit_speed(
        self,
        distance_m: float,
        target_speed_mps: float,
        longitudinal_speed_scalar_mps: float,
    ) -> float:
        """
        Computes the desired speed in pursuit mode
        It must be the same as the target speed if it is at the desired pursuit distance
        It must increase if the target is too far and vice-versa
        TODO : effect of closing speed ?

        :param distance_m: Distance to target
        :param target_speed_mps: Speed of target
        :param longitudinal_speed_scalar_mps: relative speed in the target's direction
        :return: The desired pursuit speed
        """
        desired_speed_mps = (
            target_speed_mps + self.compute_target_distance_contribution(distance_m)
        )
        desired_speed_mps = min(max(desired_speed_mps, 0.0), self.ship.max_speed_mps)
        return desired_speed_mps

    def compute_target_distance_contribution(self, distance_m: float) -> float:
        """
        Computes the contribution of target distance to pursuit speed
        Far targets get high speed,

        :param distance_m: Distance to target
        :return: The distance contribution to pursuit speed
        """
        distance_contribution_mps = self.ship.max_speed_mps * (
            0.5
            - smooth_step_down(
                x=distance_m,
                x_step=self.personality["navigator"]["attack"][
                    "ideal_pursuit_distance_m"
                ],
                slope=self.personality["navigator"]["attack"][
                    "pursuit_speed_distance_slope"
                ],
            )
        )
        # DEBUG
        # print()
        # print(f"{distance_m=:.1f}")
        # print(f"{distance_contribution_mps=:.1f}")
        return distance_contribution_mps

    def compute_engage_weights(self, distance_m: float):
        """
        Compute weights of the pursuit strategies as a function of
        distance to target.
        They are overlapping slopes

        :param distance_m: The distance to the prey
        """
        cap_weight = smooth_step_up(
            x=distance_m,
            x_step=self.personality["navigator"]["attack"]["cap_cutoff_distance_m"],
            slope=self.personality["navigator"]["attack"]["cap_lead_cutoff_slope"],
        )
        lead_weight = smooth_step_up(
            x=distance_m,
            x_step=self.personality["navigator"]["attack"][
                "lead_low_cutoff_distance_m"
            ],
            slope=self.personality["navigator"]["attack"]["lead_lag_cutoff_slope"],
        ) * smooth_step_down(
            x=distance_m,
            x_step=self.personality["navigator"]["attack"][
                "lead_high_cutoff_distance_m"
            ],
            slope=self.personality["navigator"]["attack"]["cap_lead_cutoff_slope"],
        )
        lag_weight = smooth_step_down(
            x=distance_m,
            x_step=self.personality["navigator"]["attack"]["lag_cutoff_distance_m"],
            slope=self.personality["navigator"]["attack"]["lead_lag_cutoff_slope"],
        )
        return cap_weight, lead_weight, lag_weight

    def compute_constant_angle_pursuit(
        self, direction: np.ndarray, distance_m: float, lateral_speed_vector: np.ndarray
    ) -> np.ndarray:
        """
        Constant Angle Pursuit (CAP)
        Bring lateral velocity to zero
        Good for closing in from a long distance
        Also good for missiles until the end

        :param direction: The direction of the target
        :param distance_m: Its distance from self
        :param lateral_speed_vector: Its relative velocity on the lateral plane
        """
        # TODO Dynamic CAP strength, should vary with distance/closing_speed
        cap_strength_s = 1.0  # Or =1/omega_max_radps
        desired_vector = direction * distance_m - cap_strength_s * lateral_speed_vector
        desired_vector_norm = np.linalg.norm(desired_vector)
        # Norm can't be zero if distance != 0
        return desired_vector / desired_vector_norm

    def compute_lead_pursuit(
        self,
        target_current_position: np.ndarray,
        target_current_speed: np.ndarray,
        lead_time_s: float,
    ) -> Tuple[np.ndarray, float]:
        """
        Intercepts the target by flying to its future position
        If the lead time is null, it's pure pursuit
        If the lead time is negative, it's a lag pursuit

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

        return target_future_direction

    def check_extend_conditions(
        self,
        closing_speed_mps: float,
        lateral_speed_scalar_mps: float,
    ) -> bool:
        """
        Checks if the closing velocity is too low and the lateral velocity is too
        high for too long

        :param closing_speed_mps: How fast the target is closing in
        :param lateral_speed_scalar_mps: How fast the target is zooming sideways
        :return: Whether self should extend
        """
        if (
            closing_speed_mps
            < self.personality["navigator"]["extend"]["minimum_closing_speed_mps"]
        ) and (
            lateral_speed_scalar_mps
            > self.personality["navigator"]["extend"]["maximal_lateral_speed_mps"]
        ):
            # Velocity condition met
            # Register time in spiral
            current_time = self.game.game_time.get_current_time()
            self.time_in_spiral_s += current_time - self.last_update_time
            # Result depends on time condition
            return (
                self.time_in_spiral_s
                > self.personality["navigator"]["extend"]["maximal_time_in_spiral_s"]
            )
        else:
            # Velocity condition not met, not in spiral
            # Reset time in spiral
            self.time_in_spiral_s = 0.0
            return False

    def check_overshoot_risk(
        self,
        closing_speed_mps: float,
        distance_m: float,
    ) -> bool:
        """
        Checks if the current trajectory risks taking self farther than the target

        :param closing_speed_mps: How fast the target is closing in
            (positive for closing, negative for pulling away)
        :param distance_m: The distance to the target
        :return: Whether self should reposition
        """
        if closing_speed_mps <= 0:
            # Target pulling away, no risk of overshoot
            return False
        overshoot_time_prediction_s = distance_m / closing_speed_mps

        return (
            overshoot_time_prediction_s
            < self.personality["navigator"]["reposition"]["minimum_time_to_overshoot_s"]
        )

    def reposition(
        self,
        direction: np.ndarray,
    ) -> Tuple[np.ndarray, float]:
        """
        Turn hard away from the target to avoid passing in front of it
        Therefore, simply point in the opposite direction with the same distance

        TODO: do something for immobile targets (turrets. They should not be evaded
        the same way as ships)

        :param direction: The direction to the target
        :return: The direction to point to and its reference distance
        """
        # By definition, not in spiral => reset time in spiral
        self.time_in_spiral_s = 0.0
        return -direction, self.personality["navigator"]["turning"]["speed_mps"]

    def extend(self) -> Tuple[np.ndarray, float]:
        """
        Go straight ahead and accelerate to break the pattern

        :return: The direction to point to and its reference distance
        """
        return np.zeros(3), self.personality["navigator"]["speeding"]["speed_mps"]

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
        my_actor_index = self.game.interactions.get_actor_index_from_id(self.ship.id)
        try:
            target_actor_index = self.game.interactions.get_actor_index_from_id(
                target_dict["target_id"]
            )
        except ValueError:
            if self.debug:
                LOGGER.info(
                    f"Navigator {self.ship.parent.name}: "
                    "Target has been destroyed since last intent update."
                )
            return NO_DIRECTION

        distance = self.game.interactions.distances[my_actor_index, target_actor_index]

        # Case where the target is at zero distance (Should not happen once ship-ship
        # collisions are implemented)
        if distance < TARGET_DISTANCE_TOLERANCE_M:
            return NO_DIRECTION

        direction = self.game.interactions.directions[
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

        return (
            target_relative_position / target_distance,
            self.personality["navigator"]["regroup"]["speed_mps"],
        )

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

        return fleeing_direction, self.personality["navigator"]["speeding"]["speed_mps"]

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
        return direction, self.personality["navigator"]["patrol"]["speed_mps"]

    # %% ==== DELETING THE BOT ====

    def clean(self):
        self.ship = None
        if DEBUG_DELETION:
            LOGGER.info("Cleaned autonavigator")

    def __del__(self):
        if DEBUG_DELETION:
            LOGGER.info("Deleted autonavigator")

    # %% ==== ENGAGE OLD SWITCH ====
    def engage_target_old_switch(
        self, target_dict: dict = {}
    ) -> Tuple[np.ndarray, float]:
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
        my_actor_index = self.game.interactions.get_actor_index_from_id(self.ship.id)
        try:
            target_actor_index = self.game.interactions.get_actor_index_from_id(
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
        distance = self.game.interactions.distances[my_actor_index, target_actor_index]
        direction = self.game.interactions.directions[
            my_actor_index, target_actor_index, :
        ]
        relative_speed = self.game.interactions.rel_velocities[
            my_actor_index, target_actor_index, :
        ]
        alignment = self.game.interactions.alignments[
            my_actor_index, target_actor_index
        ]
        target_current_position = self.ship.position + distance * direction
        target_current_speed = self.ship.speed + relative_speed

        if self.check_overshoot_risk_old(
            direction=direction, relative_speed=relative_speed, distance=distance
        ):
            self.record_behaviour(behaviour="reposition")
            return self.reposition_old(direction=direction, distance=distance)

        if self.check_extend_conditions_old(alignment=alignment):
            self.record_behaviour(behaviour="extend")
            return self.extend_old()

        if self.check_attack_conditions_old(
            direction=direction,
            relative_speed=relative_speed,
            distance=distance,
            alignment=alignment,
        ):
            self.record_behaviour(behaviour="attack")
            return self.attack_target_old(
                target_current_position=target_current_position,
                target_current_speed=target_current_speed,
                distance=distance,
            )
        # Default behaviour
        self.record_behaviour(behaviour="intercept")
        return self.intercept_target_old(
            target_current_position=target_current_position,
            target_current_speed=target_current_speed,
            lead_time_s=self.personality["navigator"]["intercept"]["lead_time_s"],
        )

    def check_attack_conditions_old(
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
            (distance <= self.personality["navigator"]["attack"]["maximum_distance_m"])
            and (
                alignment
                >= self.personality["navigator"]["attack"]["minimum_cos_angle"]
            )
            and True  # Lasers TODO
            and (
                self.compute_firing_window_length(
                    direction=direction,
                    relative_speed=relative_speed,
                    distance=distance,
                )
                >= self.personality["navigator"]["fire"]["minimimum_window_duration_s"]
            )
        )

    def compute_firing_window_length_old(
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
        firing_window_width_m = (
            2
            * distance
            * np.tan(self.personality["navigator"]["fire"]["maximum_angle_rad"])
        )
        lateral_relative_speed_mps = np.linalg.norm(np.cross(relative_speed, direction))
        if lateral_relative_speed_mps < 0.1:
            # Nearly no lateral movement, all the time in the world to shoot
            return 1e6
        return firing_window_width_m / lateral_relative_speed_mps

    def check_extend_conditions_old(self, alignment: float) -> bool:
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
            and (
                self.behaviour_duration_s
                >= self.personality["navigator"]["intercept"]["maximum_duration_s"]
            )
            and (
                alignment
                < self.personality["navigator"]["intercept"]["minimum_cos_angle"]
            )
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
            and (
                self.behaviour_duration_s
                >= self.personality["navigator"]["attack"]["maximum_duration_s"]
            )
            and (
                alignment < self.personality["navigator"]["attack"]["minimum_cos_angle"]
            )
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
            and self.behaviour_duration_s
            < self.personality["navigator"]["extend"]["minimum_duration_s"]
        ):
            return True
        else:
            return False

    def check_overshoot_risk_old(
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

        return (
            overshoot_time_prediction_s
            < self.personality["navigator"]["reposition"]["minimum_time_to_overshoot_s"]
        )

    def reposition_old(
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

    def extend_old(self) -> Tuple[np.ndarray, float]:
        """
        Go straight ahead and accelerate to break the pattern

        :return: The direction to point to and its reference distance
        """
        return np.zeros(3), INTERACT_MAX_DISTANCE_M

    def attack_target_old(
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
            lead_time_s=self.personality["navigator"]["attack"]["lead_time_s"],
        )
        # Decide whether to shoot
        firing_alignment = np.dot(target_future_direction, self.ship.forward)
        if (
            distance < self.personality["navigator"]["fire"]["maximum_distance_m"]
        ) and (
            firing_alignment
            > self.personality["navigator"]["fire"]["minimum_cos_angle"]
        ):
            self.ship.laser_cannon.fire()

        return target_future_direction, reference_distance_m

    def intercept_target_old(
        self,
        target_current_position: np.ndarray,
        target_current_speed: np.ndarray,
        lead_time_s: float,
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
