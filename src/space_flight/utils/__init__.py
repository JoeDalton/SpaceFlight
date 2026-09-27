import math
from typing import Union

import numpy as np
import quaternion


def rotate_single_vector(quat: np.quaternion, vector: np.ndarray):
    """
    Rotates vector by the rotation defined by quat.

    Uses the scalar Rodrigues-style formula v' = v + 2*w*(q_v x v) + 2*(q_v x
    (q_v x v)) worked out component-by-component in plain floats, instead of
    quaternion.rotate_vectors (which builds a full rotation matrix via
    generic, broadcasting-capable numpy ops meant for batches of vectors);
    for a lone 3-vector that generality is pure overhead and this is
    substantially faster (called once per ship per frame).
    """
    qx, qy, qz, qw = quat.x, quat.y, quat.z, quat.w
    vx, vy, vz = vector[0], vector[1], vector[2]
    tx = 2.0 * (qy * vz - qz * vy)
    ty = 2.0 * (qz * vx - qx * vz)
    tz = 2.0 * (qx * vy - qy * vx)
    return np.array(
        (
            vx + qw * tx + (qy * tz - qz * ty),
            vy + qw * ty + (qz * tx - qx * tz),
            vz + qw * tz + (qx * ty - qy * tx),
        )
    )


def rotation_matrix_coefficients(
    w: float, x: float, y: float, z: float
) -> tuple[float, float, float, float, float, float, float, float, float]:
    """
    The 9 coefficients, row by row, of the matrix R such that R @ v equals
    rotate_single_vector(np.quaternion(w, x, y, z), v), as plain floats.

    It is the same linear map written as a matrix, so it holds for any
    quaternion, not only unit ones (an integrated orientation drifts slightly
    off unit norm). Build it once to rotate several vectors: R's columns are
    the body axes in world coordinates, and its transpose rotates by the
    conjugate quaternion (world to body).
    """
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z
    return (
        1.0 - 2.0 * (yy + zz),
        2.0 * (xy - wz),
        2.0 * (xz + wy),
        2.0 * (xy + wz),
        1.0 - 2.0 * (xx + zz),
        2.0 * (yz - wx),
        2.0 * (xz - wy),
        2.0 * (yz + wx),
        1.0 - 2.0 * (xx + yy),
    )


def cross3(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """
    Cross product of two plain 3-vectors, worked out component-by-component
    in plain floats instead of np.cross (which, like quaternion.rotate_vectors,
    dispatches through generic broadcasting-capable numpy machinery meant for
    batches of vectors -- pure overhead for a lone pair of 3-vectors, and
    substantially slower).
    """
    return np.array(
        (
            a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0],
        )
    )


def normalize(vector: np.ndarray) -> np.ndarray:
    """
    Returns vector scaled to unit length: a 3D direction, or a quaternion's 4
    raw components (as used when renormalizing one drifting slightly out of
    unit norm after each integration step, e.g. in AsteroidField).

    Builds the squared norm as a plain float sum and calls math.sqrt on it
    directly, instead of going through np.linalg.norm's generic, broadcast-
    capable dispatch -- same pattern, and same reasoning, as
    rotate_single_vector/cross3: for a single fixed-size vector that
    generality is pure overhead.

    A 2nd-order Taylor expansion of sqrt around 1 was tried on top of this,
    to shortcut the sqrt call for the common near-unit-length input (a
    direction/quaternion that only drifted by a small numerical error, not a
    fresh arbitrary vector). It measured *slower* than calling math.sqrt
    directly (in CPython, math.sqrt is a single fast C call, and the extra
    branch and multiplications to evaluate the series cost more than the
    call they replace), and its ~1e-4 relative error broke exact-orthonormal
    assumptions elsewhere in the codebase -- so it was dropped in favour of
    a plain, exact math.sqrt.
    """
    if len(vector) == 3:
        x, y, z = vector[0], vector[1], vector[2]
        inv_norm = 1.0 / math.sqrt(x * x + y * y + z * z)
        return np.array((x * inv_norm, y * inv_norm, z * inv_norm))
    if len(vector) == 4:
        x, y, z, w = vector[0], vector[1], vector[2], vector[3]
        inv_norm = 1.0 / math.sqrt(x * x + y * y + z * z + w * w)
        return np.array((x * inv_norm, y * inv_norm, z * inv_norm, w * inv_norm))
    return vector / math.sqrt(float(np.dot(vector, vector)))


def magnitude(vector: np.ndarray) -> float:
    """
    Returns the Euclidean norm (magnitude) of vector: a 2D screen-space
    vector, a 3D direction/speed, or a quaternion's 4 raw components.

    Same reasoning as normalize/cross3/rotate_single_vector: builds the
    squared norm as a plain float sum and calls math.sqrt on it directly,
    instead of going through np.linalg.norm's generic, broadcast-capable
    dispatch -- for a single fixed-size vector that generality is pure
    overhead.
    """
    if len(vector) == 3:
        x, y, z = vector[0], vector[1], vector[2]
        return math.sqrt(x * x + y * y + z * z)
    if len(vector) == 2:
        x, y = vector[0], vector[1]
        return math.sqrt(x * x + y * y)
    if len(vector) == 4:
        x, y, z, w = vector[0], vector[1], vector[2], vector[3]
        return math.sqrt(x * x + y * y + z * z + w * w)
    return math.sqrt(float(np.dot(vector, vector)))


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
    characteristic times.

    The array branch is worked out component-by-component in plain floats
    instead of np.where/elementwise array arithmetic, which dispatch through
    numpy's generic, broadcast-capable machinery -- same reasoning, and same
    pattern, as cross3/magnitude/normalize: pure overhead for the small,
    fixed-size vectors this is actually called with (turn rates, thrust).
    """
    if dt == 0.0:
        return value

    # Choose response speed depending on press/release
    if isinstance(value, float) and isinstance(previous, float):
        tau = rise_time if value > previous else fall_time
        if tau <= 0.0:
            return value
        alpha = dt / (tau + dt)
        return previous + (value - previous) * alpha

    n = len(value)
    taus = [rise_time if value[i] > previous[i] else fall_time for i in range(n)]
    if any(tau <= 0.0 for tau in taus):
        return value
    result = np.empty(n)
    for i in range(n):
        alpha = dt / (taus[i] + dt)
        result[i] = previous[i] + (value[i] - previous[i]) * alpha
    return result


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
    acceptance is 8 / (4π/3) ≈ 1.91.

    :returns: A random vector in the unit sphere.
    """
    max_try = 50
    for _ in range(max_try):
        sample = np.random.uniform(low=-1, high=1, size=3)
        if magnitude(sample) <= 1.0:
            return sample
    # If no suitable sample is found, fall back to the origin (center of the sphere)
    return np.zeros(3)


def build_orthogonal_basis(
    normal: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Builds an orthonormal basis around *normal*.

    Returns three mutually perpendicular unit vectors (n, tangent, bitangent)
    suitable for expressing arbitrary directions in the hemisphere defined by
    *normal*. Handles degenerate (near-zero) input by falling back to +Z.

    :param normal: Preferred axis of the frame (need not be normalised).
    :returns: (normal, tangent, bitangent) — three orthonormal vectors
    """
    if normal is None:
        return None, None, None
    normal_norm = magnitude(normal)
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
    tangent = normalize(cross3(normal, helper))
    bitangent = normalize(cross3(normal, tangent))
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
    sample = normalize(sample)  # TODO Not necessary
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
    forward_norm = magnitude(forward)
    if forward_norm < 1e-4:
        forward_axis = np.array([0, 1, 0])
    else:
        forward_axis = forward / forward_norm

    # Normalize up_hint
    if up_hint is not None:
        up_hint_norm = magnitude(up_hint)
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
    right_axis = cross3(forward_axis, up_hint_axis)
    up_axis = cross3(right_axis, forward_axis)

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


def compute_next_power_of_2(x: float) -> float:
    """
    Computes the next power of two for float x

    :param x: The reference number
    :return: The next power of 2 superior than x
    """
    return 2 ** math.ceil(math.log2(max(x, 1)))
