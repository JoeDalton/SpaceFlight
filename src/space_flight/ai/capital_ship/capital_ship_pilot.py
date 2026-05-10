import numpy as np

from space_flight.actors.pawn import Pawn
from space_flight.ai import HALF_PI, Personality
from space_flight.ai.generic.generic_ship_pilot import GenericShipPilot


class CapitalShipPilot(GenericShipPilot):
    """
    A class to hold the autopilot of capital ships
    """

    def __init__(
        self, game, pawn: Pawn, personality: dict = Personality.CAPITAL_SHIP_DEFAULT
    ):
        super().__init__(game=game, pawn=pawn, personality=personality)

    def compute_angular_error(
        self,
        target_direction: np.ndarray = np.zeros(3),
    ):
        """
        Computes the angular error of the ship. Adapted to capital ships

        :param target_direction: Direction of the target
        :return: the yaw, pitch and roll error, and the alignment error
        """

        # Compute directions
        target_direction_norm = np.linalg.norm(target_direction)
        if target_direction_norm == 0.0:
            yaw_error = 0.0
            pitch_error = 0.0
            roll_error = 0.0
            cos_angle_to_target = 1.0
        else:
            # Find ship axes
            # TODO remove normalization since the autonavigator is supposed to give
            # either a null or a unit direction
            target_direction = target_direction / target_direction_norm
            ship_x = self.pawn.right
            ship_y = self.pawn.forward
            ship_z = self.pawn.up
            # Project target direction on ship axes
            target_x = np.dot(ship_x, target_direction)
            target_y = np.dot(ship_y, target_direction)
            target_z = np.dot(ship_z, target_direction)
            # Find angle errors
            yaw_error = np.arctan2(target_x, target_y)
            pitch_error = np.arctan2(target_z, target_y)
            # Capital ships only roll for the scene orientation
            is_up = np.dot(self.pawn.up, self.game.scene.up_direction) >= 0
            if is_up:
                roll_error = HALF_PI - np.arccos(
                    np.dot(self.pawn.right, self.game.scene.up_direction)
                )
            else:
                roll_error = HALF_PI + np.arccos(
                    np.dot(self.pawn.right, self.game.scene.up_direction)
                )
            # Debug output
            cos_angle_to_target = np.dot(ship_y, target_direction)

        return yaw_error, pitch_error, roll_error, cos_angle_to_target
