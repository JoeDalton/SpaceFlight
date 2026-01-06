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

ROLL_TOLERANCE = 1e-2

# TODO: Navigator parameters ?
DISTANCE_TOLERANCE_M = 1
EVADE_TIME_S = 1.0
LEAD_TIME_S = 1.0


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

    def __call__(
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

        # Update throttle
        throttle_command = max(min(self.throttle + dt * self.throttle_rate, 1.0), 0.0)

        # Compute directions
        target_direction_norm = np.linalg.norm(target_direction)
        if target_direction_norm == 0.0:
            yaw_error = 0.0
            pitch_error = 0.0
            roll_error = 0.0
            self.angle_to_target_deg = 0.0
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

            angle_to_target_rad = np.arccos(np.dot(ship_y, target_direction))
            self.angle_to_target_deg = np.rad2deg(angle_to_target_rad)

        # Update throttle command
        self.throttle_rate = AutoPilot.simple_throttle_controller(
            angle_to_target_deg=self.angle_to_target_deg,
            reference_distance_m=reference_distance_m,
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

        return self.throttle, self.yaw_rate, self.pitch_rate, self.roll_rate

    @staticmethod
    def simple_throttle_controller(
        angle_to_target_deg: float, reference_distance_m: float
    ) -> float:
        """
        I want the reference distance to go to zero and the angle to target to go to
        zero.
        First, decrease throttle for too high angles, especially if it's been too long
        => PI controller
        Second, we want a reference distance to go to zero
        =>
         - Increase if getting away while in the right direction, diminish otherwise
         - The opposite if getting closer => P(I)D controller with a twist ?

        TODO: Use 2nd order polynomials instead of if conditions

        TODO: Not sure this is a good controller. Especially with reference distances
        that are difficult to determine for boids

        :param angle_to_target_deg: _description_
        :param reference_distance_float_deg: _description_
        :return: _description_
        """
        throttle_rate = 0.0
        throttle_factor = 0.05
        # Decrease throttle if the target is at too much of an angle
        if angle_to_target_deg > 30:
            throttle_rate -= throttle_factor
        elif angle_to_target_deg > 60:
            throttle_rate -= 2 * throttle_factor
        elif angle_to_target_deg > 90:
            throttle_rate -= 3 * throttle_factor
        elif angle_to_target_deg > 120:
            throttle_rate -= 4 * throttle_factor
        # Increase throttle if the target is too far
        if reference_distance_m > 10:
            throttle_rate += 0.5 * throttle_factor
        elif reference_distance_m > 100:
            throttle_rate += 1.5 * throttle_factor
        elif reference_distance_m > 200:
            throttle_rate += 5 * throttle_factor
        elif reference_distance_m > 400:
            throttle_rate += 10 * throttle_factor

        return throttle_rate

    def clean(self):
        self.ship = None
        if DEBUG_DELETION:
            LOGGER.info("Cleaned autopilot")

    def __del__(self):
        if DEBUG_DELETION:
            LOGGER.info("Deleted autopilot")


class AutoNavigator:
    """
    TODO
    Determines the direction vector that the AutoPilot should aim for by computing the
    behaviour forces and using the weights from the AutoTactician
    """

    def __init__(self, ship):
        self.ship = ship

    def chase_target(self, target):
        """
        Chases a target by pointing towards the position it will hold LEAD_TIME_S later
        should its speed remain constant.
        The reference distance is the distance to the target itself.

        :param target: A target object with a position attribute and an optional
                speed attribute
        """
        # Find the future position of the target
        target_current_position = target.position
        try:
            target_current_speed = target.speed
        except AttributeError:
            target_current_speed = np.zeros(3)
        target_future_position = (
            target_current_position + target_current_speed * LEAD_TIME_S
        )
        # Compute direction to point to
        target_future_direction = target_future_position - self.ship.position
        target_future_distance_m = np.linalg.norm(target_future_direction)
        if target_future_distance_m < DISTANCE_TOLERANCE_M:
            target_future_direction = np.zeros(3)
        else:
            target_future_direction /= target_future_distance_m
        # Find reference distance
        reference_distance_m = np.linalg.norm(
            target_current_position - self.ship.position
        )
        return target_future_position, reference_distance_m

    def evade_target(self, target):
        """
        Passes behind a target by pointing towards the position it would have
        held one second earlier were its speed constant.

        If its speed is zero, do nothing.

        :param target: A target object with a position attribute and an optional
                speed attribute
        """
        # Find the past position of the target
        target_current_position = target.position
        try:
            target_current_speed = target.speed
        except AttributeError:
            # Immobile target, nothing to evade from
            return np.zeros(3), 0.0
        target_past_position = (
            target_current_position - target_current_speed * EVADE_TIME_S
        )
        # Compute direction to point to
        target_past_direction = target_past_position - self.ship.position
        target_past_distance_m = np.linalg.norm(target_past_direction)
        if target_past_distance_m < DISTANCE_TOLERANCE_M:
            target_past_direction = np.zeros(3)
        else:
            target_past_direction /= target_past_distance_m
        # Find reference distance
        reference_distance_m = np.linalg.norm(
            target_current_position - self.ship.position
        )
        return target_past_position, reference_distance_m

    def flee_target(self, target):
        """
        Get as far away from the target as possible.
        TODO: use boost if possible ?
        
        :param target: A target object with a position attribute
        """
        # Find the target's direction
        target_current_position = target.position

        target_current_direction = target_current_position - self.ship.position
        target_current_distance_m = np.linalg.norm(target_current_direction)
        if target_current_distance_m < DISTANCE_TOLERANCE_M:
            target_current_direction = np.zeros(3)
        else:
            target_current_direction /= target_current_distance_m
        # Find fleeing direction
        fleeing_direction = -target_current_direction
        # Find reference distance
        reference_distance_m = 1e4

        return fleeing_direction, reference_distance_m

    def clean(self):
        self.ship = None
        if DEBUG_DELETION:
            LOGGER.info("Cleaned autonavigator")

    def __del__(self):
        if DEBUG_DELETION:
            LOGGER.info("Deleted autonavigator")


class AutoTactician:
    """
    TODO
    Finds the proper strategy for a bot:
    - Select the most valuable target (enemy to kill, friend to escort,
        patrol to do, should be scriptable ?)
    - Weigh the behaviour forces
    - The weights could depend on an aggressive/defensive/cowardly personnality
    - They may depend on the situation and/or a scenario
    """

    def __init__(self, ship):
        self.ship = ship

    def clean(self):
        self.ship = None
        if DEBUG_DELETION:
            LOGGER.info("Cleaned autotactician")

    def __del__(self):
        if DEBUG_DELETION:
            LOGGER.info("Deleted autotactician")
