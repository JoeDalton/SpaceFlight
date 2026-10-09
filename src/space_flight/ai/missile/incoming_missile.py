"""
The "missile incoming" message: every guided missile in flight tells its
target where it is, each frame, so that the target can decide when and how to
evade or drop flares (see OrdnanceController and Fighter.drop_flare).

The message lives in the target's ``incoming_missiles`` dictionary, keyed by the
missile controller's id. Only actors with that dictionary (pawns) receive it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

from space_flight.utils import magnitude

if TYPE_CHECKING:
    from space_flight.actors.ordnance import OrdnanceController
    from space_flight.actors.pawn import Pawn


@dataclass
class IncomingMissile:
    """
    A guided missile homing on the actor holding this message.

    :param controller: The missile's controller
    :param position: The missile's position
    :param distance_m: The distance between the missile and its target
    :param closing_speed_mps: The rate at which that distance shrinks (negative
        while the target outruns the missile)
    """

    controller: OrdnanceController
    position: np.ndarray
    distance_m: float
    closing_speed_mps: float

    @classmethod
    def between(cls, controller: OrdnanceController, target: Any) -> IncomingMissile:
        """
        :param controller: The missile's controller
        :param target: The missile's target (static if it has no speed)
        :return: The message for the target
        """
        missile = controller.pawn
        offset = np.asarray(target.position, dtype=float) - missile.position
        distance_m = float(magnitude(offset))
        relative_velocity = (
            np.asarray(getattr(target, "speed", np.zeros(3)), dtype=float)
            - missile.speed
        )
        closing_speed_mps = (
            -float(np.dot(relative_velocity, offset)) / distance_m
            if distance_m > 0.0
            else 0.0
        )
        return cls(
            controller=controller,
            position=np.array(missile.position, dtype=float),
            distance_m=distance_m,
            closing_speed_mps=closing_speed_mps,
        )

    @property
    def time_to_impact_s(self) -> float:
        """
        :return: The time before the missile reaches its target at the current
            closing speed, infinite if it is not closing in
        """
        if self.closing_speed_mps <= 0.0:
            return np.inf
        return self.distance_m / self.closing_speed_mps


def nearest_incoming(pawn: Pawn) -> IncomingMissile | None:
    """
    :param pawn: The actor to check
    :return: The nearest missile homing on the actor, None if there is none
    """
    incoming_missiles = getattr(pawn, "incoming_missiles", None)
    if not incoming_missiles:
        return None
    return min(incoming_missiles.values(), key=lambda missile: missile.distance_m)
