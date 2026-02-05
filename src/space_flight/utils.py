from typing import Union

import numpy as np
import quaternion
from direct.showbase.ShowBaseGlobal import ClockObject


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
            return safe_angle_rad(angle_rad - 2 * np.pi)
    else:
        if angle_rad < -np.pi:
            return safe_angle_rad(angle_rad + 2 * np.pi)
    return angle_rad


def low_pass_filter_first_order(
    value: Union[float, np.ndarray],  # current raw input: 1.0 if pressed, 0.0 if not
    previous: Union[float, np.ndarray],  # previous smoothed output
    dt: float,  # Time since last call
    rise_time: float,  # seconds to reach ~63% when pressed
    fall_time: float,  # seconds to decay when released
) -> Union[float, np.ndarray]:
    """
    First order low pass filter with a possibility for distinct fall and rise
    characteristic times
    """
    if dt == 0.0:
        return value

    # Choose response speed depending on press/release
    if isinstance(value, float) and isinstance(previous, float):
        tau = rise_time if value > previous else fall_time
        if tau <= 0.0:
            return value
    elif isinstance(value, np.ndarray) and isinstance(previous, np.ndarray):
        tau = np.where((value > previous), rise_time, fall_time)
        if (tau <= 0).any():
            return value

    alpha = dt / (tau + dt)
    return previous + (value - previous) * alpha


def get_current_time() -> float:
    """
    Gets the time of the current frame

    TODO: Take pauses/start menu into account

    :return: The time stamp of the current frame
    """
    return ClockObject.getGlobalClock().getFrameTime()


def get_time_step() -> float:
    """
    Gets the time elapsed since the last frame

    TODO: Take pauses/start menu into account

    :return: The time step
    """
    return ClockObject.getGlobalClock().getDt()


def smooth_step_down(
    x: Union[float, np.ndarray], x_step: float, slope: float
) -> Union[float, np.ndarray]:
    """
    A smooth step down function of R => ]0,1[

    :param x: The values at which the function is evaluated
    :param x_step: The cutoff abscissa
    :param slope: The descending slope at the abscissa
    :return: f(x)
    """
    return 0.5 * (1.0 - np.tanh(0.5 * slope * (x - x_step)))
