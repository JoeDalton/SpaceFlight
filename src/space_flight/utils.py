from typing import Union

import numpy as np
import quaternion


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


def smooth_step_down(
    x: Union[float, np.ndarray], x_step: float, slope: float
) -> Union[float, np.ndarray]:
    """
    A smooth step down function of R => ]0,1[

    :param x: The values at which the function is evaluated
    :param x_step: The cutoff abscissa
    :param slope: The descending slope at the abscissa (>0)
    :return: f(x)
    """
    return 0.5 * (1.0 - np.tanh(0.5 * slope * (x - x_step)))


def smooth_step_up(
    x: Union[float, np.ndarray], x_step: float, slope: float
) -> Union[float, np.ndarray]:
    """
    A smooth step up function of R => ]0,1[

    :param x: The values at which the function is evaluated
    :param x_step: The cutoff abscissa
    :param slope: The ascending slope at the abscissa (>0)
    :return: f(x)
    """
    return 1.0 - smooth_step_down(x=x, x_step=x_step, slope=slope)


def sample_unit_sphere() -> np.ndarray:
    """
    Returns a uniformly distributed random point inside the unit sphere.

    Uses rejection sampling: draw a point from the unit cube and discard it
    if it falls outside the sphere. The expected number of draws before
    acceptance is ``8 / (4π/3) ≈ 1.91``.

    :returns: A random vector in the unit sphere.
    """
    max_try = 50
    for _ in range(max_try):
        sample = np.random.uniform(low=-1, high=1, size=3)
        if np.linalg.norm(sample) <= 1.0:
            return sample
    # If no suitable sample is found, fall back to the origin (center of the sphere)
    return np.zeros(3)


def build_orthogonal_basis(
    normal: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Builds an orthonormal basis around *normal*.

    Returns three mutually perpendicular unit vectors ``(n, tangent, bitangent)``
    suitable for expressing arbitrary directions in the hemisphere defined by
    *normal*. Handles degenerate (near-zero) input by falling back to ``+Z``.

    :param normal: Preferred axis of the frame (need not be normalised).
    :returns: (normal, tangent, bitangent) — three orthonormal vectors
    """
    if normal is None:
        return None, None, None
    normal_norm = np.linalg.norm(normal)
    if normal_norm < 1e-6:
        normal = np.array([0, 0, 1])
        normal_norm = 1.0
    normal /= normal_norm
    # Pick a helper vector that is guaranteed not to be parallel to n,
    # then use cross products to build the tangent plane.
    helper = (
        np.array([1, 0, 0])
        if abs(np.dot(np.array([1, 0, 0]), normal)) < 0.9
        else np.array([0, 1, 0])
    )
    tangent = np.cross(normal, helper)
    tangent /= np.linalg.norm(tangent)
    bitangent = np.cross(normal, tangent)
    bitangent /= np.linalg.norm(bitangent)
    return normal, tangent, bitangent


def sample_direction_in_cone(
    normal: np.ndarray,
    tangent: np.ndarray,
    bitangent: np.ndarray,
    half_angle_rad: float,
) -> np.ndarray:
    """
    Returns a random unit vector within a cone around normal.

    The polar angle `theta` is sampled with a square-root bias so that
    directions are uniformly distributed over the cone's solid angle rather
    than clustering near the axis.

    :param normal: Cone axis (unit vector).
    :param tangent: Tangent vector perpendicular to normal.
    :param bitangent: Bitangent vector perpendicular to both normal and tangent.
    :param half_angle_rad: Half-angle of the cone in radians.
    :returns: A normalised random direction inside the cone.
    """
    if normal is None:
        return np.zeros(3)
    theta_rad = (
        np.random.uniform(low=0, high=1) ** 0.5 * half_angle_rad
    )  # sqrt → uniform solid angle
    phi_rad = 2 * np.pi * np.random.uniform(low=0, high=1)
    sine_theta = np.sin(theta_rad)
    sample = (
        normal * np.cos(theta_rad)
        + tangent * sine_theta * np.cos(phi_rad)
        + bitangent * sine_theta * np.sin(phi_rad)
    )
    sample /= np.linalg.norm(sample)  # TODO Not necessary
    return sample


def build_axis_billboard_quat(
    forward: np.ndarray, up_hint: np.ndarray = None
) -> quaternion:
    """
    Builds a quaternion that rotates the +Y axis onto `forward`.
    The up_hint is used to pin the `up` direction. It defaults to world Z+,
    with a fallback to world +X if `forward` is nearly vertical.

    #TODO test the crap out of this !

    :param forward: The axis of the billboard
    :param up_hint: The up hint vector, defaults to None
    :return: A quaternion object for axis billboards
    """
    # Make copies to avoid modifying the original vectors

    # Normalize forward vector
    forward_norm = np.linalg.norm(forward)
    if forward_norm < 1e-4:
        forward_axis = np.array([0, 1, 0])
    else:
        forward_axis = forward / forward_norm

    # Normalize up_hint
    if up_hint is not None:
        up_hint_norm = np.linalg.norm(up_hint)
        if forward_norm < 1e-4:
            up_hint_axis = np.array([0, 0, 1])
        else:
            up_hint_axis = up_hint / up_hint_norm

    # Default up direction and fallback for forward/up alignment
    if (up_hint is None) or (np.dot(forward_axis, up_hint_axis) > 0.99):
        up_hint_axis = np.array([0, 0, 1])
    # Second fallback in the case where up_hint was None and forward was world +Z
    if np.dot(forward, up_hint) > 0.99:
        up_hint_axis = np.array([1, 0, 0])

    # Build orthogonal basis
    right_axis = np.cross(forward_axis, up_hint_axis)
    up_axis = np.cross(right_axis, forward_axis)

    quat = quaternion.from_rotation_matrix(
        np.array(
            [
                [right_axis[0], right_axis[1], right_axis[2]],
                [forward_axis[0], forward_axis[1], forward_axis[2]],
                [up_axis[0], up_axis[1], up_axis[2]],
            ]
        ).T
    )
    return quat
