from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np

from space_flight import EPSILON_TOLERANCE
from space_flight.actors.pawn import Pawn
from space_flight.ai import Intent, Personality
from space_flight.ai.generic.generic_navigator import GenericNavigator
from space_flight.ai.interactions import pair_geometry
from space_flight.utils import magnitude

if TYPE_CHECKING:
    from space_flight.game.flight_state import FlightState

LOGGER = logging.getLogger()


NO_DIRECTION = np.zeros(3)


class TrackingMountNavigator(GenericNavigator):
    """
    Aim for a tracking mount (turret, tractor beam...).

    Turns the tactician's intent into a direction for the pilot to point at, using
    lead pursuit so the barrel/antenna anticipates the prey. It is purely an aimer:
    it does not fire or grab. Instead it *publishes* its result onto the pawn
    (:attr:`TrackingMount.aim_direction` and
    :attr:`TrackingMount.target_distance_m`), so the pawn's
    own per-frame action -- firing for a turret, grabbing for a tractor beam --
    can key off the same lead solution.
    """

    def __init__(
        self,
        game: FlightState,
        pawn: Pawn,
        personality: dict = Personality.TURRET_DEFAULT,
        debug: bool = False,
    ):
        super().__init__(game=game, pawn=pawn, personality=personality, debug=debug)

    def navigate(self, intent: Intent, target_dict: dict) -> np.ndarray:
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
        if intent == Intent.ENGAGE:
            return self.engage_target(target_dict)
        raise ValueError(f"Unknown intent: {intent}")

    def engage_target(self, target_dict: dict = {}) -> np.ndarray:
        """
        Aims at a target using lead pursuit and publishes the aim solution onto
        the pawn for it to act upon.

        :param target_dict: A dictionary with the target's info
        :return: The direction to point to
        """
        if self._has_no_target(target_dict, "engage"):
            self._publish_no_engagement()
            return NO_DIRECTION

        # Get necessary info from interactions and pre compute target properties
        geometry = pair_geometry(
            self.game.interactions, self.pawn.id, target_dict["target_id"]
        )
        if geometry is None:
            self._log_target_lost()
            self._publish_no_engagement()
            return NO_DIRECTION
        distance_m, direction, relative_speed_vector = geometry

        # Compute lead pursuit direction necessary for a firing/grab solution
        # TODO Without auto-aim, bolts go down the barrel and inherit the ship's
        #  velocity, so a firing solution should lead by the *relative* velocity
        #  over the laser's time of flight (see AutoAim.predict_target_position),
        #  not by the absolute velocity over a fixed lead time.
        target_current_position = self.pawn.position + distance_m * direction
        target_current_speed = self.pawn.speed + relative_speed_vector
        aim_vector = self.compute_lead_pursuit(
            target_current_position=target_current_position,
            target_current_speed=target_current_speed,
            lead_time_s=self.personality["navigator"]["attack"]["lead_time_s"],
        )

        aim_vector_norm = magnitude(aim_vector)
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
