import logging

import numpy as np
from simple_pid import PID

from space_flight import DEBUG_DELETION
from space_flight.ai import REFERENCE_ERROR_VELOCITY_MPS, Personality
from space_flight.utils import low_pass_filter_first_order, safe_angle_rad

LOGGER = logging.getLogger()

ROLL_TOLERANCE = 1e-2
DISTANCE_FOR_MAX_THROTTLE = 2000


class AutoPilot:
    def __init__(self, game, ship, personality: dict = Personality.DEFAULT):
        self.game = game
        self.ship = ship
        self.personality = personality
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
        self.filter_time = self.personality["pilot"]["low_pass_filter_time_s"]
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
        self.pid_roll.set_auto_mode(
            True, last_output=current_normalized_roll_rate_command
        )

    def set_off(self):
        """
        Sets the Auto pilot off
        """
        self.pid_yaw.set_auto_mode(False)
        self.pid_pitch.set_auto_mode(False)
        self.pid_roll.set_auto_mode(False)

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

        TODO : Add pilot skill modifiers ? Randomness ?
        """
        dt = self.game.game_time.get_time_step()

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
            ship_x = self.ship.right
            ship_y = self.ship.forward
            ship_z = self.ship.up
            # Project target direction on ship axes
            target_x = np.dot(ship_x, target_direction)
            target_y = np.dot(ship_y, target_direction)
            target_z = np.dot(ship_z, target_direction)
            # Find angle errors
            yaw_error = np.arctan2(target_x, target_y)
            pitch_error = np.arctan2(target_z, target_y)
            roll_error = np.arctan2(target_x, target_z)
            # Clip roll error to zero if pitch and roll errors are small enough
            if (yaw_error**2 + pitch_error**2) < ROLL_TOLERANCE:
                roll_error = 0.0

            cos_angle_to_target = np.dot(ship_y, target_direction)
            self.angle_to_target_deg = np.rad2deg(np.arccos(cos_angle_to_target))

        # Find velocity error
        velocity_error = (
            np.linalg.norm(self.ship.speed) - desired_speed_mps
        ) / REFERENCE_ERROR_VELOCITY_MPS

        # Update PID commands
        throttle_command = self.pid_throttle(velocity_error)
        yaw_rate_command = self.pid_yaw(yaw_error)
        pitch_rate_command = self.pid_pitch(pitch_error)
        roll_rate_command = self.pid_roll(roll_error)

        # Low-pass filter on command to find "realistic" turn rates
        [
            self.throttle,
            self.yaw_rate,
            self.pitch_rate,
            self.roll_rate,
        ] = low_pass_filter_first_order(
            value=np.array(
                [
                    throttle_command,
                    yaw_rate_command,
                    pitch_rate_command,
                    roll_rate_command,
                ]
            ),
            previous=np.array(
                [self.throttle, self.yaw_rate, self.pitch_rate, self.roll_rate]
            ),
            dt=dt,
            rise_time=self.filter_time,
            fall_time=self.filter_time,
        )

        # Clamp throttle
        self.throttle = max(
            min(self.throttle, 1.0), self.personality["pilot"]["minimum_throttle"]
        )

        # DEBUG
        # self.throttle, self.yaw_rate, self.pitch_rate, self.roll_rate = 0, 0, 0, 0

        return self.throttle, self.yaw_rate, self.pitch_rate, self.roll_rate

    def clean(self):
        self.ship = None
        self.game = None
        if DEBUG_DELETION:
            LOGGER.info("Cleaned autopilot")

    def __del__(self):
        if DEBUG_DELETION:
            LOGGER.info("Deleted autopilot")
