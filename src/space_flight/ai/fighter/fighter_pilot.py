from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from space_flight.actors.pawn import Pawn
from space_flight.ai import ROLL_TOLERANCE, Personality
from space_flight.ai.generic.generic_ship_pilot import GenericShipPilot

if TYPE_CHECKING:
    from space_flight.game.flight_state import FlightState

SCENE_ROLL_MULTIPLIER = 0.5


class FighterPilot(GenericShipPilot):
    """
    A class to hold the autopilot of fighters
    """

    def __init__(
        self,
        game: FlightState,
        pawn: Pawn,
        personality: dict = Personality.FIGHTER_DEFAULT,
    ):
        super().__init__(game=game, pawn=pawn, personality=personality)

    def compute_angular_error(
        self,
        target_direction: np.ndarray = np.zeros(3),
        up_reference: np.ndarray | None = None,
    ) -> tuple[float, float, float, float]:
        """
        Computes the angular error of the ship. Adapted to fighter ships

        :param target_direction: Direction of the target
        :param up_reference: World "up" to roll +Z toward. When None (normal flight)
            the fighter banks into turns and slowly levels to scene up; when given
            (a bomb run's belly-aim) banking is suppressed and it rolls fully to the
            reference so the belly (-Z) faces the target.
        :return: the yaw, pitch and roll error, and the alignment error
        """

        projection = self._project_target(target_direction)
        if projection is None:
            return 0.0, 0.0, 0.0, 1.0
        yaw_error, pitch_error, target_x, target_z, cos_angle_to_target = projection

        # The vector to level +Z toward: the caller's up-reference (bomb belly
        # aim) or, by default, scene up.
        if up_reference is None:
            level_reference = self.game.scene.up_direction
            # Normal flight: bank into the turn, then add a light scene-leveling.
            roll_error = np.arctan2(target_x, target_z)
            if (yaw_error**2 + pitch_error**2) < ROLL_TOLERANCE:
                roll_error = 0.0
            level_weight = SCENE_ROLL_MULTIPLIER
        else:
            level_reference = up_reference
            # Commanded attitude (bomb run): no banking, roll fully to level.
            roll_error = 0.0
            level_weight = 1.0
        roll_error += level_weight * self._level_roll_error(level_reference)

        return yaw_error, pitch_error, roll_error, cos_angle_to_target
