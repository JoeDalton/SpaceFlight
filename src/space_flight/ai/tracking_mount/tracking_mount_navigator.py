import logging

import numpy as np

from space_flight import EPSILON_TOLERANCE
from space_flight.actors.pawn import Pawn
from space_flight.ai import Intent, Personality
from space_flight.ai.generic.generic_navigator import GenericNavigator

LOGGER = logging.getLogger()


NO_DIRECTION = np.zeros(3)


class TrackingMountNavigator(GenericNavigator):
    """
    Aim for a tracking mount (turret, tractor beam...).

    Turns the tactician's intent into a direction for the pilot to point at, using
    lead pursuit so the barrel/antenna anticipates the prey. It is purely an aimer:
    it does not fire or grab. Instead it *publishes* its result onto the pawn
    (:attr:`Pawn.aim_direction` and :attr:`Pawn.target_distance_m`), so the pawn's
    own per-frame action -- firing for a turret, grabbing for a tractor beam --
    can key off the same lead solution.
    """

    def __init__(
        self,
        game,
        pawn: Pawn,
        personality: dict = Personality.TURRET_DEFAULT,
        debug: bool = False,
    ):
        super().__init__(game=game, pawn=pawn, personality=personality, debug=debug)

    def navigate(self, intent: int, target_dict: dict) -> np.ndarray:
        """
        Turns the tactician's intent into an explicit aim direction.

        :param intent: The tactician's intent
        :param target_dict: A dictionary containing target info
        :return: The direction to point to
        """
        if intent == Intent.IDLE:
            self.engage_phase = ""
            self._publish_no_engagement()
            return NO_DIRECTION
        elif intent == Intent.ENGAGE:
            return self.engage_target(target_dict)
        else:
            return ValueError(f"Unknown intent: {intent}")

    def engage_target(self, target_dict: dict = {}) -> np.ndarray:
        """
        Aims at a target using lead pursuit and publishes the aim solution onto
        the pawn for it to act upon.

        :param target_dict: A dictionary with the target's info
        :return: The direction to point to
        """
        # Case where there is no target (Should not happen, but you never know...)
        if target_dict == {}:
            LOGGER.warning(
                f"Navigator {self.pawn.parent.name} told to engage "
                "but there's no attached target"
            )
            self._publish_no_engagement()
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
            self._publish_no_engagement()
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

        # Compute lead pursuit direction necessary for a firing/grab solution
        target_current_position = self.pawn.position + distance_m * direction
        target_current_speed = self.pawn.speed + relative_speed_vector
        aim_vector = self.compute_lead_pursuit(
            target_current_position=target_current_position,
            target_current_speed=target_current_speed,
            lead_time_s=self.personality["navigator"]["attack"]["lead_time_s"],
        )

        aim_vector_norm = np.linalg.norm(aim_vector)
        if aim_vector_norm < EPSILON_TOLERANCE:
            aim_vector = np.zeros(3)
        else:
            aim_vector /= aim_vector_norm

        # Publish the aim solution so the pawn can decide whether to act on it.
        self.pawn.aim_direction = aim_vector
        self.pawn.target_distance_m = distance_m

        return aim_vector

    def _publish_no_engagement(self):
        """
        Clear the published aim solution so the pawn does not act (no aim
        direction, unreachable distance).
        """
        self.pawn.aim_direction = np.zeros(3)
        self.pawn.target_distance_m = np.inf
