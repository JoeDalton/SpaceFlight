import logging
from typing import Tuple

import numpy as np

from space_flight import EPSILON_TOLERANCE
from space_flight.actors.pawn import Pawn
from space_flight.ai import Intent, Personality
from space_flight.ai.generic.generic_navigator import GenericNavigator

LOGGER = logging.getLogger()


NO_DIRECTION = np.zeros(3)


class TurretNavigator(GenericNavigator):
    """
    A class to define the aim of a bot given an intent given by a tactician, and
    passes its decision to a pilot that steers the turret.

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

    def navigate(self, intent: int, target_dict: dict) -> np.ndarray:
        """
        Turns the tactician's intent into explicit directions

        :param intent: The tactician's intent
        :param target_dict: A dictionary containing target info
        :return: The direction to point to
        """
        if intent == Intent.IDLE:
            self.engage_phase = ""
            return NO_DIRECTION
        elif intent == Intent.ENGAGE:
            return self.engage_target(target_dict)
        else:
            return ValueError(f"Unknown intent: {intent}")

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

        # Compute lead pursuit direction necessary for firing solution
        target_current_position = self.pawn.position + distance_m * direction
        target_current_speed = self.pawn.speed + relative_speed_vector
        aim_vector = self.compute_lead_pursuit(
            target_current_position=target_current_position,
            target_current_speed=target_current_speed,
            lead_time_s=self.personality["navigator"]["attack"]["lead_time_s"],
        )

        # Decide whether to shoot
        firing_alignment = np.dot(aim_vector, self.pawn.forward)
        if (
            distance_m < self.personality["navigator"]["fire"]["maximum_distance_m"]
        ) and (
            firing_alignment
            > self.personality["navigator"]["fire"]["minimum_cos_angle"]
        ):
            self.pawn.laser_cannon.fire()

        aim_vector_norm = np.linalg.norm(aim_vector)
        if aim_vector_norm < EPSILON_TOLERANCE:
            aim_vector = np.zeros(3)
        else:
            aim_vector /= aim_vector_norm

        return aim_vector
