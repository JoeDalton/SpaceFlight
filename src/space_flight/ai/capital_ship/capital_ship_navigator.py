import logging
from typing import Tuple

import numpy as np

from space_flight.actors.pawn import Pawn
from space_flight.ai import Intent, Personality
from space_flight.ai.generic.generic_ship_navigator import (
    NO_DIRECTION,
    GenericShipNavigator,
)

LOGGER = logging.getLogger()


class CapitalShipNavigator(GenericShipNavigator):
    """
    A class to define the aim of a bot given an intent given by a tactician, and
    passes its decision to a pilot that steers the ship.

    Outputs a direction to point to and a reference distance
    """

    def __init__(
        self,
        game,
        pawn: Pawn,
        personality: dict = Personality.CAPITAL_SHIP_DEFAULT,
        debug: bool = False,
    ):
        super().__init__(game=game, pawn=pawn, personality=personality, debug=debug)

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
            return self.engage_target(target_dict)
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
        Engages a target. TODO
        Must bring the target to the prefered direction at the desired distance
        and speed.

        :param target_dict: A dictionary with the target's direction, distance,
            alignment and relative velocity
        :return: The direction to point to and the desired speed
        """
        raise NotImplementedError
