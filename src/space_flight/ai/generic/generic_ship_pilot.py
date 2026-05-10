import numpy as np
from simple_pid import PID

from space_flight.actors.pawn import Pawn
from space_flight.ai import REFERENCE_ERROR_VELOCITY_MPS
from space_flight.ai.generic.generic_pilot import GenericPilot
from space_flight.utils import safe_angle_rad


class GenericShipPilot(GenericPilot):
    """
    A generic class for ship autopilots
    """

    def __init__(self, game, pawn: Pawn, personality: dict):
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
            output_limits=(0.0, 1.0),
        )
        self.yaw_rate = 0.0
        self.pitch_rate = 0.0
        self.roll_rate = 0.0
        self.throttle = 0.0
        self.angle_to_target_deg = 0.0

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
    ):
        """
        Given a target direction and the current orientation of the ship, compute the
        yaw, pitch and roll rates that will be applied to the trajectory.
        Given a desired ship speed, compute the necessary throttle.

        TODO : take into account the speed vector instead of ship axes to account for
        nicer flight dynamics (sideslip, AoA) ?

        TODO : Add pilot skill randomness ?
        """

        (
            yaw_error,
            pitch_error,
            roll_error,
            cos_angle_to_target,
        ) = self.compute_angular_error(target_direction=target_direction)
        self.angle_to_target_deg = np.rad2deg(np.arccos(cos_angle_to_target))

        # Find velocity error
        velocity_error = (
            np.linalg.norm(self.pawn.speed) - desired_speed_mps
        ) / REFERENCE_ERROR_VELOCITY_MPS

        # Update PID commands
        self.throttle = self.pid_throttle(velocity_error)
        self.yaw_rate = self.pid_yaw(yaw_error)
        self.pitch_rate = self.pid_pitch(pitch_error)
        self.roll_rate = self.pid_roll(roll_error)

        # Clamp throttle
        self.throttle = max(
            min(self.throttle, 1.0), self.personality["pilot"]["minimum_throttle"]
        )

        # DEBUG
        # self.throttle, self.yaw_rate, self.pitch_rate, self.roll_rate = 0, 0, 0, 0

        return self.throttle, self.yaw_rate, self.pitch_rate, self.roll_rate

    def compute_angular_error(self, target_direction: np.ndarray) -> tuple[float]:
        """
        Computes the angular error of the ship. Depends on the ship type.

        :param target_direction: Direction of the target
        :return: the yaw, pitch and roll error, and the alignment error
        """
        raise NotImplementedError
