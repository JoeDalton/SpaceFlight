from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np
from simple_pid import PID

from space_flight.actors.pawn import Pawn
from space_flight.actors.ship import ZERO_THRUST_POSITION
from space_flight.ai import REFERENCE_ERROR_VELOCITY_MPS
from space_flight.ai.generic.generic_pilot import GenericPilot
from space_flight.utils import magnitude, safe_angle_rad

if TYPE_CHECKING:
    from space_flight.game.flight_state import FlightState


class GenericShipPilot(GenericPilot):
    """
    A generic class for ship autopilots
    """

    def __init__(self, game: FlightState, pawn: Pawn, personality: dict):
        super().__init__(game=game, pawn=pawn, personality=personality)

        self.pid_yaw = PID(
            Kp=self.personality["pilot"]["yaw_kp"],
            Ki=self.personality["pilot"]["yaw_ki"],
            Kd=self.personality["pilot"]["yaw_kd"],
            setpoint=0.0,
            starting_output=0.0,
            sample_time=self.personality["pilot"]["sample_time_s"],
            error_map=safe_angle_rad,
            time_fn=self.game.game_time.get_current_time,
            output_limits=(-1.0, 1.0),
        )
        self.pid_pitch = PID(
            Kp=self.personality["pilot"]["pitch_kp"],
            Ki=self.personality["pilot"]["pitch_ki"],
            Kd=self.personality["pilot"]["pitch_kd"],
            setpoint=0.0,
            starting_output=0.0,
            sample_time=self.personality["pilot"]["sample_time_s"],
            error_map=safe_angle_rad,
            time_fn=self.game.game_time.get_current_time,
            output_limits=(-1.0, 1.0),
        )
        self.pid_roll = PID(
            Kp=self.personality["pilot"]["roll_kp"],
            Ki=self.personality["pilot"]["roll_ki"],
            Kd=self.personality["pilot"]["roll_kd"],
            setpoint=0.0,
            starting_output=0.0,
            sample_time=self.personality["pilot"]["sample_time_s"],
            error_map=safe_angle_rad,
            time_fn=self.game.game_time.get_current_time,
            output_limits=(-1.0, 1.0),
        )
        self.pid_throttle = PID(
            Kp=self.personality["pilot"]["throttle_kp"],
            Ki=self.personality["pilot"]["throttle_ki"],
            Kd=self.personality["pilot"]["throttle_kd"],
            setpoint=0.0,
            starting_output=0.0,
            sample_time=self.personality["pilot"]["sample_time_s"],
            time_fn=self.game.game_time.get_current_time,
            # Signed: it only corrects the feedforward throttle, so it may also
            # pull the throttle down
            output_limits=(-1.0, 1.0),
        )
        self.yaw_rate = 0.0
        self.pitch_rate = 0.0
        self.roll_rate = 0.0
        self.throttle = 0.0
        self.angle_to_target_deg = 0.0
        # Fraction of the yaw/pitch rate commands kept by energy protection
        self.turn_authority = 1.0

    def sample_externally(self):
        for pid in (self.pid_yaw, self.pid_pitch, self.pid_roll, self.pid_throttle):
            pid.sample_time = None

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
            math.acos(min(max(cos_angle_to_target, -1.0), 1.0))
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
        ramp = min(max(speed_deficit_mps / range_mps, 0.0), 1.0)
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
        thrust_fraction = min(max(required_thrust_n / available_thrust_n, 0.0), 1.0)
        return ZERO_THRUST_POSITION + (1.0 - ZERO_THRUST_POSITION) * math.sqrt(
            thrust_fraction
        )

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
