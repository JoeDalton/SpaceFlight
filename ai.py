import numpy as np
from simple_pid import PID
from direct.showbase.ShowBaseGlobal import globalClock
from utils import safe_angle_rad, rotate_single_vector, low_pass_filter_first_order

class AutoPilot():
    def __init__(self, ship):
        self.ship = ship
        self.pid_yaw = PID(Kp=1.0, Ki=0.0, Kd=0.0, setpoint=0.0, starting_output=0.0, sample_time=0.1, error_map=safe_angle_rad, time_fn=globalClock.getFrameTime, output_limits=(-1.0, 1.0))
        self.pid_pitch = PID(Kp=1.0, Ki=0.0, Kd=0.0, setpoint=0.0, starting_output=0.0, sample_time=0.1, error_map=safe_angle_rad, time_fn=globalClock.getFrameTime, output_limits=(-1.0, 1.0))
        self.pid_roll = PID(Kp=1.0, Ki=0.0, Kd=0.0, setpoint=0.0, starting_output=0.0, sample_time=0.1, error_map=safe_angle_rad, time_fn=globalClock.getFrameTime, output_limits=(-1.0, 1.0))
        self.filter_time = 0.5

        self.throttle = 0.5

        self.yaw_rate = 0.0
        self.pitch_rate = 0.0
        self.roll_rate = 0.0

    def set_on(self, current_normalized_yaw: float, current_normalized_pitch: float, current_normalized_roll: float):
        """
        Sets the Auto pilot on
        """
        self.pid_yaw.set_auto_mode(True, last_output=current_normalized_yaw)
        self.pid_pitch.set_auto_mode(True, last_output=current_normalized_pitch)
        self.pid_roll.set_auto_mode(True, last_output=current_normalized_roll)

    def set_on(self):
        """
        Sets the Auto pilot on
        """
        self.pid_yaw.set_auto_mode(False)
        self.pid_pitch.set_auto_mode(False)
        self.pid_roll.set_auto_mode(False)

    def pilot(self, target_direction: np.ndarray = np.zeros(3)):
        """
        Given a target direction and the current orientation of the ship, compute the
        yaw pitch and roll rates that will be applied to the trajectory

        TODO : take into account the speed vector instead to account for nicer flight
        dynamics (sideslip, AoA)

        TODO: handle throttle


        """
        target_direction_norm = np.linalg.norm(target_direction)
        if target_direction_norm == 0.0:
            yaw_error = 0.0
            pitch_error = 0.0
            roll_error = 0.0
        else:
            # Find ship axes
            target_direction = target_direction / target_direction_norm
            ship_quat = np.quaternion(*self.ship.orientation)
            ship_x = rotate_single_vector(
                ship_quat, np.array([1.0, 0.0, 0.0])
            )
            ship_y = rotate_single_vector(
                ship_quat, np.array([0.0, 1.0, 0.0])
            )
            ship_z = rotate_single_vector(
                ship_quat, np.array([0.0, 0.0, 1.0])
            )
            # Project target direction on ship axes
            target_x = np.dot(ship_x, target_direction)
            target_y = np.dot(ship_y, target_direction)
            target_z = np.dot(ship_z, target_direction)
            # Find angle errors
            yaw_error = np.arctan2(target_x, target_y)
            pitch_error = np.arctan2(target_z, target_y)
            roll_error = np.arctan2(target_x, target_z)
        # Update PID commands
        yaw_rate_command = self.pid_yaw(yaw_error)
        pitch_rate_command = self.pid_yaw(pitch_error)
        roll_rate_command = self.pid_yaw(roll_error)
        # Low-pass filter on command to find "realistic" turn rates
        dt = globalClock.getDt()
        self.yaw_rate = low_pass_filter_first_order(value=yaw_rate_command, previous=self.yaw_rate, dt=dt, rise_time=self.filter_time, fall_time=self.filter_time)
        self.pitch_rate = low_pass_filter_first_order(value=pitch_rate_command, previous=self.pitch_rate, dt=dt, rise_time=self.filter_time, fall_time=self.filter_time)
        self.roll_rate = low_pass_filter_first_order(value=roll_rate_command, previous=self.roll_rate, dt=dt, rise_time=self.filter_time, fall_time=self.filter_time)
        
        return self.throttle, self.yaw_rate, self.pitch_rate, self.roll_rate
    