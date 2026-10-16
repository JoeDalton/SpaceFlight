from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np

from space_flight.actors.pawn import Pawn
from space_flight.actors.ship import ZERO_THRUST_POSITION
from space_flight.ai import HALF_PI, REFERENCE_ERROR_VELOCITY_MPS
from space_flight.ai.generic.generic_pilot import GenericPilot
from space_flight.utils import clamp, magnitude

if TYPE_CHECKING:
    from space_flight.game.flight_state import FlightState


class GenericShipPilot(GenericPilot):
    """
    A generic class for ship autopilots
    """

    def __init__(self, game: FlightState, pawn: Pawn, personality: dict):
        super().__init__(game=game, pawn=pawn, personality=personality)

        self.pid_yaw = self._make_pid("yaw")
        self.pid_pitch = self._make_pid("pitch")
        self.pid_roll = self._make_pid("roll")
        # Signed: it only corrects the feedforward throttle, so it may also pull
        # the throttle down
        self.pid_throttle = self._make_pid("throttle", angular=False)
        self.yaw_rate = 0.0
        self.pitch_rate = 0.0
        self.roll_rate = 0.0
        self.throttle = 0.0
        self.angle_to_target_deg = 0.0
        # Fraction of the yaw/pitch rate commands kept by energy protection
        self.turn_authority = 1.0

    def set_on(
        self,
        current_normalized_yaw_rate_command: float = 0.0,
        current_normalized_pitch_rate_command: float = 0.0,
        current_normalized_roll_rate_command: float = 0.0,
        current_throttle_command: float = 0.0,
    ):
        """
        Sets the Auto pilot on
        """
        self.pid_yaw.set_auto_mode(
            enabled=True, last_output=current_normalized_yaw_rate_command
        )
        self.pid_pitch.set_auto_mode(
            enabled=True, last_output=current_normalized_pitch_rate_command
        )
        self.pid_roll.set_auto_mode(
            enabled=True, last_output=current_normalized_roll_rate_command
        )
        self.pid_throttle.set_auto_mode(
            enabled=True, last_output=current_throttle_command
        )

    def set_off(self):
        """
        Sets the Auto pilot off
        """
        self.pid_yaw.set_auto_mode(enabled=False)
        self.pid_pitch.set_auto_mode(enabled=False)
        self.pid_roll.set_auto_mode(enabled=False)
        self.pid_throttle.set_auto_mode(enabled=False)

    def pilot(
        self,
        target_direction: np.ndarray = np.zeros(3),
        desired_speed_mps: float = 0.0,
        up_reference: np.ndarray | None = None,
        minimum_speed_mps: float = 0.0,
    ) -> tuple[float, float, float, float]:
        """
        Compute the yaw, pitch and roll rates that turn the ship toward
        target_direction, and the throttle that reaches desired_speed_mps.
        Below minimum_speed_mps, the yaw and pitch rates are eased off (see
        compute_turn_authority): a hard turn bleeds more speed than full thrust
        can make up.

        TODO : take into account the speed vector instead of ship axes to account for
        nicer flight dynamics (sideslip, AoA) ?

        TODO : Add pilot skill randomness ?

        :param target_direction: The direction to point to (world frame)
        :param desired_speed_mps: The speed to reach
        :param up_reference: Optional world "up" the ship should roll its +Z toward
            (belly-aiming for a bomb run). None means level to scene up.
        :param minimum_speed_mps: The speed floor to protect (0 for none)
        :return: The throttle, yaw, pitch and roll rate commands
        """

        (
            yaw_error,
            pitch_error,
            roll_error,
            cos_angle_to_target,
        ) = self.compute_angular_error(
            target_direction=target_direction, up_reference=up_reference
        )
        self.angle_to_target_deg = math.degrees(
            math.acos(clamp(cos_angle_to_target, -1.0, 1.0))
        )

        # Find velocity error
        velocity_error = (
            magnitude(self.pawn.speed) - desired_speed_mps
        ) / REFERENCE_ERROR_VELOCITY_MPS

        # Update PID commands
        self.throttle = self.compute_feedforward_throttle(
            desired_speed_mps
        ) + self.pid_throttle(velocity_error)
        self.turn_authority = self.compute_turn_authority(minimum_speed_mps)
        self.yaw_rate = self.turn_authority * self.pid_yaw(yaw_error)
        self.pitch_rate = self.turn_authority * self.pid_pitch(pitch_error)
        self.roll_rate = self.pid_roll(roll_error)

        # Clamp throttle
        self.throttle = max(
            min(self.throttle, 1.0), self.personality["pilot"]["minimum_throttle"]
        )

        # DEBUG
        # self.throttle, self.yaw_rate, self.pitch_rate, self.roll_rate = 0, 0, 0, 0

        return self.throttle, self.yaw_rate, self.pitch_rate, self.roll_rate

    def compute_turn_authority(self, minimum_speed_mps: float) -> float:
        """
        Energy protection: the fraction of the yaw/pitch rate commands to keep.
        Full at or above minimum_speed_mps, ramping down linearly to the
        personality's min_turn_authority at energy_protection_range_factor *
        max_speed_mps below it. Roll is never limited, so the ship can still
        bank into its turn.

        :param minimum_speed_mps: The speed floor to protect (0 for none)
        :return: The turn authority, in [min_turn_authority, 1]
        """
        if minimum_speed_mps <= 0.0:
            return 1.0
        min_turn_authority = self.personality["pilot"].get("min_turn_authority", 1.0)
        range_mps = (
            self.personality["pilot"].get("energy_protection_range_factor", 0.0)
            * self.pawn.max_speed_mps
        )
        if range_mps <= 0.0:
            return 1.0
        speed_deficit_mps = minimum_speed_mps - magnitude(self.pawn.speed)
        ramp = clamp(speed_deficit_mps / range_mps, 0.0, 1.0)
        return 1.0 - ramp * (1.0 - min_turn_authority)

    def compute_feedforward_throttle(self, desired_speed_mps: float) -> float:
        """
        Estimates the throttle that holds desired_speed_mps: the thrust balancing
        the drag at that speed plus the current lift-induced drag (high in hard
        turns), through the inverse of Ship.set_inputs' quadratic throttle law.

        :param desired_speed_mps: The speed to hold
        :return: The feedforward throttle, in [ZERO_THRUST_POSITION, 1]
        """
        available_thrust_n = self.pawn.max_thrust_n * self.pawn.thrust_factor()
        if available_thrust_n <= 0.0:
            # Engine-less body (e.g. an ordnance, which has no flight forces)
            return 1.0
        lift_norm_n = magnitude(self.pawn.lift_n)
        required_thrust_n = (
            self.pawn.drag_factor * desired_speed_mps**2
            + self.pawn.lift_inefficiency * lift_norm_n**2
        )
        thrust_fraction = clamp(required_thrust_n / available_thrust_n, 0.0, 1.0)
        return ZERO_THRUST_POSITION + (1.0 - ZERO_THRUST_POSITION) * math.sqrt(
            thrust_fraction
        )

    def _project_target(
        self, target_direction: np.ndarray
    ) -> tuple[float, float, float, float, float] | None:
        """
        Project a target direction on the ship's axes.

        :param target_direction: Direction of the target
        :return: None for a null direction, else the yaw and pitch errors to the
            target, its components along the ship's right and up axes, and the
            cosine of the angle to it (its component along the nose)
        """
        target_direction_norm = magnitude(target_direction)
        if target_direction_norm == 0.0:
            return None
        # TODO remove normalization since the autonavigator is supposed to give
        # either a null or a unit direction
        target_direction = target_direction / target_direction_norm
        target_x = np.dot(self.pawn.right, target_direction)
        target_y = np.dot(self.pawn.forward, target_direction)
        target_z = np.dot(self.pawn.up, target_direction)
        yaw_error = np.arctan2(target_x, target_y)
        pitch_error = np.arctan2(target_z, target_y)
        return yaw_error, pitch_error, target_x, target_z, target_y

    def _level_roll_error(self, level_reference: np.ndarray) -> float:
        """
        :param level_reference: The world "up" to level the ship's +Z toward
        :return: The roll error to level the ship with it
        """
        # Clamp before arccos: float error can push the dot of two unit vectors
        # past ±1, and a NaN would poison the whole state.
        right_dot_ref = np.dot(self.pawn.right, level_reference)
        right_dot_ref = clamp(right_dot_ref, -1.0, 1.0)
        if np.dot(self.pawn.up, level_reference) >= 0:
            return HALF_PI - np.arccos(right_dot_ref)
        return HALF_PI + np.arccos(right_dot_ref)

    def compute_angular_error(
        self, target_direction: np.ndarray, up_reference: np.ndarray | None = None
    ) -> tuple[float, float, float, float]:
        """
        Computes the angular error of the ship. Depends on the ship type.

        :param target_direction: Direction of the target
        :param up_reference: Optional world "up" to roll +Z toward (default level)
        :return: the yaw, pitch and roll error, and the alignment error
        """
        raise NotImplementedError
