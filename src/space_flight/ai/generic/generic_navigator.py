import logging

import numpy as np

from space_flight import DEBUG_DELETION
from space_flight.actors.pawn import Pawn
from space_flight.ai import TARGET_DISTANCE_TOLERANCE_M, Personality

LOGGER = logging.getLogger()


class GenericNavigator:
    """
    A class to define the aim of a bot given an intent given by a tactician, and
    passes its decision to a pilot that controls the pawn
    """

    def __init__(
        self,
        game,
        pawn: Pawn,
        personality: dict = Personality.FIGHTER_DEFAULT,
        debug: bool = False,
    ):
        self.game = game
        self.pawn: Pawn = pawn
        self.personality: dict = personality
        self.debug = debug
        self.behaviour = "idle"
        self.behaviour_duration_s = 0.0
        self.last_update_time = self.game.game_time.get_current_time()

    def navigate(self, intent: int, target_dict: dict):
        """
        Turns the tactician's intent and collision avoidance into explicit directions

        :param intent: The tactician's intent
        :param target_dict: A dictionary containing target info
        :return: Explicit directions
        """
        raise NotImplementedError

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
                    f"Navigator {self.pawn.parent.name} switched "
                    f"to behaviour {behaviour}"
                )
        self.last_update_time = current_time

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
        :return: The direction to point to
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
    ) -> np.ndarray:
        """
        Intercepts the target by pointing to its future position
        If the lead time is null, it's pure pursuit
        If the lead time is negative, it's a lag pursuit

        :param target_current_position: The absolute position of the target
        :param target_current_speed: Its absolute speed
        :return: The direction to point to
        """
        target_future_position = (
            target_current_position + target_current_speed * lead_time_s
        )

        # Compute direction to point to
        target_future_direction = target_future_position - self.pawn.position
        target_future_distance_m = np.linalg.norm(target_future_direction)
        if target_future_distance_m < TARGET_DISTANCE_TOLERANCE_M:
            target_future_direction = np.zeros(3)
        else:
            target_future_direction /= target_future_distance_m

        return target_future_direction

    def clean(self):
        self.pawn = None
        self.game = None
        if DEBUG_DELETION:
            LOGGER.info("Cleaned autonavigator")

    def __del__(self):
        if DEBUG_DELETION:
            LOGGER.info("Deleted autonavigator")
