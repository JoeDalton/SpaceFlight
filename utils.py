import quaternion
import numpy as np

def rotate_single_vector(quat: np.quaternion, vector: np.ndarray):
    """
    Rotates vector by the rotation defined by quat
    """
    # TODO quaternion multiplication for faster computation
    return quaternion.rotate_vectors(quat, vector)

def safe_angle_rad(angle_rad: float) -> float:
    """
    Transfers an angle in the [-pi, pi[ quadrant

    :param angle_rad: An angle in radians
    :return: The same angle in [-pi, pi[
    """
    if angle_rad > 0:
        if angle_rad >= np.pi:
            return safe_angle_rad(angle_rad - 2*np.pi)
    else:
        if angle_rad < -np.pi:
            return safe_angle_rad(angle_rad + 2*np.pi)
    return angle_rad

def low_pass_filter_first_order(
        value: float,           # current raw input: 1.0 if pressed, 0.0 if not
        previous: float,        # previous smoothed output
        dt: float,              # Time since last call
        rise_time: float,   # seconds to reach ~63% when pressed
        fall_time:float,   # seconds to decay when released
    ):
        """
        First order low pass filter with a possibility for distinct fall and rise
        characteristic times 
        """

        # Choose response speed depending on press/release
        tau = rise_time if value > previous else fall_time

        if tau <= 0.0 or dt == 0.0:
            return value

        alpha = dt / (tau + dt)
        return previous + (value - previous) * alpha