import numpy as np

from space_flight.actors.pawn import Pawn
from space_flight.ai import HALF_PI, ROLL_TOLERANCE, Personality
from space_flight.ai.generic.generic_ship_pilot import GenericShipPilot

SCENE_ROLL_MULTIPLIER = 0.5


class FighterPilot(GenericShipPilot):
    """
    A class to hold the autopilot of fighters
    """

    def __init__(
        self, game, pawn: Pawn, personality: dict = Personality.FIGHTER_DEFAULT
    ):
        super().__init__(game=game, pawn=pawn, personality=personality)

    def compute_angular_error(
        self,
        target_direction: np.ndarray = np.zeros(3),
        up_reference: np.ndarray = None,
    ) -> tuple[float]:
        """
        Computes the angular error of the ship. Adapted to fighter ships

        :param target_direction: Direction of the target
        :param up_reference: World "up" to roll +Z toward. When None (normal flight)
            the fighter banks into turns and slowly levels to scene up; when given
            (a bomb run's belly-aim) banking is suppressed and it rolls fully to the
            reference so the belly (-Z) faces the target.
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

            # Clamp the dot to [-1, 1] before arccos: right and the reference are
            # unit vectors so it is mathematically in range, but float error can
            # nudge it just past ±1, which would make arccos return NaN and poison
            # the whole state.
            right_dot_ref = np.clip(np.dot(self.pawn.right, level_reference), -1.0, 1.0)
            is_up = np.dot(self.pawn.up, level_reference) >= 0
            if is_up:
                level_roll_error = HALF_PI - np.arccos(right_dot_ref)
            else:
                level_roll_error = HALF_PI + np.arccos(right_dot_ref)
            roll_error += level_weight * level_roll_error
            # Debug output
            cos_angle_to_target = np.dot(ship_y, target_direction)

        return yaw_error, pitch_error, roll_error, cos_angle_to_target
