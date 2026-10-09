from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import numpy as np

from space_flight.ai import TARGET_DISTANCE_TOLERANCE_M, Intent, Personality
from space_flight.ai.generic.generic_navigator import GenericNavigator
from space_flight.utils import magnitude

if TYPE_CHECKING:
    from space_flight.actors.ordnance import Ordnance
    from space_flight.actors.pawn import Pawn
    from space_flight.game.flight_state import FlightState

_ZERO3 = np.zeros(3)


class MissileNavigator(GenericNavigator):
    """
    A guided missile's navigator. A missile has no tactician: its intent is
    always to engage the target given by its launcher, which it does by
    constant-angle pursuit at its (constant) speed.
    """

    def __init__(
        self,
        game: FlightState,
        pawn: Ordnance,
        personality: dict = Personality.MISSILE_DEFAULT,
        debug: bool = False,
    ):
        super().__init__(game=game, pawn=pawn, personality=personality, debug=debug)

    def navigate(self, intent: Intent, target_dict: dict) -> tuple[np.ndarray, float]:
        """
        Point to the target by constant-angle pursuit.

        :param intent: Always Intent.ENGAGE
        :param target_dict: Holds the target's id under "target_id"
        :return: The direction to point to, zero once the target is lost (dead or
            gone), and the missile's speed
        """
        return self.pursue(self.find_target(target_dict.get("target_id")))

    def pursue(self, target: Any) -> tuple[np.ndarray, float]:
        """
        Point to a target by constant-angle pursuit. Unlike navigate, the target
        needs not be an interacting actor (e.g. a decoy flare).

        :param target: The live target (static if it has no speed), None if lost
        :return: The direction to point to, zero if the target is lost, and the
            missile's speed
        """
        speed_mps = self.pawn.max_speed_mps
        if target is None:
            return np.zeros(3), speed_mps

        offset = np.asarray(target.position, dtype=float) - self.pawn.position
        distance_m = magnitude(offset)
        if distance_m < TARGET_DISTANCE_TOLERANCE_M:
            return np.zeros(3), speed_mps
        direction = offset / distance_m

        # Same convention as interactions.rel_velocities[self, target]. Some
        # targets (e.g. subsystems) have no speed: treat them as static.
        relative_velocity = (
            np.asarray(getattr(target, "speed", _ZERO3), dtype=float) - self.pawn.speed
        )
        lateral_speed_vector = (
            relative_velocity - np.dot(relative_velocity, direction) * direction
        )
        return (
            self.compute_constant_angle_pursuit(
                direction=direction,
                distance_m=distance_m,
                lateral_speed_vector=lateral_speed_vector,
            ),
            speed_mps,
        )

    def find_target(self, target_id: uuid.UUID | None) -> Pawn | None:
        """
        :param target_id: The target's id
        :return: The live target actor, or None if it is no longer an interacting
            actor (destroyed, dying or removed)
        """
        interactions = self.game.interactions
        try:
            target_index = interactions.get_actor_index_from_id(target_id)
            target = interactions.actors[target_index]
        except (ValueError, KeyError, IndexError):
            return None
        if target is None or getattr(target, "is_dead", False):
            return None
        return target
