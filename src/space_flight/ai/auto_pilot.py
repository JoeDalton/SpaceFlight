import logging

import numpy as np
from direct.showbase.ShowBaseGlobal import globalClock
from simple_pid import PID

from space_flight import DEBUG_DELETION
from space_flight.utils import (
    low_pass_filter_first_order,
    rotate_single_vector,
    safe_angle_rad,
)

LOGGER = logging.getLogger()

# TODO: Pilot parameters ?
ROLL_TOLERANCE = 1e-2
ANGLE_THROTTLE_EXPONENT = 0.5
DISTANCE_FOR_MAX_THROTTLE = 2000
MIN_THROTTLE = 0.0
DISTANCE_THROTTLE_EXPONENT = 1.1


class AutoPilot:
    def __init__(self, ship):
        self.ship = ship
        self.pid_yaw = PID(
            Kp=1.0,
            Ki=0.0,
            Kd=0.0,
            setpoint=0.0,
            starting_output=0.0,
            sample_time=0.1,
            error_map=safe_angle_rad,
            time_fn=globalClock.getFrameTime,
            output_limits=(-1.0, 1.0),
        )
        self.pid_pitch = PID(
            Kp=-1.0,
            Ki=0.0,
            Kd=0.0,
            setpoint=0.0,
            starting_output=0.0,
            sample_time=0.1,
            error_map=safe_angle_rad,
            time_fn=globalClock.getFrameTime,
            output_limits=(-1.0, 1.0),
        )
        self.pid_roll = PID(
            Kp=-1.0,
            Ki=0.0,
            Kd=0.0,
            setpoint=0.0,
            starting_output=0.0,
            sample_time=0.1,
            error_map=safe_angle_rad,
            time_fn=globalClock.getFrameTime,
            output_limits=(-1.0, 1.0),
        )
        self.filter_time = 0.5

        self.yaw_rate = 0.0
        self.pitch_rate = 0.0
        self.roll_rate = 0.0
        self.throttle = 0.0
        self.throttle_rate = 0.0

        self.angle_to_target_deg = 0.0

        # Debug
        self.target_x = 0.0
        self.target_y = 0.0
        self.target_z = 0.0
        self.yaw_error_deg = 0.0
        self.pitch_error_deg = 0.0
        self.roll_error_deg = 0.0
        self.yaw_rate_command = 0.0
        self.pitch_rate_command = 0.0
        self.roll_rate_command = 0.0
        self.throttle_command = 0.0

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
        reference_distance_m: float = 0.0,
    ):
        """
        Given a target direction and the current orientation of the ship, compute the
        yaw, pitch and roll rates that will be applied to the trajectory

        TODO : take into account the speed vector instead of ship axes to account for
        nicer flight dynamics (sideslip, AoA) ?

        TODO : Add pilot skill modifiers ?
        """
        dt = globalClock.getDt()

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
            ship_quat = np.quaternion(*self.ship.orientation)
            ship_x = rotate_single_vector(ship_quat, np.array([1.0, 0.0, 0.0]))
            ship_y = rotate_single_vector(ship_quat, np.array([0.0, 1.0, 0.0]))
            ship_z = rotate_single_vector(ship_quat, np.array([0.0, 0.0, 1.0]))
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

            # Debug output
            self.target_x = target_x
            self.target_y = target_y
            self.target_z = target_z
            self.yaw_error_deg = np.rad2deg(yaw_error)
            self.pitch_error_deg = np.rad2deg(pitch_error)
            self.roll_error_deg = np.rad2deg(roll_error)

            cos_angle_to_target = np.dot(ship_y, target_direction)
            self.angle_to_target_deg = np.rad2deg(np.arccos(cos_angle_to_target))

        # Update throttle command
        # Decrease throttle if the target is at too much of an angle
        angle_contribution = max(0.0, cos_angle_to_target) ** ANGLE_THROTTLE_EXPONENT
        # Increase throttle if the target is too far and lower it if negative distance
        distance_contribution = (
            max(
                min(reference_distance_m / DISTANCE_FOR_MAX_THROTTLE, 1.0), MIN_THROTTLE
            )
            ** DISTANCE_THROTTLE_EXPONENT
        )
        # TODO: add a contribution of closing velocity ?
        velocity_contribution = 1.0
        # Combine contributions
        throttle_command = (
            angle_contribution * distance_contribution * velocity_contribution
        )

        # Update PID commands for turn rates
        yaw_rate_command = self.pid_yaw(yaw_error)
        pitch_rate_command = self.pid_pitch(pitch_error)
        roll_rate_command = self.pid_roll(roll_error)

        # Debug
        self.yaw_rate_command = yaw_rate_command
        self.pitch_rate_command = pitch_rate_command
        self.roll_rate_command = roll_rate_command

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
        self.throttle = max(min(self.throttle, 1.0), MIN_THROTTLE)

        return self.throttle, self.yaw_rate, self.pitch_rate, self.roll_rate

    def clean(self):
        self.ship = None
        if DEBUG_DELETION:
            LOGGER.info("Cleaned autopilot")

    def __del__(self):
        if DEBUG_DELETION:
            LOGGER.info("Deleted autopilot")
