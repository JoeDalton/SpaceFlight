import numpy as np
from simple_pid import PID

from space_flight.actors.pawn import Pawn
from space_flight.ai import HALF_PI, Personality
from space_flight.ai.generic.generic_pilot import GenericPilot
from space_flight.utils import safe_angle_rad


class TurretPilot(GenericPilot):
    """
    A class to hold the autopilot of turrets
    """

    def __init__(
        self, game, pawn: Pawn, personality: dict = Personality.TURRET_DEFAULT
    ):
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
        self.yaw_rate = 0.0
        self.pitch_rate = 0.0
        self.angle_to_target_deg = 0.0

    def set_on(
        self,
        current_normalized_yaw_rate_command: float = 0.0,
        current_normalized_pitch_rate_command: float = 0.0,
    ):
        """
        Sets the Auto pilot on
        """
        self.pid_yaw.set_auto_mode(
            True, last_output=current_normalized_yaw_rate_command
        )
        self.pid_pitch.set_auto_mode(
            True, last_output=current_normalized_pitch_rate_command
        )

    def set_off(self):
        """
        Sets the Auto pilot off
        """
        self.pid_yaw.set_auto_mode(False)
        self.pid_pitch.set_auto_mode(False)

    def pilot(
        self,
        target_direction: np.ndarray = np.zeros(3),
    ):
        """
        Given a target direction and the current orientation of the ship, compute the
        yaw and pitch rates that will be applied to the turret.

        TODO : Add turret randomness ?
        """

        # Compute angular errors
        target_direction_norm = np.linalg.norm(target_direction)
        if target_direction_norm == 0.0:
            yaw_error_rad = 0.0
            pitch_error_rad = 0.0
            cos_angle_to_target = 1.0
        else:
            target_direction = target_direction / target_direction_norm
            # Project target direction on turret base axes
            base_x = self.pawn.base_right
            base_y = self.pawn.base_forward
            base_z = self.pawn.base_up
            target_x = np.dot(base_x, target_direction)
            target_y = np.dot(base_y, target_direction)
            target_z = np.dot(base_z, target_direction)
            cannon_x = np.dot(base_x, self.pawn.forward)
            cannon_y = np.dot(base_y, self.pawn.forward)
            cannon_z = np.dot(base_z, self.pawn.forward)
            # Compute angular errors
            # Yaw
            yaw_target_rad = HALF_PI - np.arctan2(target_y, target_x)
            yaw_cannon_rad = HALF_PI - np.arctan2(cannon_y, cannon_x)
            yaw_error_rad = yaw_target_rad - yaw_cannon_rad
            # Pitch
            pitch_target_rad = np.arcsin(target_z)
            pitch_cannon_rad = np.arcsin(cannon_z)
            pitch_error_rad = pitch_target_rad - pitch_cannon_rad

            cos_angle_to_target = np.dot(self.pawn.forward, target_direction)
            self.angle_to_target_deg = np.rad2deg(np.arccos(cos_angle_to_target))

        # Update PID commands
        self.yaw_rate = self.pid_yaw(yaw_error_rad)
        self.pitch_rate = self.pid_pitch(pitch_error_rad)

        return self.yaw_rate, self.pitch_rate
