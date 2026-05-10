import logging
from typing import Tuple

import numpy as np

from space_flight.actors.pawn import Pawn
from space_flight.ai import TARGET_DISTANCE_TOLERANCE_M, Intent, Personality
from space_flight.ai.generic.generic_ship_navigator import (
    NO_DIRECTION,
    GenericShipNavigator,
)
from space_flight.utils import smooth_step_down, smooth_step_up

LOGGER = logging.getLogger()


class FighterNavigator(GenericShipNavigator):
    """
    A class to define the aim of a bot given an intent given by a tactician, and
    passes its decision to a pilot that steers the ship.

    Outputs a direction to point to and a reference distance
    """

    def __init__(
        self,
        game,
        pawn: Pawn,
        personality: dict = Personality.FIGHTER_DEFAULT,
        debug: bool = False,
    ):
        super().__init__(game=game, pawn=pawn, personality=personality, debug=debug)
        self.time_in_spiral_s = 0.0

    def navigate_intent(
        self, intent: int, target_dict: dict
    ) -> tuple[np.ndarray, float]:
        """
        Turns the tactician's intent into explicit directions

        :return: The direction to point to and the desired speed
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
        elif intent == Intent.FORMATION:
            self.engage_phase = ""
            return self.formation(target_dict)
        else:
            return ValueError(f"Unknown intent: {intent}")

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
        :return: The direction to point to and the desired speed
        """
        # Case where there is no target (Should not happen, but you never know...)
        if target_dict == {}:
            LOGGER.warning(
                f"Navigator {self.pawn.parent.name} told to engage "
                "but there's no attached target"
            )
            return NO_DIRECTION

        # Identify self and target in interactions
        my_actor_index = self.game.interactions.get_actor_index_from_id(self.pawn.id)
        try:
            target_actor_index = self.game.interactions.get_actor_index_from_id(
                target_dict["target_id"]
            )
        except ValueError:
            if self.debug:
                LOGGER.info(
                    f"Navigator {self.pawn.parent.name}: "
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

        # Compute lead pursuit direction necessary for firing solution
        target_current_position = self.pawn.position + distance_m * direction
        target_current_speed = self.pawn.speed + relative_speed_vector
        lead_direction = self.compute_lead_pursuit(
            target_current_position=target_current_position,
            target_current_speed=target_current_speed,
            lead_time_s=self.personality["navigator"]["attack"]["lead_time_s"],
        )

        # Decide whether to shoot
        firing_alignment = np.dot(lead_direction, self.pawn.forward)
        if (
            distance_m < self.personality["navigator"]["fire"]["maximum_distance_m"]
        ) and (
            firing_alignment
            > self.personality["navigator"]["fire"]["minimum_cos_angle"]
        ):
            self.pawn.laser_cannon.fire()

        # Check if we risk passing ahead of the target
        if self.check_overshoot_risk(
            closing_speed_mps=-longitudinal_speed_scalar_mps, distance_m=distance_m
        ):
            self.record_behaviour(behaviour="reposition")
            return self.reposition(direction=direction)

        # Check if we need to extend the trajectory to avoid a spiral of death
        longitudinal_speed_vector = longitudinal_speed_scalar_mps * direction
        lateral_speed_vector = relative_speed_vector - longitudinal_speed_vector
        lateral_speed_scalar_mps = np.linalg.norm(lateral_speed_vector)

        if self.check_extend_conditions(
            longitudinal_speed_scalar_mps=longitudinal_speed_scalar_mps,
            lateral_speed_scalar_mps=lateral_speed_scalar_mps,
        ):
            self.record_behaviour(behaviour="extend")
            return self.extend()

        # Pursue target
        self.record_behaviour(behaviour="pursuit")

        # Compute CAP contribution
        cap_direction = self.compute_constant_angle_pursuit(
            direction=direction,
            distance_m=distance_m,
            lateral_speed_vector=lateral_speed_vector,
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
        if aim_vector_norm < TARGET_DISTANCE_TOLERANCE_M:
            aim_vector = np.zeros(3)
        else:
            aim_vector /= aim_vector_norm

        # Compute desired speed
        target_speed_mps = np.linalg.norm(target_current_speed)
        pursuit_speed_mps = self.compute_follow_speed(
            distance_m=distance_m,
            target_speed_mps=target_speed_mps,
            longitudinal_speed_scalar_mps=longitudinal_speed_scalar_mps,
            intent="attack",
        )

        return aim_vector, pursuit_speed_mps

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

    def check_extend_conditions(
        self,
        longitudinal_speed_scalar_mps: float,
        lateral_speed_scalar_mps: float,
    ) -> bool:
        """
        Checks if the closing velocity is too low and the lateral velocity is too
        high for too long

        :param longitudinal_speed_scalar_mps: How fast the target is going in
            the self-target direction
        :param lateral_speed_scalar_mps: How fast the target is zooming sideways
        :return: Whether self should extend
        """
        if (
            np.abs(longitudinal_speed_scalar_mps)
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
        elif (
            self.behaviour == "extend"
            and self.behaviour_duration_s
            < self.personality["navigator"]["extend"]["minimum_duration_s"]
        ):
            # Extending for not enough time
            return True
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
        :return: The direction to point to and the desired speed
        """
        # By definition, not in spiral => reset time in spiral
        self.time_in_spiral_s = 0.0
        return -direction, self.personality["navigator"]["turning"]["speed_mps"]

    def extend(self) -> Tuple[np.ndarray, float]:
        """
        Go straight ahead and accelerate to break the pattern

        :return: The direction to point to and the desired speed
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
        :return: The direction to point to and the desired speed
        """
        # Case where there is no target (Should not happen, but you never know...)
        if target_dict == {}:
            LOGGER.warning(
                f"Navigator {self.pawn.parent.name} told to evade but "
                "there's no attached target"
            )
            return NO_DIRECTION

        # Identify self and target in interactions
        my_actor_index = self.game.interactions.get_actor_index_from_id(self.pawn.id)
        try:
            target_actor_index = self.game.interactions.get_actor_index_from_id(
                target_dict["target_id"]
            )
        except ValueError:
            if self.debug:
                LOGGER.info(
                    f"Navigator {self.pawn.parent.name}: "
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
