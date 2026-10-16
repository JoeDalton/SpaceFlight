from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from space_flight.actors.pawn import Pawn
from space_flight.ai import Personality
from space_flight.ai.generic.generic_ship_pilot import GenericShipPilot

if TYPE_CHECKING:
    from space_flight.game.flight_state import FlightState


class MajorShipPilot(GenericShipPilot):
    """
    A class to hold the autopilot of capital ships
    """

    def __init__(
        self,
        game: FlightState,
        pawn: Pawn,
        personality: dict = Personality.ESCORT_SHIP_DEFAULT,
    ):
        super().__init__(game=game, pawn=pawn, personality=personality)

    def compute_angular_error(
        self,
        target_direction: np.ndarray = np.zeros(3),
        up_reference: np.ndarray | None = None,
    ) -> tuple[float, float, float, float]:
        """
        Computes the angular error of the ship. Adapted to capital ships

        :param target_direction: Direction of the target
        :param up_reference: World "up" to roll +Z toward; defaults to scene up
        :return: the yaw, pitch and roll error, and the alignment error
        """

        projection = self._project_target(target_direction)
        if projection is None:
            return 0.0, 0.0, 0.0, 1.0
        yaw_error, pitch_error, _, _, cos_angle_to_target = projection
        # Capital ships only roll to level with the reference up (scene up by
        # default).
        level_reference = (
            self.game.scene.up_direction if up_reference is None else up_reference
        )
        roll_error = self._level_roll_error(level_reference)

        return yaw_error, pitch_error, roll_error, cos_angle_to_target
